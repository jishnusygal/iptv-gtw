import asyncio
import logging
from app.models import now
from app.services import jellyfin_service
from app.services.sync_service import sync
from app.services.checker_service import check

log = logging.getLogger(__name__)


class Jobs:
    def __init__(self, db, client, settings):
        self.db, self.client, self.settings = db, client, settings
        self.task = None
        self.status = {'running': False, 'name': None, 'error': None, 'result': None, 'progress': None}

    def start(self, name, **kwargs):
        if self.task and not self.task.done():
            return False
        self.status = {'running': True, 'name': name, 'error': None, 'result': None, 'progress': None, 'started_at': now().isoformat()}
        self.task = asyncio.create_task(self.run(name, kwargs))
        return True

    def _report_progress(self, done, total):
        self.status['progress'] = {'done': done, 'total': total}

    async def run(self, name, kwargs):
        try:
            if name == 'sync':
                self.status['result'] = await sync(self.db, self.client, self.settings, **kwargs)
                await check(self.db, self.client, self.settings, on_progress=self._report_progress)
            else:
                self.status['result'] = await check(self.db, self.client, self.settings, on_progress=self._report_progress)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not expose upstream URLs or credentials in logs/status.
            log.error('Background %s failed (%s)', name, type(exc).__name__)
            self.status['error'] = f'{type(exc).__name__}: job failed; retry or verify upstream configuration.'
        else:
            await jellyfin_service.push_if_enabled(self.db, self.client, self.settings)
        finally:
            self.status['running'] = False
            self.status['finished_at'] = now().isoformat()

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
