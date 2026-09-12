import asyncio
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.config import Settings
from app.database import Database
from app.main import create_app
from app.models import Channel, Stream
from app.services import sync_service, checker_service
from app.services.export_service import epg, playlist, GuideCache
from app.services.jobs import Jobs


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, database_url=f'sqlite+aiosqlite:///{tmp_path}/test.db',
                    admin_password='test-password-123', export_token='test-export-token-1234567890',
                    scheduler_enabled=False, sync_on_start=False)


@pytest.fixture
async def db(settings):
    database = Database(settings.database_url)
    await database.initialize()
    yield database
    await database.engine.dispose()


def login(client, password, username='admin'):
    assert client.post('/login', json={'username': username, 'password': password}).status_code == 200


async def seed(db):
    async with db.sessions.begin() as session:
        c = Channel(channel_number=1, name='News "One"\nInjected', tvg_id='News.us', epg_id='guide.news', group_title='News')
        session.add(c)
        await session.flush()
        session.add_all([Stream(channel_id=c.id, url='https://example.com/slow', status='ONLINE', latency_ms=90),
                         Stream(channel_id=c.id, url='https://example.com/fast', status='ONLINE', latency_ms=10),
                         Stream(channel_id=c.id, url='https://example.com/dead', status='OFFLINE')])
        session.add(Channel(channel_number=2, name='Disabled', tvg_id='Disabled.us', is_enabled=False))


def fixture_feed(monkeypatch, streams=None):
    data = {'channels': [{'id': 'News.us', 'name': 'News', 'country': 'US', 'categories': ['news']}],
            'streams': streams or [{'channel': 'News.us', 'url': 'https://example.com/one'},
                                   {'channel': None, 'title': 'News HD', 'url': 'https://example.com/two'},
                                   {'channel': 'News.us', 'url': 'https://example.com/one'}],
            'logos': [{'channel': 'News.us', 'url': 'https://example.com/logo', 'in_use': True}], 'feeds': []}
    async def download(client, url, limit):
        import json
        return json.dumps(data[url.rsplit('/', 1)[1].split('.')[0]]).encode()
    monkeypatch.setattr(sync_service, 'download', download)
    return data


async def test_sync_dedup_and_preserve_curation(db, settings, monkeypatch):
    data = fixture_feed(monkeypatch)
    await sync_service.sync(db, None, settings)
    async with db.sessions.begin() as session:
        c = await session.scalar(select(Channel))
        c.name, c.group_title, c.is_enabled, c.epg_id = 'Custom', 'My news', False, 'custom.id'
        c.channel_number = 7
    data['streams'] = [{'channel': 'News.us', 'url': 'https://example.com/one'}]
    await sync_service.sync(db, None, settings)
    async with db.sessions() as session:
        c = await session.scalar(select(Channel))
        assert (c.name, c.group_title, c.is_enabled, c.channel_number, c.epg_id) == ('Custom', 'My news', False, 7, 'custom.id')
        assert len((await session.scalars(select(Stream))).all()) == 1


async def test_filter_and_atomic_failure(db, settings, monkeypatch):
    data = fixture_feed(monkeypatch)
    await sync_service.sync(db, None, settings, countries=['US'], categories=['news'])
    data['streams'] = []
    with pytest.raises(ValueError):
        await sync_service.sync(db, None, settings)
    async with db.sessions() as session:
        assert len((await session.scalars(select(Stream))).all()) == 2
    data['streams'] = [{'channel': 'News.us', 'url': 'https://example.com/one'}]
    await sync_service.sync(db, None, settings, countries=['in'])
    async with db.sessions() as session:
        assert not (await session.scalars(select(Stream))).all()


async def test_playlist_best_mirror_and_xml_override(db):
    await seed(db)
    result = await playlist(db, 'https://pilot.example/epg.xml')
    assert result.count('#EXTINF:') == 1
    assert 'tvg-chno="1"' in result and 'tvg-id="guide.news"' in result
    assert 'https://example.com/fast' in result and '/slow' not in result and '/dead' not in result
    assert '\nInjected' not in result
    doc = ET.fromstring('<tv><programme channel="guide.news" start="20260912010000 +0000"><title>News &amp; weather</title></programme><programme channel="other"/></tv>')
    guide = ET.fromstring(await epg(db, [doc, doc]))
    assert len(guide.findall('programme')) == 1
    assert guide.find('channel').get('id') == 'guide.news'


async def test_checker_timeout_redirect_and_success(monkeypatch):
    monkeypatch.setattr(checker_service, 'validate_public_url', AsyncMock())
    async def handler(request):
        if request.url.path == '/redirect':
            return httpx.Response(302, headers={'location': '/ok'})
        if request.url.path == '/timeout':
            await asyncio.sleep(.1)
        return httpx.Response(206, stream=httpx.ByteStream(b'#EXTM3U'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        stream = Stream(url='https://example.com/redirect')
        assert (await checker_service.probe(client, stream, 1))[0] == 'ONLINE'
        stream.url = 'https://example.com/timeout'
        assert (await checker_service.probe(client, stream, .01))[0] == 'OFFLINE'


async def test_checker_concurrency_and_persistence(db, settings, monkeypatch):
    await seed(db)
    running = 0
    peak = 0
    async def probe(*args):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(.01)
        running -= 1
        return 'ONLINE', 200, 12
    monkeypatch.setattr(checker_service, 'probe', probe)
    settings.check_concurrency = 2
    await checker_service.check(db, None, settings)
    assert peak == 2
    async with db.sessions() as session:
        assert all(s.last_checked and s.status == 'ONLINE' for s in (await session.scalars(select(Stream))).all())


def test_api_auth_edit_validation_exports(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get('/healthz').status_code == 200
        assert client.get('/api/status').status_code == 401
        assert client.get('/playlist.m3u').status_code == 401
        login(client, settings.admin_password.get_secret_value())
        assert client.get('/').status_code == 200
        assert client.get('/api/channels').json()['total'] == 0
        assert client.patch('/api/channels/1', json={'name': 'New'}).status_code == 403
        headers = {'X-Pilot-Request': '1'}
        assert client.patch('/api/channels/1', json={'name': None}, headers=headers).status_code == 422
        assert client.patch('/api/channels/1', json={'channel_number': 0}, headers=headers).status_code == 422
        assert client.patch('/api/channels/1', json={'name': 'New'}, headers=headers).status_code == 404
        token = settings.export_token.get_secret_value()
        assert client.get('/playlist.m3u', params={'token': token}).text.startswith('#EXTM3U')
        assert ET.fromstring(client.get('/epg.xml', params={'token': token}).content).tag == 'tv'


async def test_job_overlap_and_cleanup(db, settings, monkeypatch):
    from app.services import jobs as module
    wait = asyncio.Event()
    monkeypatch.setattr(module, 'check', AsyncMock(side_effect=lambda *args: None))
    async def slow(*args):
        await wait.wait()
    monkeypatch.setattr(module, 'check', slow)
    jobs = Jobs(db, None, settings)
    assert jobs.start('check')
    assert not jobs.start('sync')
    await asyncio.sleep(0)
    await jobs.close()
    assert not jobs.status['running']


async def test_private_destinations_blocked():
    from app.services.http_service import validate_public_url
    for url in ('http://127.0.0.1/', 'http://[::1]/', 'file:///etc/passwd'):
        with pytest.raises(ValueError):
            await validate_public_url(url)


async def test_epg_rejects_entities(settings, monkeypatch):
    from app.services import export_service
    monkeypatch.setattr(export_service, 'download', AsyncMock(return_value=b'<!DOCTYPE tv [<!ENTITY x "bad">]><tv>&x;</tv>'))
    settings.epg_urls = 'https://example.com/epg.xml'
    with pytest.raises(Exception):
        await GuideCache().get(None, settings)


def test_setup_wizard_creates_admin(tmp_path):
    unconfigured = Settings(_env_file=None, database_url=f'sqlite+aiosqlite:///{tmp_path}/setup.db',
                             scheduler_enabled=False, sync_on_start=False)
    with TestClient(create_app(unconfigured)) as client:
        assert client.get('/', follow_redirects=False).headers['location'] == '/setup'
        assert client.get('/setup').status_code == 200
        assert client.get('/login', follow_redirects=False).headers['location'] == '/setup'
        assert client.get('/playlist.m3u').status_code == 503
        assert client.get('/api/status').status_code == 503
        assert client.post('/setup', json={'username': 'admin', 'password': 'short', 'confirm': 'short'}).status_code == 422
        assert client.post('/setup', json={'username': 'admin', 'password': 'longenoughpassword', 'confirm': 'nope'}).status_code == 422
        assert client.post('/setup', json={'username': 'admin', 'password': 'longenoughpassword', 'confirm': 'longenoughpassword'}).status_code == 200

        # The wizard signs the new admin straight in; no separate login step needed.
        assert client.get('/').status_code == 200
        assert 'token=' in client.get('/').text
        assert client.post('/setup', json={'username': 'admin', 'password': 'longenoughpassword', 'confirm': 'longenoughpassword'}).status_code == 409
        assert client.get('/setup', follow_redirects=False).status_code == 307

        # Signing out drops the session; a real login page (not a browser Basic-auth popup) is how you get back in.
        assert client.post('/logout').status_code == 200
        assert client.get('/', follow_redirects=False).headers['location'] == '/login'
        assert client.get('/login').status_code == 200
        assert client.post('/login', json={'username': 'admin', 'password': 'wrong'}).status_code == 401
        login(client, 'longenoughpassword')
        assert client.get('/').status_code == 200


def test_password_rotation_invalidates_existing_sessions(tmp_path):
    unconfigured = Settings(_env_file=None, database_url=f'sqlite+aiosqlite:///{tmp_path}/rotate.db',
                             scheduler_enabled=False, sync_on_start=False)
    with TestClient(create_app(unconfigured)) as client:
        client.post('/setup', json={'username': 'admin', 'password': 'original-password-123', 'confirm': 'original-password-123'})
        assert client.get('/').status_code == 200
        old_session = client.cookies.get('session')

        db = client.app.state.db
        client.portal.call(lambda: db.update_json('admin_account', password='rotated-password-456'))

        # The cookie from before rotation must no longer authenticate.
        stale = TestClient(client.app)
        stale.cookies.set('session', old_session)
        assert stale.get('/', follow_redirects=False).headers['location'] == '/login'
        assert stale.get('/api/status').status_code == 401

        # Logging in again with the new password issues a fresh, working session.
        login(client, 'rotated-password-456')
        assert client.get('/').status_code == 200


async def test_jellyfin_save_push_reuse_key_and_auto_sync(settings, monkeypatch):
    import json as jsonlib
    from app.services import jellyfin_service

    def handler(request):
        if request.url.path == '/System/Info':
            return httpx.Response(200, json={})
        if request.url.path == '/LiveTv/TunerHosts':
            data = jsonlib.loads(request.read())
            return httpx.Response(200, json={**data, 'Id': data.get('Id') or 'tuner-1'})
        if request.url.path == '/LiveTv/ListingProviders':
            data = jsonlib.loads(request.read())
            return httpx.Response(200, json={**data, 'Id': data.get('Id') or 'listing-1'})
        if request.url.path == '/ScheduledTasks':
            return httpx.Response(200, json=[{'Name': 'Refresh Guide', 'Key': 'RefreshGuide', 'Id': 'task-1'}])
        return httpx.Response(204)

    with TestClient(create_app(settings)) as client:
        client.app.state.client._transport = httpx.MockTransport(handler)
        login(client, settings.admin_password.get_secret_value())
        headers = {'X-Pilot-Request': '1'}
        body = {'url': 'http://jellyfin:8096', 'api_key': 'key-1', 'base_url': 'http://iptv-gtw:8000', 'auto_sync': True}
        assert client.post('/api/jellyfin', json=body, headers=headers).status_code == 200
        assert client.get('/api/jellyfin').json()['api_key_set'] is True
        assert client.post('/api/jellyfin/push', headers=headers).status_code == 200
        status = client.get('/api/jellyfin').json()
        assert status['last_push'] and not status['last_error']

        # A blank api_key on save keeps the previously stored key rather than clearing it.
        assert client.post('/api/jellyfin', json={**body, 'api_key': ''}, headers=headers).status_code == 200

        # A successful background job auto-pushes to Jellyfin because auto_sync is enabled.
        pushed = []
        original = jellyfin_service.push
        async def spy(db, http_client, cfg):
            pushed.append(True)
            return await original(db, http_client, cfg)
        monkeypatch.setattr(jellyfin_service, 'push', spy)

        async def wait_job():
            await client.app.state.jobs.task

        assert client.post('/api/check', headers=headers).status_code == 202
        client.portal.call(wait_job)
        assert pushed

        # Disabling auto_sync stops the background hook from pushing again.
        pushed.clear()
        assert client.post('/api/jellyfin', json={**body, 'api_key': '', 'auto_sync': False}, headers=headers).status_code == 200
        assert client.post('/api/check', headers=headers).status_code == 202
        client.portal.call(wait_job)
        assert not pushed


def test_jellyfin_url_defaults_detected_and_editable(settings):
    with TestClient(create_app(settings)) as client:
        login(client, settings.admin_password.get_secret_value())
        status = client.get('/api/jellyfin').json()
        assert status['url'] is None and status['url_detected'] is False  # "jellyfin" doesn't resolve in tests
        assert status['base_url'].startswith('http://') and status['base_url'].endswith(':8000')
        assert status['base_url_detected'] is True

        headers = {'X-Pilot-Request': '1'}
        body = {'url': 'http://jellyfin:8096', 'api_key': 'key-1', 'base_url': 'http://my-custom-host:8000', 'auto_sync': False}
        with_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        client.app.state.client._transport = with_transport
        assert client.post('/api/jellyfin', json=body, headers=headers).status_code == 200
        status = client.get('/api/jellyfin').json()
        assert status['base_url'] == 'http://my-custom-host:8000' and status['base_url_detected'] is False


def test_multi_language_filter(settings):
    with TestClient(create_app(settings)) as client:
        async def seed_languages(db):
            async with db.sessions.begin() as session:
                session.add_all([Channel(channel_number=1, name='Eng', tvg_id='eng.1', language='eng'),
                                  Channel(channel_number=2, name='Hin', tvg_id='hin.1', language='hin'),
                                  Channel(channel_number=3, name='Spa', tvg_id='spa.1', language='spa')])
        client.portal.call(seed_languages, client.app.state.db)
        login(client, settings.admin_password.get_secret_value())
        assert client.get('/api/filters').json()['languages'] == ['eng', 'hin', 'spa']
        assert client.get('/api/channels', params={'language': 'eng'}).json()['total'] == 1
        data = client.get('/api/channels', params=[('language', 'eng'), ('language', 'hin')]).json()
        assert data['total'] == 2
        assert {c['name'] for c in data['items']} == {'Eng', 'Hin'}


def test_number_conflict_and_saved_edit(settings):
    with TestClient(create_app(settings)) as client:
        client.portal.call(seed, client.app.state.db)
        login(client, settings.admin_password.get_secret_value())
        headers = {'X-Pilot-Request': '1'}
        assert client.patch('/api/channels/1', json={'channel_number': 2}, headers=headers).status_code == 409
        assert client.patch('/api/channels/1', json={'name': 'Renamed', 'epg_id': 'new.id'}, headers=headers).status_code == 200
        data = client.get('/api/channels', params={'q': 'Renamed'}).json()
        assert data['total'] == 1
        assert data['items'][0]['epg_id'] == 'new.id'
        assert data['items'][0]['channel_number'] == 1
