from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.auth import credentials_for, effective_scheme, export_auth, profile_export_auth
from app.services.export_service import epg, playlist

router = APIRouter(dependencies=[Depends(export_auth)])
profile_router = APIRouter(prefix='/profiles/{profile_id}', dependencies=[Depends(profile_export_auth)])


def _url(request, path, token):
    # A reverse proxy forwards the original Host header unchanged but terminates TLS itself,
    # so only the scheme (not the host) needs the forwarded header as a fallback source.
    return f'{effective_scheme(request)}://{request.url.netloc}' + path + '?' + urlencode({'token': token})


async def endpoint(request, path):
    _, _, token = await credentials_for(request)
    return _url(request, path, token)


def profile_endpoint(request, profile_id, path, token):
    return _url(request, f'/profiles/{profile_id}{path}', token)


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


@profile_router.get('/playlist.m3u')
async def profile_m3u(request: Request, profile_id: int):
    state = request.app.state
    profile = request.state.profile
    guide_url = profile_endpoint(request, profile_id, '/epg.xml', profile.token)
    content = await playlist(state.db, guide_url, channel_ids=[c.id for c in profile.channels])
    return Response(content, media_type='audio/x-mpegurl',
                     headers={'Content-Disposition': f'attachment; filename="{profile.name}.m3u"', 'Cache-Control': 'no-store'})


@profile_router.get('/epg.xml')
async def profile_xml(request: Request, profile_id: int):
    state = request.app.state
    profile = request.state.profile
    try:
        docs = await state.guides.get(state.client, state.settings)
    except Exception:
        raise HTTPException(502, 'EPG source unavailable or invalid') from None
    content = await epg(state.db, docs, channel_ids=[c.id for c in profile.channels])
    return Response(content, media_type='application/xml', headers={'Cache-Control': 'no-store'})
