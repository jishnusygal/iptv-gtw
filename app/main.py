from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from app.config import Settings
from app.database import Database
from app.models import Channel
from app.routers import api, export, jellyfin, login, setup, web
from app.services.export_service import GuideCache
from app.services.jobs import Jobs


def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings()
        app.state.settings = config
        db = Database(config.database_url)
        app.state.db = db
        await db.initialize()
        async with httpx.AsyncClient(timeout=30, trust_env=False, limits=httpx.Limits(max_connections=30)) as client:
            app.state.client = client
            app.state.guides = GuideCache()
            jobs = Jobs(db, client, config)
            app.state.jobs = jobs
            scheduler = AsyncIOScheduler(timezone='UTC')
            async def scheduled(name):
                jobs.start(name)

            if config.scheduler_enabled:
                scheduler.add_job(scheduled, 'cron', hour=3, minute=0, args=['sync'], max_instances=1, coalesce=True)
                scheduler.add_job(scheduled, 'interval', hours=config.health_interval_hours, args=['check'], max_instances=1, coalesce=True)
                scheduler.start()
            async with db.sessions() as session:
                empty = not await session.scalar(select(func.count(Channel.id)))
            if empty and config.sync_on_start:
                jobs.start('sync')
            try:
                yield
            finally:
                if scheduler.running:
                    scheduler.shutdown(wait=False)
                await jobs.close()
                await db.engine.dispose()

    app = FastAPI(title='IPTV-Org Pilot', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(api.router)
    app.include_router(export.router)
    app.include_router(jellyfin.router)
    app.include_router(login.router)
    app.include_router(setup.router)
    app.include_router(web.router)
    app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')

    @app.get('/healthz')
    async def health():
        async with app.state.db.sessions() as session:
            await session.execute(text('SELECT 1'))
        return {'status': 'ok'}

    return app


app = create_app()
