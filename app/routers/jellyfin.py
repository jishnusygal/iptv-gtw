from fastapi import APIRouter, Depends, HTTPException, Request
from app.auth import admin
from app.schemas import JellyfinConfig
from app.services import jellyfin_service

router = APIRouter(prefix='/api/jellyfin', dependencies=[Depends(admin)])


@router.get('')
async def status(request: Request):
    config = await jellyfin_service.read_config(request.app.state.db)
    return {'url': config.get('url'), 'base_url': config.get('base_url'), 'api_key_set': bool(config.get('api_key')),
            'auto_sync': config.get('auto_sync', False), 'last_push': config.get('last_push'), 'last_error': config.get('last_error') or None}


@router.post('')
async def save(body: JellyfinConfig, request: Request):
    existing = await jellyfin_service.read_config(request.app.state.db)
    api_key = body.api_key or existing.get('api_key')
    if not api_key:
        raise HTTPException(422, 'An API key is required')
    try:
        await jellyfin_service.test_connection(request.app.state.client, body.url, api_key)
    except Exception:
        raise HTTPException(400, 'Could not reach Jellyfin with that URL and API key') from None
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
    return {'ok': True}
