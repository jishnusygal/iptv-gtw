import asyncio
import hashlib
import json
import re
import unicodedata
from sqlalchemy import func, select
from app.models import Channel, State, Stream, now
from app.services.http_service import download


def normalize(title):
    title = re.sub(r'\b(?:HD|SD|FHD|UHD|4K|\d{3,4}p)\b', '', title, flags=re.I)
    return ''.join(c for c in unicodedata.normalize('NFKC', title).casefold() if c.isalnum())


async def sync(db, client, settings, countries=None, categories=None):
    countries = settings.values('countries') if countries is None else {x.lower() for x in countries}
    categories = settings.values('categories') if categories is None else {x.lower() for x in categories}

    async def fetch(name):
        data = json.loads(await download(client, f'{settings.api_base_url}/{name}.json', settings.max_download_bytes))
        if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
            raise ValueError('Invalid upstream schema')
        return data

    metadata, streams, logos, feeds = await asyncio.gather(*(fetch(n) for n in ('channels', 'streams', 'logos', 'feeds')))
    if not metadata or not streams:
        raise ValueError('Empty upstream snapshot; retaining existing data')
    canonical = {c['id']: c for c in metadata if c.get('id') and c.get('name')}
    names = {}
    for c in canonical.values():
        for title in [c['name'], *c.get('alt_names', [])]:
            names.setdefault(normalize(title), set()).add(c['id'])
    logo_map = {x['channel']: x['url'] for x in logos if x.get('channel') and x.get('url') and x.get('in_use', True)}
    language_map = {x['channel']: ','.join(x.get('languages') or []) for x in feeds if x.get('is_main')}
    grouped = {}
    for stream in streams:
        url = stream.get('url', '')
        if not url.startswith(('https://', 'http://')) or any(ord(c) < 32 for c in url):
            continue
        key = stream.get('channel') or stream.get('tvg_id')
        if not key:
            title = normalize(stream.get('title', ''))
            matches = names.get(title, set())
            if len(matches) == 1:
                key = next(iter(matches))
            elif not countries and not categories and title:
                key = 'unmatched:' + hashlib.sha256(title.encode()).hexdigest()[:24]
            else:
                continue
        c = canonical.get(key)
        if c is None:
            if not key.startswith('unmatched:'):
                continue
            c = {'id': key, 'name': stream['title'], 'country': '', 'categories': []}
        if countries and c.get('country', '').lower() not in countries:
            continue
        if categories and not categories.intersection(x.lower() for x in c.get('categories', [])):
            continue
        grouped.setdefault(key, {'metadata': c, 'streams': {}})['streams'][url] = stream
    async with db.sessions.begin() as session:
        existing = {c.tvg_id: c for c in (await session.scalars(select(Channel))).all()}
        number = (await session.scalar(select(func.max(Channel.channel_number)))) or 0
        for key, group in grouped.items():
            c = group['metadata']
            channel = existing.get(key)
            if channel is None:
                number += 1
                channel = Channel(channel_number=number, name=c['name'], tvg_id=key, tvg_name=c['name'],
                                  group_title=', '.join(c.get('categories', [])) or 'General',
                                  country=c.get('country'), language=language_map.get(key), logo_url=logo_map.get(key))
                session.add(channel)
                await session.flush()
            else:
                channel.logo_url = logo_map.get(key, channel.logo_url)
                channel.language = language_map.get(key, channel.language)
            old = {s.url: s for s in (await session.scalars(select(Stream).where(Stream.channel_id == channel.id))).all()}
            for url, raw in group['streams'].items():
                stream = old.pop(url, None)
                if stream is None:
                    stream = Stream(channel_id=channel.id, url=url)
                    session.add(stream)
                stream.resolution = raw.get('quality')
                stream.referrer = raw.get('referrer')
                stream.user_agent = raw.get('user_agent')
            for removed in old.values():
                await session.delete(removed)
        # Channels retain curation and numbers; absent mirrors must not remain exportable.
        for key, channel in existing.items():
            if key not in grouped:
                for stream in (await session.scalars(select(Stream).where(Stream.channel_id == channel.id))).all():
                    await session.delete(stream)
        await session.merge(State(key='last_sync', value=now().isoformat()))
    return {'channels_synced': len(grouped), 'streams_synced': sum(len(g['streams']) for g in grouped.values())}
