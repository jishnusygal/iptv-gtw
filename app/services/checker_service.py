import asyncio
import time
import httpx
from sqlalchemy import select, update
from app.models import Stream, now
from app.services.http_service import validate_public_url


async def probe(client, stream, timeout):
    started = time.monotonic()
    code = None
    headers = {}
    if stream.referrer:
        headers['Referer'] = stream.referrer
    if stream.user_agent:
        headers['User-Agent'] = stream.user_agent
    try:
        async with asyncio.timeout(timeout):
            url = stream.url
            for _ in range(6):
                await validate_public_url(url)
                async with client.stream('GET', url, headers={**headers, 'Range': 'bytes=0-1023'}, follow_redirects=False) as response:
                    code = response.status_code
                    if response.is_redirect:
                        url = str(response.url.join(response.headers['location']))
                        continue
                    response.raise_for_status()
                    # Read only a small chunk, never buffer a live broadcast.
                    async for chunk in response.aiter_raw(chunk_size=1024):
                        if chunk:
                            return 'ONLINE', code, int((time.monotonic() - started) * 1000)
                    break
    except (httpx.HTTPError, TimeoutError, ValueError, OSError):
        pass
    return 'OFFLINE', code, int((time.monotonic() - started) * 1000)


async def check(db, client, settings, on_progress=None):
    semaphore = asyncio.Semaphore(settings.check_concurrency)
    async with db.sessions() as session:
        streams = (await session.scalars(select(Stream))).all()
    total = len(streams)

    async def one(stream):
        async with semaphore:
            status, code, latency = await probe(client, stream, settings.check_timeout)
            return {'id': stream.id, 'status': status, 'http_status': code, 'latency_ms': latency, 'last_checked': now()}

    # Bound pending tasks as well as sockets, and persist progress in batches.
    for start in range(0, total, 200):
        results = await asyncio.gather(*(one(s) for s in streams[start:start + 200]))
        async with db.sessions.begin() as session:
            await session.execute(update(Stream), results)
        if on_progress:
            on_progress(min(start + 200, total), total)
    return {'streams_checked': total}
