from typing import TypeVar, Any, cast
from datetime import datetime
import uuid

from sqlalchemy import (
    ForeignKey, Index, UniqueConstraint, CheckConstraint,
    String, Integer, Boolean, JSON,
    or_, literal,
)
from sqlalchemy.orm import Mapped, RelationshipProperty, mapped_column, validates
from sqlalchemy.ext.hybrid import hybrid_property

from app.settings import NSFW_ENABLED
from app.handlers import HandlerTags
from app.utils.datetime import utcnow
from app.utils.db import relationship

from .database import Base
from .types import IntEnum, AwareDateTime
from .enums import AccessLevel

NumberT = TypeVar("NumberT", int, float)


# ==============================================================================
# Config

MAX_SESSION_RECOVERY_TIME: int = 600
"""Maximum number of seconds to allow for channel/viewer session recovery."""


# ==============================================================================
# Constants

COMMAND_TAGS_DISABLED: frozenset[str] = frozenset(
    tag for tag in {
        HandlerTags.nsfw if not NSFW_ENABLED else None,
    } if tag
)
"""
Any `Command` whose `Command.definition.tags` contain any of these tag names
should be treated as disabled, regardless of `Command.disabled`.
"""


# ==============================================================================
# Connection State

class ConnectionState(Base):
    """
    Single-row table to track connection state.
    """
    __tablename__ = "connection_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)

    last_event_received_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)

# ==============================================================================
# User Models

class User(Base):
    """
    User data.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, onupdate=utcnow, nullable=False)

    channel: Mapped["Channel"] = relationship("Channel", uselist=False, back_populates="owner")
    viewers: Mapped[list["Viewer"]] = relationship("Viewer", uselist=True, back_populates="user")

    command_cooldowns: Mapped[list["ViewerCommandCooldown"]] = relationship("ViewerCommandCooldown", uselist=True, back_populates="user")


# ==============================================================================
# Channel Models

class Channel(Base):
    """
    Channel data.
    """
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), default=None, unique=True, index=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, onupdate=utcnow, nullable=False)

    cur_stream_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
    """Unique ID of current stream. DO NOT SET DIRECTLY"""

    prev_stream_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
    """Unique ID of previous stream. DO NOT SET DIRECTLY"""

    live_started_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    """Timestamp when the current live session began. DO NOT SET DIRECTLY"""

    last_offline_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    """Timestamp of last time the channel went offline. DO NOT SET DIRECTLY"""

    is_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """True if the channel is currently live. DO NOT SET DIRECTLY"""

    last_tipped_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    """Last time someone tipped the channel."""

    total_tipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total tipped amount for the channel (only while bot was running)."""

    cur_tipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Tipped amount for the current stream."""

    owner: Mapped[User | None] = relationship("User", uselist=False, back_populates="channel")
    viewers: Mapped[list["Viewer"]] = relationship("Viewer", uselist=True, back_populates="channel")
    access_token: Mapped["ChannelAccessToken"]  = relationship("ChannelAccessToken", uselist=False, back_populates="channel", cascade="all, delete-orphan")
    commands: Mapped[list["Command"]] = relationship("Command", uselist=True, back_populates="channel")

    def set_live(self, timestamp: datetime | None = None) -> None:
        """Mark the channel as live and start a new stream if not in recovery."""
        if self.is_live:
            return

        timestamp = timestamp or utcnow()

        # Only start a new stream if we're outside the recovery window
        if not self.is_within_recovery_window(timestamp):
            self.live_started_at = timestamp

            # Update stream IDs
            self.prev_stream_id = self.cur_stream_id
            self.cur_stream_id = str(uuid.uuid4())

        self.is_live = True

    def set_offline(self, timestamp: datetime | None = None) -> None:
        """Mark the channel as offline."""
        if not self.is_live:
            return

        self.is_live = False
        self.last_offline_at = timestamp or utcnow()

    def force_offline(self, timestamp: datetime | None = None) -> None:
        """Force the channel into offline state."""
        self.set_offline(timestamp)

    def is_within_recovery_window(self, timestamp: datetime | None = None) -> bool:
        """Returns True if we are within the session recovery window."""
        delta = (timestamp or utcnow()) - self.last_offline_at
        return delta.total_seconds() < MAX_SESSION_RECOVERY_TIME

    def is_fresh_stream(self, last_at: datetime | None) -> bool:
        """
        Return True if an event has not happened since
        the start of the current live stream.

        NOTE: Does not check if the stream is live.
        """
        return not last_at or last_at < self.live_started_at

    def accumulate_per_stream(
        self,
        prev: NumberT,
        amount: NumberT,
        last_at: datetime | None,
    ) -> NumberT:
        """
        Accumulate per-stream values.

        Adds `amount` to `prev` for the current stream,
        resetting if it's the first event during this stream.
        Returns `prev` unchanged if the channel is not live.
        """
        # Don't accumulate if not live
        if not self.is_live:
            return prev

        # Reset if first time in current live stream
        if self.is_fresh_stream(last_at):
            return amount

        return prev + amount

    def accumulate_per_stream_streak(
        self,
        prev: NumberT,
        amount: NumberT,
        last_stream_id: str | None,
    ) -> NumberT:
        """
        Accumulate per-stream-streak values; resets if streak broken.

        Adds `amount` to `prev` for the current stream streak,
        resetting if the streak has broken.
        Returns `prev` unchanged if already accumulated this
        stream or if never streamed.
        """
        # Return unchanged if no stream to accumulate
        if self.cur_stream_id is None:
            return prev

        # Return unchanged if already counted for this stream
        if last_stream_id == self.cur_stream_id:
            return prev

        # Reset if the streak has broken
        if self.prev_stream_id and last_stream_id != self.prev_stream_id:
            return amount

        return prev + amount

class ChannelAccessToken(Base):
    """
    Channel JWT access token.
    """
    __tablename__ = "access_tokens"

    def __init__(
        self,
        id: int,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        refreshed_at: datetime | None = None,
        *args,
        **kwargs,
    ):
        from app.security import encrypt
        super().__init__(
            id=id,
            access_token_encrypted=encrypt(access_token),
            refresh_token_encrypted=encrypt(refresh_token),
            expires_at=expires_at,
            refreshed_at=refreshed_at or utcnow(),
            *args,
            **kwargs,
        )

    id: Mapped[int] = mapped_column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True, index=True, nullable=False)

    access_token_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(AwareDateTime, nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)

    channel: Mapped[Channel] = relationship("Channel", uselist=False, back_populates="access_token")

    # Accessors to hide encryption/decryption logic
    def set_tokens(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        refreshed_at: datetime | None = None,
    ) -> None:
        from app.security import encrypt
        self.access_token_encrypted = encrypt(access_token)
        self.refresh_token_encrypted = encrypt(refresh_token)
        self.expires_at = expires_at
        self.refreshed_at = refreshed_at or utcnow()

    def get_access_token(self) -> str:
        from app.security import decrypt
        return decrypt(self.access_token_encrypted)

    def get_refresh_token(self) -> str:
        from app.security import decrypt
        return decrypt(self.refresh_token_encrypted)


# ==============================================================================
# Viewer Models

class Viewer(Base):
    """
    Viewer data.

    NOTE: State and timestamps can currently only be tracked while
          the program is running, which means that it may be out of sync.
          For that reason, many timestamps and the follow state are
          not included in the database.
    """
    __tablename__ = "viewers"
    __table_args__ = (
        Index("ix_viewers_user_id_channel_id", "user_id", "channel_id"),
        UniqueConstraint("user_id", "channel_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, onupdate=utcnow, nullable=False)

    presence_started_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    """Timestamp when the current continuous presence began. DO NOT SET DIRECTLY"""

    last_left_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    """Timestamp when the last leave event was received. DO NOT SET DIRECTLY"""

    active_session_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Number of currently active sessions. Used for multiple device/session tracking. DO NOT SET DIRECTLY"""

    watch_time_rewarded_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    """Timestamp when the viewer was last rewarded for watch time."""

    first_seen_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    """First time of interaction on the channel (join, chat, tip, etc)."""

    last_seen_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    """Last time of interaction on the channel (join, chat, tip, etc)."""

    last_chatted_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    """Last time the viewer chatted in the channel."""

    last_tipped_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    """Last time the viewer tipped the channel."""

    last_raided_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    """Last time the viewer raided the channel."""

    is_streamer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """True if the viewer is the channel's streamer."""

    is_moderator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """True if the viewer is a moderator of the channel."""

    is_subscriber: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """True if the viewer is a subscriber of the channel."""

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """
    True if the viewer is verified.
    Verified means they spent money on the site or are a content creator.
    NOTE: Technically a user attribute, but included here for convenience.
    """

    is_content_creator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """
    True if the viewer is a content creator. May or may not be the channel's streamer.
    NOTE: Technically a user attribute, but included here for convenience.
    """

    total_watch_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total watch time in seconds."""

    cur_watch_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Watch time for the current stream."""

    total_streams_watched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total number of streams the viewer has watched."""

    cur_watch_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """How many streams the viewer has watched in a row."""

    last_streak_stream_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
    """The ID of the last stream the viewer watched in a row."""

    total_chatted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total number of messages sent in the channel (only while bot was running)."""

    cur_chatted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Number of messages sent during the current stream."""

    total_tipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total tipped amount for the channel (only while bot was running)."""

    cur_tipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Tipped amount for the current stream."""

    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Channel-points the viewer currently has."""

    @hybrid_property
    def access_level(self) -> AccessLevel: # pyright: ignore[reportRedeclaration]
        """Access level of the viewer."""
        if self.is_streamer:
            return AccessLevel.streamer
        if self.is_moderator:
            return AccessLevel.moderator
        if self.is_subscriber:
            return AccessLevel.subscriber
        if self.is_verified:
            return AccessLevel.verified
        return AccessLevel.viewer

    @hybrid_property
    def is_present(self) -> bool: # pyright: ignore[reportRedeclaration]
        """Returns True if the viewer is currently present in the channel."""
        return self.active_session_count > 0

    @is_present.expression # pyright: ignore[reportArgumentType]
    def is_present(cls):
        """SQL expression for querying is_present."""
        return cls.active_session_count > 0

    def join(self, timestamp: datetime | None = None):
        """Mark viewer as present on a new device/session; starts presence on first session."""
        if self.active_session_count == 0:
            timestamp = timestamp or utcnow()
            if not self.is_within_recovery_window(timestamp):
                self.presence_started_at = timestamp

        self.active_session_count += 1

    def leave(self, timestamp: datetime | None = None):
        """Mark one device/session as left; record last leave event."""
        if self.active_session_count > 0:
            self.active_session_count -= 1

        self.last_left_at = timestamp or utcnow()

    def force_offline(self, timestamp: datetime | None = None):
        """Force viewer fully offline, clearing any sessions."""
        self.active_session_count = 0
        self.last_left_at = timestamp or utcnow()

    def is_within_recovery_window(self, timestamp: datetime | None = None) -> bool:
        """Returns True if we are within the session recovery window."""
        delta = (timestamp or utcnow()) - self.last_left_at
        return delta.total_seconds() < MAX_SESSION_RECOVERY_TIME

    user: Mapped[User] = relationship("User", uselist=False, back_populates="viewers")
    channel: Mapped[Channel] = relationship("Channel", uselist=False, back_populates="viewers")


# ==============================================================================
# Command Models

class CommandDefinition(Base):
    """
    Global command definition (mirrored from plugins).
    """
    __tablename__ = "command_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    tags: Mapped[list["CommandTag"]] = relationship("CommandTag", uselist=True, lazy="selectin", back_populates="definition", cascade="all, delete-orphan")
    commands: Mapped[list["Command"]] = relationship("Command", uselist=True, back_populates="definition", cascade="all, delete-orphan")

    @hybrid_property  # pyright: ignore[reportRedeclaration]
    def disabled(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return any(x.name in COMMAND_TAGS_DISABLED for x in self.tags)

    @disabled.expression
    def disabled(cls):
        if not COMMAND_TAGS_DISABLED:
            return literal(False)

        tags = cast(RelationshipProperty, cls.tags)  # typing fix

        return or_(*[
            tags.any(CommandTag.name == tag)
            for tag in COMMAND_TAGS_DISABLED
        ])

class CommandTag(Base):
    """
    Per-command tag.
    """
    __tablename__ = "command_tags"
    __table_args__ = (
        Index("ix_command_tags_definition_id_name", "definition_id", "name"),
        UniqueConstraint("definition_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    definition_id: Mapped[int] = mapped_column(Integer, ForeignKey("command_definitions.id", ondelete="CASCADE"), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    definition: Mapped[CommandDefinition] = relationship("CommandDefinition", uselist=False, back_populates="tags")

    @validates("name")
    def _normalize_name(self, key: str, value: str) -> str:
        return value.casefold()

class Command(Base):
    """
    Per-channel command setting overrides.
    """
    __tablename__ = "commands"
    __table_args__ = (
        Index("ix_commands_definition_id_channel_id", "definition_id", "channel_id"),
        UniqueConstraint("definition_id", "channel_id"),

        CheckConstraint("base_cost >= 0"),
        CheckConstraint("channel_cooldown >= 0"),
        CheckConstraint("viewer_cooldown >= 0"),
        CheckConstraint("channel_limit >= 0"),
        CheckConstraint("viewer_limit >= 0"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    definition_id: Mapped[int] = mapped_column(Integer, ForeignKey("command_definitions.id", ondelete="CASCADE"), index=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, onupdate=utcnow, nullable=False)

    default_alias_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("command_aliases.id", ondelete="SET NULL"), nullable=True)

    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    min_access_level: Mapped[AccessLevel] = mapped_column(IntEnum(AccessLevel), default=AccessLevel.viewer, nullable=False)

    base_cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    channel_cooldown: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    channel_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    viewer_cooldown: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    viewer_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    memory: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    definition: Mapped[CommandDefinition] = relationship("CommandDefinition", uselist=False, back_populates="commands")
    channel: Mapped[Channel] = relationship("Channel", uselist=False, back_populates="commands")
    default_alias: Mapped["CommandAlias | None"]  = relationship("CommandAlias", uselist=False, post_update=True, lazy="joined", foreign_keys=[default_alias_id])
    aliases: Mapped[list["CommandAlias"]] = relationship("CommandAlias", uselist=True, back_populates="command", foreign_keys="CommandAlias.command_id", cascade="all, delete-orphan")
    channel_cooldowns: Mapped[list["ChannelCommandCooldown"]] = relationship("ChannelCommandCooldown", uselist=True, back_populates="command", cascade="all, delete-orphan")
    viewer_cooldowns: Mapped[list["ViewerCommandCooldown"]] = relationship("ViewerCommandCooldown", uselist=True, back_populates="command", cascade="all, delete-orphan")

    @hybrid_property
    def aliases_default_first(self) -> list["CommandAlias"]:
        return sorted(self.aliases, key=lambda x: x.id != self.default_alias_id)

class CommandAlias(Base):
    """
    Channel Command Alias.
    """
    __tablename__ = "command_aliases"
    __table_args__ = (
        Index("ix_command_aliases_command_id_name", "command_id", "name"),
        UniqueConstraint("command_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    command_id: Mapped[int] = mapped_column(Integer, ForeignKey("commands.id", ondelete="CASCADE"), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    command: Mapped[Command] = relationship("Command", uselist=False, back_populates="aliases", foreign_keys=[command_id])

    @validates("name")
    def _normalize_name(self, key: str, value: str) -> str:
        return value.casefold()

class ChannelCommandCooldown(Base):
    """
    Channel command cooldown.
    """
    __tablename__ = "channel_command_cooldowns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    command_id: Mapped[int] = mapped_column(Integer, ForeignKey("commands.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)

    last_used_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cur_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    command: Mapped[Command] = relationship("Command", uselist=False, back_populates="channel_cooldowns")

class ViewerCommandCooldown(Base):
    """
    Viewer command cooldown.
    """
    __tablename__ = "viewer_command_cooldowns"
    __table_args__ = (
        Index("ix_viewer_command_cooldowns_command_id_user_id", "command_id", "user_id"),
        UniqueConstraint("command_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    command_id: Mapped[int] = mapped_column(Integer, ForeignKey("commands.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    last_used_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cur_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_exec_alias: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_exec_argument: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_exec_cost: Mapped[int] = mapped_column(default=0, nullable=False)

    command: Mapped[Command] = relationship("Command", uselist=False, back_populates="viewer_cooldowns")
    user: Mapped[User] = relationship("User", uselist=False, back_populates="command_cooldowns")
