from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Table, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Channel(Base):
    __tablename__ = 'channels'
    __table_args__ = (CheckConstraint('channel_number > 0'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_number: Mapped[int] = mapped_column(unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    tvg_id: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    tvg_name: Mapped[str | None] = mapped_column(String(300))
    epg_id: Mapped[str | None] = mapped_column(String(300))
    logo_url: Mapped[str | None] = mapped_column(String(2000))
    group_title: Mapped[str] = mapped_column(default='General')
    country: Mapped[str | None]
    language: Mapped[str | None]
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    streams: Mapped[list['Stream']] = relationship(cascade='all, delete-orphan', passive_deletes=True)


class Stream(Base):
    __tablename__ = 'streams'
    __table_args__ = (UniqueConstraint('channel_id', 'url'), CheckConstraint("status IN ('ONLINE','OFFLINE','UNTESTED')"))
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey('channels.id', ondelete='CASCADE'), index=True)
    url: Mapped[str]
    resolution: Mapped[str | None]
    referrer: Mapped[str | None]
    user_agent: Mapped[str | None]
    status: Mapped[str] = mapped_column(default='UNTESTED', index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class State(Base):
    __tablename__ = 'state'
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]


profile_channels = Table(
    'profile_channels', Base.metadata,
    Column('profile_id', ForeignKey('profiles.id', ondelete='CASCADE'), primary_key=True),
    Column('channel_id', ForeignKey('channels.id', ondelete='CASCADE'), primary_key=True, index=True),
)


class Profile(Base):
    __tablename__ = 'profiles'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    channels: Mapped[list['Channel']] = relationship(secondary=profile_channels)
