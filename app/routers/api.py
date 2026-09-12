from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.auth import admin
from app.models import Channel, State, Stream
from app.schemas import ChannelPatch, SyncRequest

router = APIRouter(prefix='/api', dependencies=[Depends(admin)])


@router.get('/status')
async def status(request: Request):
    async with request.app.state.db.sessions() as session:
        total = await session.scalar(select(func.count(Channel.id)))
        counts = dict((await session.execute(select(Stream.status, func.count(Stream.id)).group_by(Stream.status))).all())
        last = await session.get(State, 'last_sync')
    return {'total_channels': total, 'active_streams': counts.get('ONLINE', 0), 'dead_streams': counts.get('OFFLINE', 0),
            'untested_streams': counts.get('UNTESTED', 0), 'last_sync': last.value if last else None,
            'job': request.app.state.jobs.status, 'epg_configured': bool(request.app.state.settings.epg_urls)}


async def distinct_values(session, column):
    return (await session.scalars(select(column).distinct().where(column.is_not(None), column != '').order_by(column))).all()


@router.get('/filters')
async def filters(request: Request):
    async with request.app.state.db.sessions() as session:
        countries = await distinct_values(session, Channel.country)
        languages = await distinct_values(session, Channel.language)
        groups = await distinct_values(session, Channel.group_title)
    return {'countries': countries, 'languages': languages, 'groups': groups}


@router.get('/channels')
async def channels(request: Request, q: str = Query('', max_length=300), status: str | None = Query(None, pattern='^(ONLINE|OFFLINE|UNTESTED)$'),
                   country: str | None = Query(None, max_length=100), language: list[str] = Query(default=[]),
                   group_title: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100)):
    statement = select(Channel)
    if q:
        statement = statement.where(or_(Channel.name.contains(q, autoescape=True), Channel.tvg_id.contains(q, autoescape=True)))
    if status:
        statement = statement.where(Channel.streams.any(Stream.status == status))
    if country:
        statement = statement.where(Channel.country == country)
    if language:
        statement = statement.where(Channel.language.in_(language))
    if group_title:
        statement = statement.where(Channel.group_title == group_title)
    async with request.app.state.db.sessions() as session:
        total = await session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (await session.scalars(statement.options(selectinload(Channel.streams)).order_by(Channel.channel_number)
                                     .offset((page - 1) * limit).limit(limit))).all()
        items = []
        for c in rows:
            item = {field: getattr(c, field) for field in ('id', 'channel_number', 'name', 'tvg_id', 'tvg_name', 'epg_id', 'logo_url', 'group_title', 'country', 'language', 'is_enabled')}
            item['streams'] = [{field: getattr(s, field) for field in ('id', 'resolution', 'status', 'http_status', 'latency_ms', 'last_checked')} for s in c.streams]
            items.append(item)
    return {'items': items, 'total': total, 'page': page, 'limit': limit}


@router.patch('/channels/{channel_id}')
async def edit(channel_id: int, body: ChannelPatch, request: Request):
    try:
        async with request.app.state.db.sessions.begin() as session:
            channel = await session.get(Channel, channel_id)
            if channel is None:
                raise HTTPException(404, 'Channel not found')
            for key, value in body.model_dump(exclude_unset=True).items():
                setattr(channel, key, value)
    except IntegrityError:
        raise HTTPException(409, 'Channel number is already in use') from None
    return {'ok': True}


@router.post('/sync', status_code=202)
async def trigger_sync(request: Request, body: SyncRequest = SyncRequest()):
    if not request.app.state.jobs.start('sync', **body.model_dump()):
        raise HTTPException(409, 'A background job is already running')
    return {'accepted': True}


@router.post('/check', status_code=202)
async def trigger_check(request: Request):
    if not request.app.state.jobs.start('check'):
        raise HTTPException(409, 'A background job is already running')
    return {'accepted': True}
