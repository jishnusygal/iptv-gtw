import json
from pathlib import Path
from sqlalchemy import event
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
        async with self.sessions.begin() as session:
            row = await session.get(State, key)
            data = json.loads(row.value) if row else {}
            data.update(changes)
            await session.merge(State(key=key, value=json.dumps(data)))
        return data
