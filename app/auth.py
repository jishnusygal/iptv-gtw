import hashlib
import hmac
import secrets
import time
from fastapi import HTTPException, Request

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


def _sign(secret, issued_at, fingerprint):
    return hmac.new(secret.encode(), f'{issued_at}.{fingerprint}'.encode(), hashlib.sha256).hexdigest()


async def create_session(request):
    secret = await _session_secret(request)
    _, password, _ = await credentials_for(request)
    issued_at = int(time.time())
    return f'{issued_at}.{_sign(secret, issued_at, _fingerprint(password))}'


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
    return secrets.compare_digest(signature, _sign(secret, issued_at, _fingerprint(password)))


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
