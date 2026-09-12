import logging
from urllib.parse import urlencode
import httpx
from app.auth import resolve_credentials
from app.models import now

log = logging.getLogger(__name__)


def _headers(api_key):
    return {'X-MediaBrowser-Token': api_key}


async def read_config(db):
    return await db.read_json('jellyfin')


async def test_connection(client, url, api_key):
    response = await client.get(f'{url.rstrip("/")}/System/Info', headers=_headers(api_key))
    response.raise_for_status()
    return response.json()


async def _register(client, url, api_key, m3u_url, epg_url, tuner_id, listing_id):
    url = url.rstrip('/')
    tuner = await client.post(f'{url}/LiveTv/TunerHosts', headers=_headers(api_key), json={'Id': tuner_id, 'Url': m3u_url, 'Type': 'm3u'})
    tuner.raise_for_status()
    listing = await client.post(f'{url}/LiveTv/ListingProviders', headers=_headers(api_key),
                                 params={'validateListings': 'false', 'validateLogin': 'false'},
                                 json={'Id': listing_id, 'Type': 'xmltv', 'Path': epg_url, 'EnableAllTuners': True})
    listing.raise_for_status()
    tasks = await client.get(f'{url}/ScheduledTasks', headers=_headers(api_key))
    tasks.raise_for_status()
    task = next((t for t in tasks.json() if t.get('Key') == 'RefreshGuide'), None)
    if task:
        (await client.post(f'{url}/ScheduledTasks/Running/{task["Id"]}', headers=_headers(api_key))).raise_for_status()
    return tuner.json().get('Id'), listing.json().get('Id')


async def push(db, client, settings):
    config = await read_config(db)
    if not (config.get('url') and config.get('api_key') and config.get('base_url')):
        return {'ok': False, 'error': 'Jellyfin is not configured yet.'}
    _, _, token = await resolve_credentials(settings, db)
    if not token:
        return {'ok': False, 'error': 'Create the admin account before connecting Jellyfin.'}
    base = config['base_url'].rstrip('/')
    m3u_url = f"{base}/playlist.m3u?{urlencode({'token': token})}"
    epg_url = f"{base}/epg.xml?{urlencode({'token': token})}"
    try:
        tuner_id, listing_id = await _register(client, config['url'], config['api_key'], m3u_url, epg_url,
                                                config.get('tuner_id'), config.get('listing_id'))
    except httpx.HTTPStatusError as exc:
        log.error('Jellyfin push to %s was rejected (HTTP %s)', config['url'], exc.response.status_code)
        error = f'Jellyfin at {config["url"]} responded with HTTP {exc.response.status_code} — check the API key.'
        await db.update_json('jellyfin', last_error=error)
        return {'ok': False, 'error': error}
    except Exception as exc:
        log.error('Jellyfin push to %s failed (%s)', config['url'], type(exc).__name__)
        error = f'Could not reach Jellyfin at {config["url"]} ({type(exc).__name__}).'
        await db.update_json('jellyfin', last_error=error)
        return {'ok': False, 'error': error}
    changes = {'last_push': now().isoformat(), 'last_error': ''}
    if tuner_id:
        changes['tuner_id'] = tuner_id
    if listing_id:
        changes['listing_id'] = listing_id
    await db.update_json('jellyfin', **changes)
    return {'ok': True, 'error': None}


async def push_if_enabled(db, client, settings):
    config = await read_config(db)
    if config.get('auto_sync'):
        await push(db, client, settings)
