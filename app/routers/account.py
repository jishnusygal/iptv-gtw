import secrets
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.auth import (SESSION_COOKIE, SESSION_MAX_AGE, admin, cookie_is_secure, create_session, credentials_for,
                       rotate_session_generation, verify_password)
from app.schemas import PasswordChange

router = APIRouter(prefix='/api/account', dependencies=[Depends(admin)])


@router.get('')
async def status(request: Request):
    settings = request.app.state.settings
    username, _, _ = await credentials_for(request)
    return {'username': username, 'password_locked': settings.admin_password is not None,
            'export_token_locked': settings.export_token is not None}


@router.post('/password')
async def change_password(body: PasswordChange, request: Request, response: Response):
    if request.app.state.settings.admin_password is not None:
        raise HTTPException(409, 'Password is set via ADMIN_PASSWORD and cannot be changed here')
    username, _, token = await credentials_for(request)
    if not await verify_password(request, username, body.current_password):
        raise HTTPException(401, 'Current password is incorrect')
    await request.app.state.db.update_json('admin_account', password=body.new_password)
    # Bump the session generation so every previously issued session is revoked for good,
    # even one whose fingerprint happens to match again if the password is changed back later.
    await rotate_session_generation(request)
    # credentials_for() cached the old password on this request; refresh it so create_session()
    # below signs the new cookie with the new password, keeping the current session alive
    # instead of logging this browser out (password rotation invalidates every other session).
    request.state.credentials = (username, body.new_password, token)
    response.set_cookie(SESSION_COOKIE, await create_session(request), max_age=SESSION_MAX_AGE,
                         httponly=True, samesite='lax', secure=cookie_is_secure(request))
    return {'ok': True}


@router.post('/export-token')
async def regenerate_export_token(request: Request):
    if request.app.state.settings.export_token is not None:
        raise HTTPException(409, 'Export token is set via EXPORT_TOKEN and cannot be changed here')
    await request.app.state.db.update_json('admin_account', export_token=secrets.token_hex(32))
    return {'ok': True}
