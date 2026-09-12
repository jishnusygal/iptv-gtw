from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from app.auth import require_ready
from app.routers.export import endpoint

router = APIRouter(dependencies=[Depends(require_ready)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))


@router.get('/')
async def index(request: Request):
    settings = request.app.state.settings
    return templates.TemplateResponse(request=request, name='index.html', context={
        'playlist_url': await endpoint(request, '/playlist.m3u'), 'epg_url': await endpoint(request, '/epg.xml'),
        'countries': settings.countries, 'categories': settings.categories,
        'sync_interval_hours': settings.sync_interval_hours}, headers={'Cache-Control': 'no-store'})
