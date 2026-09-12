import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.auth import admin, get_profile
from app.models import Channel, Profile
from app.routers.export import profile_endpoint
from app.schemas import ProfileWrite

router = APIRouter(prefix='/api', dependencies=[Depends(admin)])


def serialize(request, profile):
    return {'id': profile.id, 'name': profile.name, 'channel_ids': [c.id for c in profile.channels],
            'playlist_url': profile_endpoint(request, profile.id, '/playlist.m3u', profile.token),
            'epg_url': profile_endpoint(request, profile.id, '/epg.xml', profile.token)}


async def resolve_channels(session, channel_ids):
    found = (await session.scalars(select(Channel).where(Channel.id.in_(channel_ids)))).all()
    missing = set(channel_ids) - {c.id for c in found}
    if missing:
        raise HTTPException(422, f'Unknown channel ids: {sorted(missing)}')
    return found


@router.get('/profiles')
async def list_profiles(request: Request):
    async with request.app.state.db.sessions() as session:
        profiles = (await session.scalars(select(Profile).options(selectinload(Profile.channels)).order_by(Profile.name))).all()
        return [serialize(request, p) for p in profiles]


@router.post('/profiles', status_code=201)
async def create_profile(body: ProfileWrite, request: Request):
    try:
        async with request.app.state.db.sessions.begin() as session:
            profile = Profile(name=body.name, token=secrets.token_hex(16))
            profile.channels = await resolve_channels(session, body.channel_ids)
            session.add(profile)
            await session.flush()
            result = serialize(request, profile)
    except IntegrityError:
        raise HTTPException(409, 'A profile with this name already exists') from None
    return result


@router.patch('/profiles/{profile_id}')
async def update_profile(profile_id: int, body: ProfileWrite, request: Request):
    try:
        async with request.app.state.db.sessions.begin() as session:
            profile = await get_profile(session, profile_id, with_channels=True)
            profile.name = body.name
            profile.channels = await resolve_channels(session, body.channel_ids)
            result = serialize(request, profile)
    except IntegrityError:
        raise HTTPException(409, 'A profile with this name already exists') from None
    return result


@router.delete('/profiles/{profile_id}')
async def delete_profile(profile_id: int, request: Request):
    async with request.app.state.db.sessions.begin() as session:
        profile = await get_profile(session, profile_id)
        await session.delete(profile)
    return {'ok': True}
