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

REWARD_INTERVAL: int = 300
"""Interval in seconds to reward watch time and points"""
REWARD_POINTS_PER_INTERVAL: int = 10
"""
Points per interval; should not be too small (e.g. below 10),
since reward multipliers are rounded per interval and very
small base values would reduce their effectiveness.
"""

REWARD_SUBSCRIBER_MULT: float = 2.0
"""points multiplier for subscribers"""

REWARD_CHATTED_ONCE: int = 100
"""points for first-time chatters"""
REWARD_CHATTED_FIXED: int = 0
"""fixed points for each chat message"""

REWARD_TIPPED_PER_TOKEN: float = 1.0
"""points per token"""
REWARD_TIPPED_FIXED: int = 0
"""fixed points for each tips"""

REWARD_RAIDED_PER_VIEWER: float = 0.0
"""points per viewer for raid/drop-in"""
REWARD_RAIDED_FIXED: int = 50
"""points for raid/drop-in"""

MAX_STATUS_RECOVERY_TIME: int = REWARD_INTERVAL
"""max channel/viewer online status recovery time in seconds"""


# ==============================================================================
# Interface

def adjust_viewer_points(
    viewer: Viewer,
    amount: int,
    reason: str,
) -> int:
    """
    Adjust points for a viewer.
    """
    # Exit if no points to adjust
    if amount == 0:
        return 0

    # Update viewer
    viewer.points += amount

    logger.info((
        "Adjusting points by %d for viewer #%d (user #%d, channel #%d); reason: %s"
    ), amount, viewer.id, viewer.user_id, viewer.channel_id, reason)

    return amount

def reward_viewer_watch_time(
    channel: Channel,
    viewer: Viewer,
) -> int:
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
        viewer.watch_time_rewarded_at,
    )
    time_end = min(
        now if viewer.is_present else viewer.left_at,
        now if channel.is_live else channel.offline_at,
    )

    # Return if no reward is due
    if time_end <= time_start:
        return 0

    # Round down to the nearest REWARD_INTERVAL
    intervals: int = int((time_end - time_start).total_seconds() / REWARD_INTERVAL)
    seconds: int = int(intervals * REWARD_INTERVAL)
    time_end = time_start + timedelta(seconds=seconds)

    # Return if no reward is due
    if seconds <= 0:
        return 0

    # Determine reward multiplier
    mult = 1.0

    if viewer.is_subscriber:
        mult += max(0, REWARD_SUBSCRIBER_MULT - 1)

    # Calculate final point reward
    # NOTE: Round per interval instead of after accumulation.
    #       Otherwise frequent calls would discard fractional rewards
    #       more often, giving slightly fewer points to more active viewers.
    points_per_interval = round(REWARD_POINTS_PER_INTERVAL * mult)
    points = max(0, intervals * points_per_interval)

    # Update viewer
    fresh_stream = channel.is_fresh_stream(viewer.watch_time_rewarded_at)

    viewer.watch_streak = 1 + (viewer.watch_streak if fresh_stream else 0)
    viewer.cur_watch_time = seconds + (viewer.cur_watch_time if fresh_stream else 0)

    viewer.total_watch_time += seconds
    viewer.watch_time_rewarded_at = time_end

    tmin, tsec = divmod(seconds, 60)
    points = adjust_viewer_points(viewer, points, (
        f"watched for {tmin:d}:{tsec:02d}"
    ))

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
        if is_live is not None and is_live != channel.is_live:
            if is_live:  # channel.is_live == False
                channel.set_live(now)
            else:  # channel.is_live == True
                channel.force_offline(max(channel.live_at, cutoff_at))

        result = await db.execute(
            select(Viewer)
            .filter_by(channel_id=channel.id, is_present=True),
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
            reward_viewer_watch_time(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

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
        .filter(Viewer.is_present.is_(True), Channel.is_live.is_(True)),
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
        reward_viewer_watch_time(viewer.channel, viewer)  # WARNING: Channel and viewer must be up-to-date

async def on_server_message(db: AsyncSession) -> None:
    await jstv_db.update_last_event_received_time(db)

async def on_viewer_interaction(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> None:
    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    now = utcnow()

    if viewer.first_seen_at is None:
        viewer.first_seen_at = now

    viewer.last_seen_at = now

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
        select(Viewer)
        .filter_by(channel_id=channel.id, is_present=True),
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
        reward_viewer_watch_time(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

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
    if not isinstance(channel, Channel):
        channel = await jstv_db.get_or_create_channel(db, channel)

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
    reward_viewer_watch_time(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

async def on_new_chat(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> int:
    if not isinstance(channel, Channel):
        channel = await jstv_db.get_or_create_channel(db, channel)

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    reason = "first time chatted" if viewer.last_chatted_at is None else "chatted"

    points = REWARD_CHATTED_ONCE if viewer.last_chatted_at is None else REWARD_CHATTED_FIXED
    points = max(0, points)

    # Update viewer
    viewer.cur_chatted = channel.accumulate_per_stream(
        viewer.cur_chatted, 1, viewer.last_chatted_at,
    )

    viewer.total_chatted += 1
    viewer.last_chatted_at = utcnow()

    points = adjust_viewer_points(viewer, points, reason)

    # Fail-safe for offline viewers
    if not viewer.is_present:
        channel_id = channel.channel_id if isinstance(channel, Channel) else channel
        username = user.username if isinstance(user, User) else user
        logger.info(
            "Fail-safe: Offline viewer %s chatted in channel %s - marking as online",
            username, channel_id,
        )

        # Force viewer online
        await on_enter_stream(db, channel, user, viewer)

    return points

async def on_followed(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> int:
    return 0

async def on_subscribed(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
) -> int:
    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    viewer.is_subscriber = True
    return 0

async def on_tipped(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
    amount: int,
) -> int:
    points = REWARD_TIPPED_FIXED + round(REWARD_TIPPED_PER_TOKEN * amount)
    points = max(0, points)

    if not isinstance(channel, Channel):
        channel = await jstv_db.get_or_create_channel(db, channel)

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    now = utcnow()

    # Update viewer
    viewer.cur_tipped = channel.accumulate_per_stream(
        viewer.cur_tipped, amount, viewer.last_tipped_at,
    )

    viewer.total_tipped += amount
    viewer.last_tipped_at = now

    points = adjust_viewer_points(viewer, points, f"tipped {amount} tokens")

    channel.total_tipped += amount
    channel.last_tipped_at = now

    # Update channel
    channel.cur_tipped = channel.accumulate_per_stream(
        channel.cur_tipped, amount, channel.last_tipped_at,
    )

    channel.total_tipped += amount
    channel.last_tipped_at = now

    return points

async def on_raided(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
    viewer_count: int,
) -> int:
    points = REWARD_RAIDED_FIXED + round(REWARD_RAIDED_PER_VIEWER * viewer_count)
    points = max(0, points)

    if not isinstance(channel, Channel):
        channel = await jstv_db.get_or_create_channel(db, channel)

    if not isinstance(viewer, Viewer):
        viewer = await jstv_db.get_or_create_viewer(db, channel, user)

    fresh_stream = channel.is_fresh_stream(viewer.last_raided_at)

    # Update viewer
    viewer.last_raided_at = utcnow()

    if fresh_stream:
        points = adjust_viewer_points(viewer, points, (
            f"raided with {viewer_count} viewers"
        ))

    return points
