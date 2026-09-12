from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.auth import export_auth
from app.services.export_service import epg, playlist

router = APIRouter(dependencies=[Depends(export_auth)])


def endpoint(settings, path):
    return settings.public_base_url.rstrip('/') + path + '?' + urlencode({'token': settings.export_token.get_secret_value()})


@router.get('/playlist.m3u')
async def m3u(request: Request):
    state = request.app.state
    content = await playlist(state.db, endpoint(state.settings, '/epg.xml'))
    return Response(content, media_type='audio/x-mpegurl', headers={'Content-Disposition': 'attachment; filename="pilot.m3u"', 'Cache-Control': 'no-store'})


@router.get('/epg.xml')
async def xml(request: Request):
    state = request.app.state
    try:
        docs = await state.guides.get(state.client, state.settings)
    except Exception:
        raise HTTPException(502, 'EPG source unavailable or invalid') from None
    return Response(await epg(state.db, docs), media_type='application/xml', headers={'Cache-Control': 'no-store'})
