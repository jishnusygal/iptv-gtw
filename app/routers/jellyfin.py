import asyncio
import logging
import socket
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from app.auth import admin
from app.schemas import JellyfinConfig
from app.services import jellyfin_service

log = logging.getLogger(__name__)
router = APIRouter(prefix='/api/jellyfin', dependencies=[Depends(admin)])

INTERNAL_PORT = 8000  # baked into the Dockerfile's CMD; this container always listens here


async def _guess_jellyfin_url():
    # Most compose stacks that pair this app with Jellyfin name its service "jellyfin";
    # if that hostname actually resolves on this container's network, it's almost
    # certainly the right one, so offer it as an editable starting point rather than
    # making the admin type a value that's usually the same anyway.
    try:
        await asyncio.get_running_loop().getaddrinfo('jellyfin', 8096, type=socket.SOCK_STREAM)
    except OSError:
        return None
    return 'http://jellyfin:8096'


@router.get('')
async def status(request: Request):
    config = await jellyfin_service.read_config(request.app.state.db)
    detected_url = await _guess_jellyfin_url()
    detected_base_url = f'http://{socket.gethostname()}:{INTERNAL_PORT}'
    return {'url': config.get('url') or detected_url, 'url_detected': not config.get('url') and bool(detected_url),
            'base_url': config.get('base_url') or detected_base_url, 'base_url_detected': not config.get('base_url'),
            'api_key_set': bool(config.get('api_key')), 'auto_sync': config.get('auto_sync', False),
            'last_push': config.get('last_push'), 'last_error': config.get('last_error') or None}


@router.post('')
async def save(body: JellyfinConfig, request: Request):
    existing = await jellyfin_service.read_config(request.app.state.db)
    api_key = body.api_key or existing.get('api_key')
    if not api_key:
        raise HTTPException(422, 'An API key is required')
    try:
        await jellyfin_service.test_connection(request.app.state.client, body.url, api_key)
    except httpx.HTTPStatusError as exc:
        log.error('Jellyfin connection test to %s was rejected (HTTP %s)', body.url, exc.response.status_code)
        raise HTTPException(400, f'Jellyfin at {body.url} responded with HTTP {exc.response.status_code} — check the API key.') from None
    except Exception as exc:
        log.error('Jellyfin connection test to %s failed (%s)', body.url, type(exc).__name__)
        raise HTTPException(400, f'Could not reach Jellyfin at {body.url} ({type(exc).__name__}). '
                                  'Check the URL and that this container can reach it on the network.') from None
    changes = {'url': body.url, 'api_key': api_key, 'base_url': body.base_url, 'auto_sync': body.auto_sync}
    if body.url != existing.get('url'):
        changes['tuner_id'] = None
        changes['listing_id'] = None
    await request.app.state.db.update_json('jellyfin', **changes)
    return {'ok': True}


@router.post('/push')
async def push(request: Request):
    result = await jellyfin_service.push(request.app.state.db, request.app.state.client, request.app.state.settings)
    if not result['ok']:
        raise HTTPException(502, result['error'])
    return {'ok': True, 'confirmed': result.get('confirmed', False)}
