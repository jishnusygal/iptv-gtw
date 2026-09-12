import secrets
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

basic = HTTPBasic(auto_error=False)


async def admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic)):
    settings = request.app.state.settings
    if credentials is None or not (secrets.compare_digest(credentials.username.encode(), settings.admin_username.encode())
            and secrets.compare_digest(credentials.password.encode(), settings.admin_password.get_secret_value().encode())):
        raise HTTPException(401, 'Admin credentials required', headers={'WWW-Authenticate': 'Basic realm="IPTV-Org Pilot"'})
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('x-pilot-request') != '1':
        raise HTTPException(403, 'X-Pilot-Request: 1 required')


async def export_auth(request: Request, token: str = ''):
    if not secrets.compare_digest(token.encode(), request.app.state.settings.export_token.get_secret_value().encode()):
        raise HTTPException(401, 'Valid export token required')
