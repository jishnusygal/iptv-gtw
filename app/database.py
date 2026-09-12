import json
from pathlib import Path
from sqlalchemy import event, func
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.models import Base, State


class Database:
    def __init__(self, url):
        self.engine = create_async_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        @event.listens_for(self.engine.sync_engine, 'connect')
        def pragmas(connection, _):
            cursor = connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA busy_timeout=10000')
            cursor.close()

    async def initialize(self):
        path = self.engine.url.database
        if path and path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def read_json(self, key):
        # Small, together-read/written config blobs (admin account, Jellyfin integration)
        # live one-per-key as JSON in the generic State table rather than as scattered rows.
        async with self.sessions() as session:
            row = await session.get(State, key)
        return json.loads(row.value) if row else {}

    async def update_json(self, key, **changes):
        # A single atomic INSERT ... ON CONFLICT DO UPDATE (with SQLite's json_patch
        # doing the merge) instead of read-then-write, so two requests racing to
        # initialize the same key for the first time (e.g. the session secret, right
        # after startup) can't both decide "no row yet" and collide on the unique key.
        patch = json.dumps(changes)
        stmt = sqlite_upsert(State).values(key=key, value=patch)
        stmt = stmt.on_conflict_do_update(index_elements=[State.key], set_={'value': func.json_patch(State.value, stmt.excluded.value)})
        async with self.sessions.begin() as session:
            await session.execute(stmt)
            row = await session.get(State, key)
        return json.loads(row.value)
