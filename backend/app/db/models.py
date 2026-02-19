from datetime import datetime

from sqlalchemy import (
    ForeignKey, Index, UniqueConstraint, CheckConstraint,
    String, Integer, Float, Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.hybrid import hybrid_property

from app.utils.datetime import utcnow
from app.utils.db import relationship

from .database import Base
from .types import Enum, AwareDateTime
from .enums import CommandAccessLevel


# ==============================================================================
# Connection State

class ConnectionState(Base):
    """
    Single-row table to track connection state.
    """
    __tablename__ = "connection_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

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

    live_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    offline_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)

    owner: Mapped[User | None] = relationship("User", uselist=False, back_populates="channel")
    viewers: Mapped[list["Viewer"]] = relationship("Viewer", uselist=True, back_populates="channel")
    access_token: Mapped["ChannelAccessToken"]  = relationship("ChannelAccessToken", uselist=False, back_populates="channel")
    commands: Mapped[list["Command"]] = relationship("Command", uselist=True, back_populates="channel")

    @hybrid_property
    def is_live(self) -> bool: # pyright: ignore[reportRedeclaration]
        return self.live_at > self.offline_at

    @is_live.expression # pyright: ignore[reportArgumentType]
    def is_live(cls): # pyright: ignore[reportRedeclaration]
        return cls.live_at > cls.offline_at

    def set_live(self, timestamp: datetime | None = None) -> None:
        """Mark the channel as live."""
        if self.is_live:
            return

        self.live_at = timestamp or utcnow()

    def set_offline(self, timestamp: datetime | None = None) -> None:
        """Mark the channel as offline."""
        if not self.is_live:
            return

        self.offline_at = timestamp or utcnow()

    def force_offline(self, timestamp: datetime | None = None) -> None:
        """Force the channel into offline state."""
        self.offline_at = timestamp or utcnow()
        self.live_at = min(self.live_at, self.offline_at)

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
    """
    __tablename__ = "viewers"
    __table_args__ = (
        Index("ix_viewers_user_id_channel_id", "user_id", "channel_id"),
        UniqueConstraint("user_id", "channel_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), index=True, nullable=False)

    joined_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    left_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    rewarded_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)  # last watch time / points update

    join_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # number of times viewer is present (for multiple devices)

    chatted_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    followed_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    subscribed_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    tipped_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)

    watch_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    points: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    @hybrid_property
    def is_present(self) -> bool: # pyright: ignore[reportRedeclaration]
        """Returns True if the viewer is currently present in the channel."""
        return self.join_count > 0

    @is_present.expression # pyright: ignore[reportArgumentType]
    def is_present(cls):
        return cls.join_count > 0

    def join(self, timestamp: datetime | None = None):
        """Mark viewer as present on a new device/session."""
        self.join_count += 1
        self.joined_at = timestamp or utcnow()

    def leave(self, timestamp: datetime | None = None):
        """Mark one device/session as left; fully offline if last session."""
        if self.join_count > 0:
            self.join_count -= 1
        if self.join_count == 0:
            self.left_at = timestamp or utcnow()

    def force_offline(self, timestamp: datetime | None = None):
        """Force viewer fully offline, clearing any sessions."""
        self.join_count = 0
        self.left_at = timestamp or utcnow()
        self.joined_at = min(self.joined_at, self.left_at)

    user: Mapped[User] = relationship("User", uselist=False, back_populates="viewers")
    channel: Mapped[Channel] = relationship("Channel", uselist=False, back_populates="viewers")


# ==============================================================================
# Command Models

class Command(Base):
    """
    Channel command.
    """
    __tablename__ = "commands"
    __table_args__ = (
        Index("ix_commands_channel_id_key", "channel_id", "key"),
        UniqueConstraint("channel_id", "key"),

        CheckConstraint("point_cost >= 0"),
        CheckConstraint("channel_cooldown >= 0"),
        CheckConstraint("viewer_cooldown >= 0"),
        CheckConstraint("channel_limit >= 0"),
        CheckConstraint("viewer_limit >= 0"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), index=True, nullable=False)

    key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    default_alias_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("command_aliases.id", ondelete="SET NULL"), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    min_access_level: Mapped[CommandAccessLevel] = mapped_column(Enum(CommandAccessLevel), default=CommandAccessLevel.viewer.name, nullable=False)

    point_cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    channel_cooldown: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    channel_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    viewer_cooldown: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    viewer_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    channel: Mapped[Channel] = relationship("Channel", uselist=False, back_populates="commands")
    aliases: Mapped[list["CommandAlias"]] = relationship("CommandAlias", uselist=True, back_populates="command", foreign_keys="CommandAlias.command_id")
    default_alias: Mapped["CommandAlias"] = relationship("CommandAlias", uselist=False, post_update=True, lazy="joined", foreign_keys=[default_alias_id])
    channel_cooldowns: Mapped[list["ChannelCommandCooldown"]] = relationship("ChannelCommandCooldown", uselist=True, back_populates="command")
    viewer_cooldowns: Mapped[list["ViewerCommandCooldown"]] = relationship("ViewerCommandCooldown", uselist=True, back_populates="command")

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

class ChannelCommandCooldown(Base):
    """
    Channel command cooldowns.
    """
    __tablename__ = "channel_command_cooldowns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    command_id: Mapped[int] = mapped_column(Integer, ForeignKey("commands.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)

    used_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    count_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    count_current: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    command: Mapped[Command] = relationship("Command", uselist=False, back_populates="channel_cooldowns")

class ViewerCommandCooldown(Base):
    """
    Viewer command cooldowns.
    """
    __tablename__ = "viewer_command_cooldowns"
    __table_args__ = (
        Index("ix_viewer_command_cooldowns_command_id_user_id", "command_id", "user_id"),
        UniqueConstraint("command_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, nullable=False)
    command_id: Mapped[int] = mapped_column(Integer, ForeignKey("commands.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    used_at: Mapped[datetime] = mapped_column(AwareDateTime, default=utcnow, nullable=False)
    count_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    count_current: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    command: Mapped[Command] = relationship("Command", uselist=False, back_populates="viewer_cooldowns")
    user: Mapped[User] = relationship("User", uselist=False, back_populates="command_cooldowns")
