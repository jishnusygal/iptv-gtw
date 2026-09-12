import asyncio
import copy
import gzip
import io
import xml.etree.ElementTree as ET
from defusedxml.ElementTree import fromstring
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models import Channel
from app.services.http_service import download


def clean(value):
    return ''.join(c for c in str(value or '') if ord(c) >= 32).replace('"', "'")


async def active_channels(db, channel_ids=None):
    statement = select(Channel).where(Channel.is_enabled.is_(True))
    if channel_ids is not None:
        statement = statement.where(Channel.id.in_(channel_ids))
    async with db.sessions() as session:
        channels = (await session.scalars(statement.options(selectinload(Channel.streams)).order_by(Channel.channel_number))).all()
    return [(c, min((s for s in c.streams if s.status == 'ONLINE'), key=lambda s: (s.latency_ms if s.latency_ms is not None else 999999, s.id)))
            for c in channels if any(s.status == 'ONLINE' for s in c.streams)]


async def playlist(db, guide_url, channel_ids=None):
    lines = [f'#EXTM3U x-tvg-url="{clean(guide_url)}"']
    for c, s in await active_channels(db, channel_ids):
        attrs = {'tvg-id': c.epg_id or c.tvg_id, 'tvg-name': c.tvg_name or c.name,
                 'tvg-logo': c.logo_url, 'tvg-chno': c.channel_number, 'group-title': c.group_title}
        lines.append('#EXTINF:-1 ' + ' '.join(f'{k}="{clean(v)}"' for k, v in attrs.items()) + ',' + clean(c.name))
        if s.referrer:
            lines.append('#EXTVLCOPT:http-referrer=' + clean(s.referrer))
        if s.user_agent:
            lines.append('#EXTVLCOPT:http-user-agent=' + clean(s.user_agent))
        lines.append(clean(s.url))
    return '\n'.join(lines) + '\n'


class GuideCache:
    def __init__(self):
        self.documents = []
        self.updated = 0.0
        self.lock = asyncio.Lock()

    async def get(self, client, settings):
        import time
        async with self.lock:
            if time.monotonic() - self.updated < 3600:
                return self.documents
            documents = []
            for url in filter(None, (s.strip() for s in settings.epg_urls.split(','))):
                payload = await download(client, url, settings.max_download_bytes)
                if payload[:2] == b'\x1f\x8b':
                    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as zipped:
                        payload = zipped.read(settings.max_download_bytes + 1)
                    if len(payload) > settings.max_download_bytes:
                        raise ValueError('Decompressed EPG exceeds limit')
                document = await asyncio.to_thread(fromstring, payload)
                if document.tag != 'tv':
                    raise ValueError('Expected XMLTV tv root')
                documents.append(document)
            self.documents, self.updated = documents, time.monotonic()
            return documents


async def epg(db, documents, channel_ids=None):
    root = ET.Element('tv', {'generator-info-name': 'IPTV-Org Pilot'})
    ids = set()
    for channel, _ in await active_channels(db, channel_ids):
        key = channel.epg_id or channel.tvg_id
        if key in ids:
            continue
        ids.add(key)
        element = ET.SubElement(root, 'channel', {'id': key})
        ET.SubElement(element, 'display-name').text = channel.tvg_name or channel.name
        if channel.logo_url:
            ET.SubElement(element, 'icon', {'src': channel.logo_url})
    seen = set()
    for document in documents:
        for programme in document.findall('programme'):
            identity = (programme.get('channel'), programme.get('start'), programme.get('stop'))
            if identity[0] in ids and identity not in seen:
                root.append(copy.deepcopy(programme))
                seen.add(identity)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)
