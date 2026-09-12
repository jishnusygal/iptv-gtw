from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from app.auth import admin
from app.routers.export import endpoint

router = APIRouter(dependencies=[Depends(admin)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))


@router.get('/')
async def index(request: Request):
    settings = request.app.state.settings
    return templates.TemplateResponse(request=request, name='index.html', context={
        'playlist_url': endpoint(settings, '/playlist.m3u'), 'epg_url': endpoint(settings, '/epg.xml'),
        'countries': settings.countries, 'categories': settings.categories}, headers={'Cache-Control': 'no-store'})
