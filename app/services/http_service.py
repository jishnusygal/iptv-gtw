import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit
import httpx


async def validate_public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only public HTTP(S) URLs are supported')
    addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private network destinations are blocked')


async def download(client, url, limit):
    # Follow redirects explicitly so each destination is checked.
    for _ in range(6):
        await validate_public_url(url)
        async with client.stream('GET', url, follow_redirects=False) as response:
            if response.is_redirect:
                url = str(response.url.join(response.headers['location']))
                continue
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError('Upstream document exceeds download limit')
            return bytes(data)
    raise httpx.TooManyRedirects('Too many redirects')
