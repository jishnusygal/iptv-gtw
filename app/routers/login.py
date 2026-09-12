from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.auth import SESSION_COOKIE, SESSION_MAX_AGE, cookie_is_secure, create_session, is_configured, verify_password
from app.schemas import LoginRequest

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))


@router.get('/login')
async def login_page(request: Request):
    if not await is_configured(request):
        return RedirectResponse('/setup')
    return templates.TemplateResponse(request=request, name='login.html', context={'host': request.url.netloc},
                                       headers={'Cache-Control': 'no-store'})


@router.post('/login')
async def login(body: LoginRequest, request: Request, response: Response):
    if not await verify_password(request, body.username, body.password):
        raise HTTPException(401, 'Invalid username or password')
    response.set_cookie(SESSION_COOKIE, await create_session(request), max_age=SESSION_MAX_AGE,
                         httponly=True, samesite='lax', secure=cookie_is_secure(request))
    return {'ok': True}


@router.post('/logout')
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {'ok': True}
