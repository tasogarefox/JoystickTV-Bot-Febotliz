import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.datetime import utcmin, utcnow

from app.db.models import Channel, User, Viewer

from app.jstv import jstv_db, jstv_web, jstv_auth
from app.jstv.jstv_error import JSTVAuthError, JSTVWebError

logger = logging.getLogger(__name__)


# ==============================================================================
# Config

REWARD_INTERVAL = 300  # point reward interval in seconds
REWARD_POINTS_PER_MINUTE = 2.0  # points per minute

REWARD_FOLLOWER_MULT = 1.0  # points multiplier for followers
REWARD_SUBSCRIBER_MULT = 2.0  # points multiplier for subscribers

REWARD_CHATTED_ONCE = 100  # points for first-time chatters
REWARD_CHATTED_FIXED = 0  # fixed points for each chat message

REWARD_FOLLOWED_ONCE = 100  # points for first-time followers

REWARD_SUBSCRIBED_ONCE = 0  # points for first-time subscribers
REWARD_SUBSCRIBED_FIXED = 0  # fixed points for each subscribtion

REWARD_TIPPED_PER_TOKEN = 0.0  # points per token
REWARD_TIPPED_FIXED = 0  # fixed points for each tips

REWARD_RAIDED_PER_VIEWER = 0.0  # points per viewer for drop-in
REWARD_RAIDED_FIXED = 0  # points for drop-in

MAX_STATUS_RECOVERY_TIME = REWARD_INTERVAL  # max channel/viewer online status recovery time in seconds


# ==============================================================================
# Interface

async def reward_viewer(channel: Channel, viewer: Viewer) -> float:
    """
    Reward a viewer with points and watch time.

    - Only full REWARD_INTERVAL seconds earn points.
    - Fractional seconds are preserved in rewarded_at for precise future calculations.
    - Rewards only time that overlaps with the channel being live.

    WARNING: Make sure that viewer and channel presence/online status are up-to-date before calling.

    Args:
        channel: The Channel instance.
        viewer: The Viewer instance to reward.

    Returns:
        The number of points rewarded.
    """
    # Determine reward window
    # NOTE: Channel and viewer live/presence related timestamps are never None.
    now = utcnow()
    time_start = max(
        channel.live_at,
        viewer.joined_at,
        viewer.rewarded_at,
    )
    time_end = min(
        now if viewer.is_present else viewer.left_at,
        now if channel.is_live else channel.offline_at,
    )

    # Return if no reward is due
    if time_end <= time_start:
        return 0

    # Round down to the nearest REWARD_INTERVAL
    intervals = int((time_end - time_start).total_seconds() // REWARD_INTERVAL)
    time_delta = intervals * REWARD_INTERVAL
    time_end = time_start + timedelta(seconds=time_delta)

    # Return if no reward is due
    if time_delta <= 0:
        return 0

    # Calculate points (only complete intervals)
    # NOTE: `time_delta` is already a multiple of REWARD_INTERVAL
    points = time_delta / 60 * REWARD_POINTS_PER_MINUTE
    mult = 1.0

    # # TODO: Reenable when we track follower status
    # if viewer.followed_at:
    #     mult += REWARD_FOLLOWER_MULT

    # # TODO: Reenable when we track subscriber status
    # if viewer.subscribed_at:
    #     mult += REWARD_SUBSCRIBER_MULT

    # Calculate final point reward
    points = max(0, points * mult)

    # Update viewer
    viewer.rewarded_at = time_end
    viewer.watch_time += int(time_delta)
    viewer.points += points

    return points

async def on_connected(db: AsyncSession) -> set[Channel]:
    """
    Handle (re)connection.

    - Reconciles channel live/offline state with the database.
    - If downtime exceeds `MAX_STATUS_RECOVERY_TIME`, marks all present viewers
      offline at a safe cutoff time and rewards them up to that point.
    """
    logger.info("Updating live channels...")

    # Load all channels
    result = await db.execute(select(Channel))

    channels = set(result.scalars().unique().all())
    if not channels:
        return set()

    now = utcnow()
    last_event_at = await jstv_db.get_last_event_received_time(db) or utcmin

    gap_seconds = (now - last_event_at).total_seconds()
    within_recovery_window = gap_seconds <= MAX_STATUS_RECOVERY_TIME  # Are we within the recovery window?

    cutoff_at = min(now, last_event_at + timedelta(seconds=MAX_STATUS_RECOVERY_TIME))

    # Fetch stream settings for all channels in parallel
    async def get_live_status_helper(
        channel: Channel,
    ) -> tuple[Channel, jstv_web.StreamSettings | None]:
        try:
            access_token = await jstv_auth.get_access_token(channel.channel_id)
            settings = await jstv_web.fetch_stream_settings(access_token)
        except (JSTVAuthError, JSTVWebError):
            return channel, None

        return channel, settings

    tasks = [
        get_live_status_helper(channel)
        for channel in channels
    ]

    # Process results as they come
    for task in asyncio.as_completed(tasks):
        channel, settings = await task
        is_live = settings.live if settings is not None else None

        # Trusted reconnection: no forced recovery
        if within_recovery_window:
            if is_live:
                channel.set_live(now)
            else:
                channel.set_offline(now)
            continue

        # Untrusted state: force reconciliation
        if is_live != channel.is_live:
            if is_live:  # channel.is_live == False
                channel.set_live(now)
            else:  # channel.is_live == True
                channel.force_offline(max(channel.live_at, cutoff_at))

        result = await db.execute(
            select(Viewer).filter_by(channel_id=channel.id, is_present=True),
        )

        viewers = result.scalars().all()
        if not viewers:
            continue

        logger.info(
            "Fail-safe: Cannot reconcile channel %s viewer presence after %d minutes of disconnection - "
            "marking %d viewers as offline",
            channel.channel_id,
            gap_seconds // 60,
            len(viewers),
        )

        # Mark all present viewers as offline and reward them up until `cutoff_at`
        for viewer in viewers:
            viewer.force_offline(max(viewer.joined_at, cutoff_at))
            await reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

    return channels

async def on_disconnected(db: AsyncSession) -> None:
    """
    Handle loss of connection or shutdown.

    - Rewards all currently-present viewers **only if their channel is live**.
    - Does NOT mark viewers offline or modify channel state.
    - Viewer cleanup and offline inference are deferred to recovery on reconnect.
    """
    # Select viewers who are currently present and in a live channel
    result = await db.execute(
        select(Viewer)
        .join(Viewer.channel)
        .options(joinedload(Viewer.channel))
        .filter(Viewer.is_present == True, Channel.is_live == True),
    )

    viewers = result.scalars().all()
    if not viewers:
        return

    logger.info(
        "Fail-safe: Disconnected with %d viewers - rewarding viewers up until now",
        len(viewers),
    )

    for viewer in viewers:
        # NOTE: We rely on recovery to mark viewers as offline later, if needed
        await reward_viewer(viewer.channel, viewer)  # WARNING: Channel and viewer must be up-to-date

async def on_server_message(db: AsyncSession) -> None:
    await jstv_db.update_last_event_received_time(db)

async def on_stream_started(db: AsyncSession, channel: Channel | str) -> None:
    """
    Handle a channel transitioning to live.

    - Marks the channel as live in the database.
    """
    if not isinstance(channel, Channel):
        channel = await jstv_db.get_or_create_channel(db, channel)

    # Mark channel live
    channel.set_live()

async def on_stream_resuming(db: AsyncSession, channel: Channel | str) -> None:
    """
    Handle a channel resuming its stream after a short disconnect.

    - Marks the channel as live in the database.
    """
    if not isinstance(channel, Channel):
        channel = await jstv_db.get_or_create_channel(db, channel)

    # Mark channel live
    channel.set_live()

async def on_stream_ended(db: AsyncSession, channel: Channel | str):
    """
    Handle a channel transitioning to offline.

    - Marks the channel as offline in the database.
    - Rewards all currently-present viewers up to the end of the stream.

    Viewer presence cleanup is deferred to leave events or recovery logic.
    """
    if not isinstance(channel, Channel):
        channel = await jstv_db.get_or_create_channel(db, channel)

    # Mark channel offline; timestamps are handled by the model
    channel.set_offline()

    # Reward all viewers still marked as present
    result = await db.execute(
        select(Viewer).filter_by(channel_id=channel.id, is_present=True),
    )

    viewers = result.scalars().all()
    if not viewers:
        return

    logger.info(
        "Fail-safe: Stream %s ended with %d viewers - rewarding viewers up until now",
        channel.channel_id, len(viewers),
    )

    for viewer in viewers:
        # NOTE: We do NOT mark viewers offline here.
        #       Offline inference is handled by leave events or recovery.
        await reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

async def on_enter_stream(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> None:
    """
    Handle a viewer joining a channel.

    - Marks the viewer as present.
    - Does NOT handle rewards; rewarding occurs on leave, stream end or recovery.

    Notes:
    - This event may arrive while the channel is offline.
    """
    # channel_id = channel.channel_id if isinstance(channel, Channel) else channel
    # username = user.username if isinstance(user, User) else user

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    # Handle viewer joining
    viewer.join()

async def on_leave_stream(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> None:
    """
    Handle a viewer leaving a channel.

    - Marks the viewer as not present.
    - Rewards the viewer.

    Notes:
    - Viewers who joined while the channel was offline are NOT rewarded here.
      Their potential reward (if any) is handled by `on_stream_ended` or recovery.
    """
    if not isinstance(channel, Channel):
        channel = await jstv_db.get_or_create_channel(db, channel)

    # username = user.username if isinstance(user, User) else user

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    # Fail-safe for offline viewers
    if not viewer.is_present:
        logger.info(
            "Fail-safe: Viewer already left channel %s at %s - ignoring",
            channel.channel_id, viewer.left_at,
        )
        return

    # Handle viewer leaving
    viewer.leave()

    # Reward viewer
    await reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

async def on_new_chat(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> float:
    channel_id = channel.channel_id if isinstance(channel, Channel) else channel
    username = user.username if isinstance(user, User) else user

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    points = REWARD_CHATTED_ONCE if viewer.chatted_at is None else REWARD_CHATTED_FIXED
    points = max(0, points)

    if points > 0:
        logger.info((
            "User %s chatted in channel %s; rewarding %d points"
        ), username, channel_id, points)

    # Update viewer
    viewer.chatted_at = utcnow()
    viewer.points += points

    # Fail-safe for offline viewers
    if not viewer.is_present:
        logger.info(
            "Fail-safe: Offline viewer %s chatted in channel %s - marking as online",
            username, channel_id,
        )

        # Force viewer online
        viewer.join()

    return points

async def on_followed(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> float:
    channel_id = channel.channel_id if isinstance(channel, Channel) else channel
    username = user.username if isinstance(user, User) else user

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    points = 0
    points += REWARD_FOLLOWED_ONCE if viewer.followed_at is None else 0
    points = max(0, points)

    if points > 0:
        logger.info((
            "User %s followed channel %s; rewarding %d points"
        ), username, channel_id, points)

    # Update viewer
    viewer.points += points
    if viewer.followed_at is None:
        viewer.followed_at = utcnow()

    return points

async def on_subscribed(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> float:
    channel_id = channel.channel_id if isinstance(channel, Channel) else channel
    username = user.username if isinstance(user, User) else user

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    points = REWARD_SUBSCRIBED_FIXED
    points += REWARD_SUBSCRIBED_ONCE if viewer.subscribed_at is None else 0
    points = max(0, points)

    if points > 0:
        logger.info((
            "User %s subscribed to channel %s; rewarding %d points"
        ), username, channel_id, points)

    # Update viewer
    viewer.points += points
    if viewer.subscribed_at is None:
        viewer.subscribed_at = utcnow()

    return points

async def on_tipped(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
    amount: float,
) -> float:
    points = REWARD_TIPPED_FIXED
    points += REWARD_TIPPED_PER_TOKEN * amount
    points = max(0, points)

    if points <= 0:
        return 0

    channel_id = channel.channel_id if isinstance(channel, Channel) else channel
    username = user.username if isinstance(user, User) else user

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    logger.info((
        "User %s tipped %d tokens to channel %s; rewarding %d points"
    ), username, amount, channel_id, points)

    viewer.points += points
    return points

async def on_raided(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
    viewer_count: int,
) -> float:
    points = REWARD_RAIDED_FIXED
    points += REWARD_RAIDED_PER_VIEWER * viewer_count
    points = max(0, points)

    if points <= 0:
        return 0

    channel_id = channel.channel_id if isinstance(channel, Channel) else channel
    username = user.username if isinstance(user, User) else user

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    logger.info((
        "User %s raided channel %s with %d viewers; rewarding %d points"
    ), username, channel_id, viewer_count, points)

    viewer.points += points
    return points
