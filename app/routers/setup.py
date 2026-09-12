import secrets
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.auth import SESSION_COOKIE, SESSION_MAX_AGE, cookie_is_secure, create_session, is_configured
from app.schemas import SetupRequest

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))


@router.get('/setup')
async def setup_page(request: Request):
    if await is_configured(request):
        return RedirectResponse('/')
    return templates.TemplateResponse(request=request, name='setup.html', context={'host': request.url.netloc},
                                       headers={'Cache-Control': 'no-store'})


@router.post('/setup')
async def create_admin(body: SetupRequest, request: Request, response: Response):
    if await is_configured(request):
        raise HTTPException(409, 'Admin account already configured')
    token = secrets.token_hex(32)
    await request.app.state.db.update_json('admin_account', username=body.username, password=body.password, export_token=token)
    # is_configured() above already cached the old (unconfigured) credentials on this
    # request; refresh the cache so create_session() below signs with the new ones.
    request.state.credentials = (body.username, body.password, token)
    # Sign the new admin straight in, matching how first-run wizards elsewhere behave.
    response.set_cookie(SESSION_COOKIE, await create_session(request), max_age=SESSION_MAX_AGE,
                         httponly=True, samesite='lax', secure=cookie_is_secure(request))
    return {'ok': True}
