from dataclasses import dataclass, field, InitVar
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.datetime import utcnow

from app.db.models import ConnectionState, User, Channel, Viewer


# ==============================================================================
# Context classes

@dataclass(slots=True)
class BoundViewer:
    db: AsyncSession

    init_channel: InitVar[Channel | str]
    init_user: InitVar[User | str]

    viewer: Viewer | None = None

    channel: Channel | None = field(init=False, default=None)
    channel_id: str = field(init=False)

    user: User | None = field(init=False, default=None)
    username: str = field(init=False)

    def __post_init__(
        self,
        init_channel: Channel | str,
        init_user: User | str,
    ):
        if isinstance(init_channel, Channel):
            self.channel_id = init_channel.channel_id
            self.channel = init_channel
        else:
            self.channel_id = init_channel

        if isinstance(init_user, User):
            self.username = init_user.username
            self.user = init_user
        else:
            self.username = init_user

    async def lazy_channel(self) -> Channel:
        if self.channel is not None:
            return self.channel

        self.channel = await get_or_create_channel(self.db, self.channel_id)
        return self.channel

    async def lazy_user(self) -> User:
        if self.user is not None:
            return self.user

        self.user = await get_or_create_user(self.db, self.username)
        return self.user

    async def lazy_viewer(self) -> Viewer:
        if self.viewer is not None:
            return self.viewer

        channel = await self.lazy_channel()
        user = await self.lazy_user()

        self.viewer = await get_or_create_viewer(self.db, channel, user)
        return self.viewer


# ==============================================================================
# Functions

async def get_last_event_received_time(db: AsyncSession) -> datetime | None:
    state = await db.get(ConnectionState, 1)
    return state.last_event_received_at if state is not None else None

async def update_last_event_received_time(
    db: AsyncSession,
    time: datetime | None = None,
) -> None:
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

async def get_channel(
    db: AsyncSession,
    channel_id: str,
) -> Channel | None:
    result = await db.execute(select(Channel).filter_by(channel_id=channel_id))
    return result.scalar_one_or_none()

async def get_or_create_channel(
    db: AsyncSession,
    channel_id: str,
) -> Channel:
    channel = await get_channel(db, channel_id)
    if channel is None:
        channel = Channel(channel_id=channel_id)
        db.add(channel)
        await db.flush()  # ensure ID is available

    return channel

async def get_user(
    db: AsyncSession,
    username: str,
) -> User | None:
    result = await db.execute(select(User).filter_by(username=username))
    return result.scalar_one_or_none()

async def get_or_create_user(
    db: AsyncSession,
    username: str,
) -> User:
    user = await get_user(db, username)
    if user is None:
        user = User(username=username)
        db.add(user)
        await db.flush()  # ensure ID is available

    return user

async def get_viewer(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
) -> Viewer | None:
    if not isinstance(channel, Channel):
        channel = await get_channel(db, channel)
    if channel is None:
        return None

    if not isinstance(user, User):
        user = await get_user(db, user)
    if user is None:
        return None

    result = await db.execute(select(Viewer).filter_by(user_id=user.id, channel_id=channel.id))
    return result.scalar_one_or_none()

async def get_or_create_viewer(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
) -> Viewer:
    if not isinstance(channel, Channel):
        channel = await get_or_create_channel(db, channel)

    if not isinstance(user, User):
        user = await get_or_create_user(db, user)

    # Get or create viewer for this channel and user combination
    viewer = await get_viewer(db, channel, user)
    if viewer is None:
        viewer = Viewer(user_id=user.id, channel_id=channel.id)
        db.add(viewer)
        await db.flush()  # ensure ID is available

    return viewer
