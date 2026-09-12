import hashlib
import hmac
import secrets
import time
from fastapi import HTTPException, Request
from sqlalchemy.orm import selectinload
from app.models import Profile

SESSION_COOKIE = 'session'
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days; re-login is cheap for a single-admin tool


async def resolve_credentials(settings, db):
    # Credentials come from env/.env when set there; a wizard-created admin account
    # (app/routers/setup.py) stores them in the State table instead, for deployments
    # that never configure ADMIN_PASSWORD/EXPORT_TOKEN before first start.
    username = settings.admin_username
    password = settings.admin_password.get_secret_value() if settings.admin_password else None
    token = settings.export_token.get_secret_value() if settings.export_token else None
    if password is None or token is None:
        stored = await db.read_json('admin_account')
        username = stored.get('username', username)
        password = password or stored.get('password')
        token = token or stored.get('export_token')
    return username, password, token


async def credentials_for(request):
    # Multiple dependencies/handlers may need credentials within the same request
    # (admin/export_auth, then endpoint() for the URLs shown on the page); resolve once.
    if not hasattr(request.state, 'credentials'):
        request.state.credentials = await resolve_credentials(request.app.state.settings, request.app.state.db)
    return request.state.credentials


async def is_configured(request):
    _, password, _ = await credentials_for(request)
    return password is not None


async def verify_password(request, username, password):
    expected_username, expected_password, _ = await credentials_for(request)
    return expected_password is not None and secrets.compare_digest(username.encode(), expected_username.encode()) \
        and secrets.compare_digest(password.encode(), expected_password.encode())


def effective_scheme(request):
    # Behind a reverse proxy, the connection to this app is plain HTTP even though the
    # browser is on HTTPS; trust the forwarded header as a fallback source only.
    return request.headers.get('x-forwarded-proto', request.url.scheme)


def cookie_is_secure(request):
    return effective_scheme(request) == 'https'


async def _session_secret(request):
    # Static for the process lifetime once loaded; cache on app.state to avoid a
    # DB round trip on every authenticated request (dashboard polls every 5s).
    if not hasattr(request.app.state, 'session_secret'):
        db = request.app.state.db
        stored = await db.read_json('security')
        secret = stored.get('session_secret')
        if not secret:
            secret = secrets.token_hex(32)
            await db.update_json('security', session_secret=secret)
        request.app.state.session_secret = secret
    return request.app.state.session_secret


def _fingerprint(password):
    # Binds the session signature to the current password so rotating credentials
    # invalidates sessions issued under the old ones, without a session store.
    return hashlib.sha256(password.encode()).hexdigest()[:16]


async def _session_generation(request):
    # Bumped by rotate_session_generation() on every explicit password change, independent
    # of the fingerprint above: without this, changing the password from A to B and back to
    # A would make a session issued under the original A valid again (same fingerprint),
    # even though the admin's intent when changing to B was to revoke every prior session.
    if not hasattr(request.app.state, 'session_generation'):
        stored = await request.app.state.db.read_json('security')
        request.app.state.session_generation = stored.get('session_generation', 0)
    return request.app.state.session_generation


async def rotate_session_generation(request):
    generation = await _session_generation(request) + 1
    await request.app.state.db.update_json('security', session_generation=generation)
    request.app.state.session_generation = generation
    return generation


def _sign(secret, issued_at, fingerprint, generation):
    return hmac.new(secret.encode(), f'{issued_at}.{fingerprint}.{generation}'.encode(), hashlib.sha256).hexdigest()


async def create_session(request):
    secret = await _session_secret(request)
    generation = await _session_generation(request)
    _, password, _ = await credentials_for(request)
    issued_at = int(time.time())
    return f'{issued_at}.{_sign(secret, issued_at, _fingerprint(password), generation)}'


async def _session_valid(request):
    cookie = request.cookies.get(SESSION_COOKIE, '')
    issued_at, _, signature = cookie.partition('.')
    if not issued_at.isdigit() or not signature:
        return False
    issued_at = int(issued_at)
    if time.time() - issued_at > SESSION_MAX_AGE:
        return False
    _, password, _ = await credentials_for(request)
    if password is None:
        return False
    secret = await _session_secret(request)
    generation = await _session_generation(request)
    return secrets.compare_digest(signature, _sign(secret, issued_at, _fingerprint(password), generation))


async def require_ready(request: Request):
    # Browser-facing routes only: send an unconfigured install to setup, a signed-out one to login.
    if not await is_configured(request):
        raise HTTPException(307, 'Setup required', headers={'Location': '/setup'})
    if not await _session_valid(request):
        raise HTTPException(307, 'Sign in required', headers={'Location': '/login'})


async def admin(request: Request):
    if not await is_configured(request):
        raise HTTPException(503, 'Setup required; create the admin account first')
    if not await _session_valid(request):
        raise HTTPException(401, 'Sign in required')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('x-pilot-request') != '1':
        raise HTTPException(403, 'X-Pilot-Request: 1 required')


async def export_auth(request: Request, token: str = ''):
    _, _, export_token = await credentials_for(request)
    if export_token is None:
        raise HTTPException(503, 'Setup required; create the admin account first')
    if not secrets.compare_digest(token.encode(), export_token.encode()):
        raise HTTPException(401, 'Valid export token required')


async def get_profile(session, profile_id, *, with_channels=False):
    options = [selectinload(Profile.channels)] if with_channels else []
    profile = await session.get(Profile, profile_id, options=options)
    if profile is None:
        raise HTTPException(404, 'Profile not found')
    return profile


async def profile_export_auth(request: Request, profile_id: int, token: str = ''):
    # Each profile carries its own token (unlike the single shared EXPORT_TOKEN above),
    # so a leaked profile link only exposes that profile's channel subset. channels is
    # eager-loaded since the session closes before the route handler reads it.
    async with request.app.state.db.sessions() as session:
        profile = await get_profile(session, profile_id, with_channels=True)
    if not secrets.compare_digest(token.encode(), profile.token.encode()):
        raise HTTPException(401, 'Valid profile token required')
    request.state.profile = profile
