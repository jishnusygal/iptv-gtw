from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.auth import credentials_for, effective_scheme, export_auth
from app.services.export_service import epg, playlist

router = APIRouter(dependencies=[Depends(export_auth)])


async def endpoint(request, path):
    # A reverse proxy forwards the original Host header unchanged but terminates TLS itself,
    # so only the scheme (not the host) needs the forwarded header as a fallback source.
    _, _, token = await credentials_for(request)
    return f'{effective_scheme(request)}://{request.url.netloc}' + path + '?' + urlencode({'token': token})


@router.get('/playlist.m3u')
async def m3u(request: Request):
    state = request.app.state
    content = await playlist(state.db, await endpoint(request, '/epg.xml'))
    return Response(content, media_type='audio/x-mpegurl', headers={'Content-Disposition': 'attachment; filename="pilot.m3u"', 'Cache-Control': 'no-store'})


@router.get('/epg.xml')
async def xml(request: Request):
    state = request.app.state
    try:
        docs = await state.guides.get(state.client, state.settings)
    except Exception:
        raise HTTPException(502, 'EPG source unavailable or invalid') from None
    return Response(await epg(state.db, docs), media_type='application/xml', headers={'Cache-Control': 'no-store'})
