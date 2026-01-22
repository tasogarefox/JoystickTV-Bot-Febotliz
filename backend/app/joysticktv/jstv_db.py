from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.datetime import utcnow

from app.db.models import ConnectionState, User, Channel, Viewer


# ==============================================================================
# Functions

async def get_last_event_received_time(db: AsyncSession) -> datetime | None:
    state = await db.get(ConnectionState, 1)
    return state.last_event_received_at if state is not None else None

async def update_last_event_received_time(db: AsyncSession, time: Optional[datetime] = None) -> None:
    if time is None:
        time = utcnow()

    state = await db.get(ConnectionState, 1)
    if state is None:
        state = ConnectionState(id=1)
        db.add(state)

    if state.last_event_received_at is not None:
        if time - state.last_event_received_at < timedelta(seconds=1):
            return

    state.last_event_received_at = time

async def get_or_create_channel(db: AsyncSession, channel_id: str) -> Channel:
    result = await db.execute(select(Channel).filter_by(channel_id=channel_id))

    channel = result.scalar_one_or_none()
    if channel is None:
        channel = Channel(channel_id=channel_id)
        db.add(channel)
        await db.flush()  # ensure ID is available

    return channel

async def get_or_create_user(db: AsyncSession, username: str) -> User:
    result = await db.execute(select(User).filter_by(username=username))

    user = result.scalar_one_or_none()
    if user is None:
        user = User(username=username)
        db.add(user)
        await db.flush()  # ensure ID is available

    return user

async def get_or_create_viewer(db: AsyncSession, channel: Channel | str, user: User | str) -> Viewer:
    # Get or create channel and user
    channel = channel if isinstance(channel, Channel) else await get_or_create_channel(db, channel)
    user = user if isinstance(user, User) else await get_or_create_user(db, user)

    # Get or create viewer for this user-channel
    result = await db.execute(select(Viewer).filter_by(user_id=user.id, channel_id=channel.id))

    viewer = result.scalar_one_or_none()
    if viewer is None:
        viewer = Viewer(user_id=user.id, channel_id=channel.id)
        db.add(viewer)
        await db.flush()  # ensure ID is available

    return viewer
