from typing import Any, Collection, Mapping, cast
from dataclasses import dataclass, field
from datetime import datetime
import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import POINTS_NAME
from app.connector import BaseConnector
from app.events import jstv as evjstv
from app.jstv import jstv_db, jstv_dbstate
from app.db.database import AsyncSessionMaker
from app.db.models import (
    Channel, User, Viewer,
    CommandDefinition, Command,
    CommandTag, CommandAlias,
    ChannelCommandCooldown, ViewerCommandCooldown,
)
from app.utils.datetime import utcnow

from .handler import JSTVCommand, JSTVCommandContext, JSTVCommandSettings

logger = logging.getLogger(__name__)

COMMAND_MAP = cast(Mapping[str, type[JSTVCommand]], JSTVCommand.handlers)


# ==============================================================================
# Config

STREAMER_EXEMPT = True


# ==============================================================================
# Context Classes

@dataclass(slots=True)
class BoundCommand:
    dbcommand: Command
    dbdefinition: CommandDefinition
    command: type[JSTVCommand[Any, Any]]
    aliases: tuple[str, ...]

    @classmethod
    async def from_alias(
        cls,
        db: AsyncSession,
        alias: str,
        channel_db_id: int,
    ) -> "BoundCommand":
        alias_fold = alias.casefold()

        result = await db.execute(
            select(Command)
            .join(Command.definition)
            .options(
                joinedload(Command.definition).selectinload(CommandDefinition.tags),
                selectinload(Command.aliases),
            )
            .where(
                Command.channel_id == channel_db_id,
                Command.aliases.any(CommandAlias.name == alias_fold),
            )
            .order_by(CommandDefinition.priority.desc())
        )

        dbcmd = result.scalar_one_or_none()
        if dbcmd is None:
            raise KeyError(f"Unknown command: {alias}")

        if dbcmd.disabled or dbcmd.definition.disabled:
            raise ValueError(f"Command {alias} is disabled.")

        try:
            cmd = COMMAND_MAP[dbcmd.definition.key]
        except KeyError:
            raise KeyError(f"Unimplemented command; key: {dbcmd.definition.key}")

        return cls(
            dbcommand=dbcmd,
            dbdefinition=dbcmd.definition,
            command=cmd,
            aliases=tuple(x.name for x in dbcmd.aliases_default_first),
        )

    def make_settings(self) -> JSTVCommandSettings:
        dbcmd: Command = self.dbcommand
        return JSTVCommandSettings(
            aliases = self.aliases,
            min_access_level=dbcmd.min_access_level,
            base_cost=dbcmd.base_cost,

            channel_cooldown=dbcmd.channel_cooldown,
            channel_limit=dbcmd.channel_limit,
            viewer_cooldown=dbcmd.viewer_cooldown,
            viewer_limit=dbcmd.viewer_limit,
        )

@dataclass(slots=True)
class BoundViewerCommand:
    bound_command: BoundCommand
    bound_viewer: jstv_db.BoundViewer

    channel_cooldown: ChannelCommandCooldown | None = field(init=False, default=None)
    viewer_cooldown: ViewerCommandCooldown | None = field(init=False, default=None)

    @classmethod
    async def from_alias(
        cls,
        db: AsyncSession,
        alias: str,
        bound_viewer: jstv_db.BoundViewer,
    ) -> "BoundViewerCommand":
        channel = await bound_viewer.lazy_channel()
        bound_command = await BoundCommand.from_alias(db, alias, channel.id)
        return await cls.from_bound_command(bound_command, bound_viewer)

    @classmethod
    async def from_bound_command(
        cls,
        bound_command: BoundCommand,
        bound_viewer: jstv_db.BoundViewer,
    ) -> "BoundViewerCommand":
        # channel = await bound_viewer.lazy_channel()
        # if channel.id != bound_command.dbcommand.channel_id:
        #     raise ValueError(f"Channel mismatch: {channel.id} != {bound_command.dbcommand.channel_id}")

        return cls(bound_command, bound_viewer)

    @property
    def db(self) -> AsyncSession:
        return self.bound_viewer.db

    @property
    def dbcommand(self) -> Command:
        return self.bound_command.dbcommand

    @property
    def dbdefinition(self) -> CommandDefinition:
        return self.bound_command.dbdefinition

    @property
    def command(self) -> type[JSTVCommand[Any, Any]]:
        return self.bound_command.command

    @property
    def aliases(self) -> tuple[str, ...]:
        return self.bound_command.aliases

    @property
    def channel(self) -> Channel | None:
        return self.bound_viewer.channel

    @property
    def user(self) -> User | None:
        return self.bound_viewer.user

    @property
    def viewer(self) -> Viewer | None:
        return self.bound_viewer.viewer

    async def lazy_channel(self) -> Channel:
        return await self.bound_viewer.lazy_channel()

    async def lazy_user(self) -> User:
        return await self.bound_viewer.lazy_user()

    async def lazy_viewer(self) -> Viewer:
        return await self.bound_viewer.lazy_viewer()

    async def lazy_channel_cooldown(self) -> ChannelCommandCooldown:
        if self.channel_cooldown is not None:
            return self.channel_cooldown

        self.channel_cooldown = await get_or_create_channel_command_cooldown(
            self.db, self.dbcommand.id,
        )

        return self.channel_cooldown

    async def lazy_viewer_cooldown(self) -> ViewerCommandCooldown:
        if self.viewer_cooldown is not None:
            return self.viewer_cooldown

        bound_viewer = self.bound_viewer

        user_id: int
        if bound_viewer.user is not None:
            user: User = bound_viewer.user
            user_id = user.id
        elif bound_viewer.viewer is not None:
            viewer: Viewer = bound_viewer.viewer
            user_id = viewer.user_id
        else:
            user = await bound_viewer.lazy_user()
            user_id = user.id

        dbcmd: Command = self.dbcommand

        self.viewer_cooldown = await get_or_create_viewer_command_cooldown(
            self.db, dbcmd.id, user_id,
        )

        return self.viewer_cooldown

    def make_settings(self) -> JSTVCommandSettings:
        return self.bound_command.make_settings()

    async def make_command_context(
        self,
        connector: BaseConnector,
        message: evjstv.JSTVMessage | None,
        alias: str,
        argument: str | None,
        *,
        settings: JSTVCommandSettings | None = None,
    ) -> JSTVCommandContext:
        # if alias.casefold() not in self.aliases:
        #     raise ValueError(f"Alias mismatch: {alias} not in {self.aliases}")

        if settings is None:
            settings = self.make_settings()

        dbcmd: Command = self.dbcommand

        channel = await self.lazy_channel()
        user = await self.lazy_user()
        viewer = await self.lazy_viewer()

        cd_channel = await self.lazy_channel_cooldown()
        cd_viewer = await self.lazy_viewer_cooldown()

        # Create context
        memory = dbcmd.memory
        # if not isinstance(memory, dict):
        #     memory = {}

        return JSTVCommandContext(
            settings=settings,
            connector=connector,
            message=message,
            db=self.db,
            channel=channel,
            user=user,
            viewer=viewer,
            channel_cooldown=cd_channel,
            viewer_cooldown=cd_viewer,
            alias=alias,
            argument=argument or "",
        )

    async def invoke(
        self,
        ctx: JSTVCommandContext,
        *,
        check_permissions: bool = True,
        check_cooldown: bool = True,
        pay: bool = True,
    ) -> bool | None:
        from app.connectors.joysticktv import JoystickTVConnector

        jstv = ctx.connector.manager.get(JoystickTVConnector)
        if jstv is None:
            return None

        cmd = self.command
        dbcmd: Command = self.dbcommand

        settings = ctx.settings
        alias = ctx.alias

        channel: Channel = ctx.channel
        viewer: Viewer = ctx.viewer

        cd_channel: ChannelCommandCooldown = ctx.channel_cooldown
        cd_viewer: ViewerCommandCooldown = ctx.viewer_cooldown

        now = utcnow()

        async with self.db.begin_nested():
            # Commands can always be used by the streamer or fake messages
            if (
                (STREAMER_EXEMPT and viewer.is_streamer) or
                (ctx.message is not None and ctx.message.isFake)
            ):
                check_permissions = False
                check_cooldown = False
                pay = False

            # Check access level
            if check_permissions:
                access_level = viewer.access_level
                if access_level < settings.min_access_level:
                    await ctx.reply((
                        f"Insufficient permissions to use command {alias}"
                    ), mention=True)
                    return False

            # Ensure points are up-to-date
            jstv_dbstate.reward_viewer_watch_time(channel, viewer)

            # Check base cost
            if pay and settings.base_cost > viewer.points:
                await ctx.reply((
                    f"Insufficient {POINTS_NAME} to use command {alias}"
                ), whisper=True)
                return False

            # Check channel cooldown
            if check_cooldown:
                if not await _check_channel_cooldown(ctx, channel, cd_channel, now=now):
                    return False

            # Check viewer cooldown
            if check_cooldown:
                if not await _check_viewer_cooldown(ctx, channel, cd_viewer, now=now):
                    return False

            logger.info("Invoking command handler %r", cmd.key)

            # Prepare handler
            try:
                success = await cmd.prepare(ctx)

            except Exception as e:
                # Report error
                logger.exception("Error preparing command %r: %s", cmd.key, e)
                await ctx.reply((
                    f"Error preparing command {alias}. See logs for details"
                ))

                return False

            if not success:
                return False

            # Calculate costs
            total_cost: int
            if not pay:
                var_costs = {}
                total_cost = 0
            else:
                try:
                    var_costs = await cmd.variable_costs(ctx)
                    total_cost = calc_total_cost(settings.base_cost, var_costs)

                except Exception as e:
                    # Report error
                    logger.exception("Error calculating variable costs for command %r: %s", cmd.key, e)
                    await ctx.reply((
                        f"Error calculating variable costs for command {alias}."
                        f" See logs for details"
                    ))

                    return False

            # Check total cost
            if total_cost and total_cost > viewer.points:
                str_costs = format_command_costs(settings.base_cost, var_costs)
                await ctx.reply((
                    f"Insufficient {POINTS_NAME} to use command {alias}: {str_costs}"
                ), whisper=True)

                return False

            # Pay points
            if total_cost:
                jstv_dbstate.adjust_viewer_points(viewer, -total_cost, (
                    f"command {alias}"
                ))

            # Invoke handler
            try:
                success = await cmd.handle(ctx)

            except Exception as e:
                # Refund points
                if total_cost:
                    jstv_dbstate.adjust_viewer_points(viewer, total_cost, (
                        f"refund for error in command {alias}"
                    ))

                # Report error
                logger.exception("Error handling command %r: %s", cmd.key, e)
                await ctx.reply((
                    f"Error handling command {alias}."
                    f" See logs for details"
                ))

                return False

            if not success:
                # Refund points
                if total_cost:
                    jstv_dbstate.adjust_viewer_points(viewer, total_cost, (
                        f"refund for failed command {alias}"
                    ))
                return False

            # Update database
            # dbcmd.memory = ctx.memory

            cd_channel.cur_count = channel.accumulate_per_stream(
                cd_channel.cur_count, 1, cd_channel.last_used_at,
            )
            cd_channel.total_count += 1
            cd_channel.last_used_at = now

            cd_viewer.cur_count = channel.accumulate_per_stream(
                cd_viewer.cur_count, 1, cd_viewer.last_used_at,
            )
            cd_viewer.total_count += 1
            cd_viewer.last_used_at = now
            cd_viewer.last_exec_alias = ctx.alias
            cd_viewer.last_exec_argument = ctx.argument
            cd_viewer.last_exec_cost = total_cost

            return True


# ==============================================================================
# Interface

def calc_total_cost(
    base_cost: int,
    variable_costs: dict[str, float],
) -> int:
    return max(0, int(base_cost + sum(variable_costs.values())))

def format_command_costs(
    base_cost: int,
    variable_costs: dict[str, float],
) -> str:
    total_cost = calc_total_cost(base_cost, variable_costs)
    text = f"{total_cost:,d} {POINTS_NAME}"
    if not variable_costs:
        return text

    var_cost_str = (
        f"{base_cost:,d} base"
        + "".join(f" + {v:,.1f} {k}" for k, v in variable_costs.items())
    )

    text += f" ({var_cost_str})"
    return text

async def load_command_definitions(
    db: AsyncSession,
    *,
    keys: Collection[str] | None = None,
) -> dict[str, CommandDefinition]:
    """
    Load command definitions from the database by their keys.
    """
    stmt = select(CommandDefinition)
    if keys is not None:
        stmt = stmt.where(CommandDefinition.key.in_(keys))

    result = await db.scalars(stmt)

    return {
        definition.key: definition
        for definition in result.all()
    }

async def sync_command_definitions(
    *,
    delete_missing: bool = False,
) -> None:
    """
    Synchronize command definitions with their handler definitions.
    If `delete_missing` is set, missing definitions will be deleted.
    """
    async with AsyncSessionMaker.begin() as db:
        result = await db.scalars(
            select(CommandDefinition)
            .options(selectinload(CommandDefinition.tags))
        )

        db_definitions = {
            cmd.key: cmd
            for cmd in result.all()
        }

        # --- Delete removed definitions ---

        if delete_missing:
            for key, db_definition in db_definitions.items():
                if key not in COMMAND_MAP:
                    logger.info("Deleting command definition %s", key)
                    await db.delete(db_definition)

        # --- Insert / Update definitions ---

        for key, command in COMMAND_MAP.items():
            db_definition = db_definitions.get(key)

            if db_definition is None:
                logger.info("Inserting command definition %s", key)

                db_definition = CommandDefinition(
                    key=key,
                    tags=[],
                )

                db.add(db_definition)
                await db.flush()

            # --- Reset scalar fields ---
            db_definition.priority = command.priority

            # --- Sync Tags ---

            existing_tags = {x.name: x for x in db_definition.tags}
            incoming_tags = set(x.casefold() for x in command.tags)

            # Delete removed
            for name, tag in existing_tags.items():
                if name not in incoming_tags:
                    logger.debug("Deleting command %s tag: %s", key, name)
                    await db.delete(tag)

            # Add new
            for name in incoming_tags:
                if name not in existing_tags:
                    logger.debug("Inserting command %s tag: %s", key, name)
                    db_definition.tags.append(CommandTag(name=name))

async def sync_commands(
    *,
    reset_existing: bool = False,
    delete_missing: bool = False,
) -> None:
    """
    Synchronize database commands with their handler definitions.
    """
    async with AsyncSessionMaker.begin() as db:
        # Load command definitions
        db_definitions = await load_command_definitions(db, keys=JSTVCommand.handlers.keys())

        # Load channels IDs
        result = await db.execute(select(Channel.id))
        channel_ids = result.scalars().unique().all()

        # Sync
        for channel_id in channel_ids:
            await sync_channel_commands(
                db,
                channel_id,
                db_definitions=db_definitions,
                reset_existing=reset_existing,
                delete_missing=delete_missing,
            )

async def sync_channel_commands(
    db: AsyncSession,
    channel_db_id: int,
    *,
    db_definitions: dict[str, CommandDefinition] | None = None,
    reset_existing: bool = False,
    delete_missing: bool = False,
) -> None:
    """
    Synchronize database commands with their handler definitions.
    If `reset_existing` is set, existing commands will be reset to their handler definition.
    If `delete_missing` is set, commands not present in handler definitions will be deleted.
    """
    # Load existing commands
    result = await db.scalars(
        select(Command)
        .options(
            selectinload(Command.definition),
            selectinload(Command.aliases),
        )
        .where(Command.channel_id == channel_db_id)
    )
    db_commands = {
        cmd.definition.key: cmd
        for cmd in result.all()
    }

    # Load definitions
    if db_definitions is None:
        db_definitions = await load_command_definitions(db, keys=COMMAND_MAP.keys())

    # Delete removed commands
    if delete_missing:
        for key, db_command in db_commands.items():
            if key not in COMMAND_MAP:
                logger.info("Deleting command %s for channel #%s", key, channel_db_id)
                await db.delete(db_command)

    # Insert / Update commands
    for key, command in COMMAND_MAP.items():
        definition = db_definitions.get(key)

        if definition is None:
            raise RuntimeError(
                f"Command definition missing for key '{key}'. "
                f"Run `sync_command_definitions` first."
            )

        db_command = db_commands.get(key)

        is_new = False
        if db_command is None:
            is_new = True

            logger.info("Inserting command %s for channel #%s", key, channel_db_id)

            db_command = Command(
                definition_id=definition.id,
                channel_id=channel_db_id,
                aliases=[],
            )

            db.add(db_command)
            await db.flush()

        if is_new or reset_existing:
            if not is_new:
                logger.debug("Resetting command %s for channel #%s", key, channel_db_id)
            await reset_command(db, db_command, command)

async def reset_command(
    db: AsyncSession,
    db_command: Command,
    command: type[JSTVCommand],
) -> None:
    """
    Reset a single database command to match its handler definition.
    """
    settings = command.settings

    # --- Reset scalar fields ---
    db_command.disabled = command.disabled
    db_command.min_access_level = settings.min_access_level
    db_command.base_cost = settings.base_cost
    db_command.channel_cooldown = settings.channel_cooldown
    db_command.channel_limit = settings.channel_limit
    db_command.viewer_cooldown = settings.viewer_cooldown
    db_command.viewer_limit = settings.viewer_limit
    # db_command.memory = {}

    # --- Sync Aliases ---

    aliases = tuple(x.casefold() for x in settings.aliases)

    existing_aliases = {x.name: x for x in db_command.aliases}
    incoming_aliases = set(aliases)

    # Delete removed aliases
    for name, db_alias in existing_aliases.items():
        if name not in incoming_aliases:
            await db.delete(db_alias)

    # Add new aliases
    for name in incoming_aliases:
        if name not in existing_aliases:
            db_command.aliases.append(CommandAlias(name=name))

    # Ensure new aliases have IDs before assigning default
    await db.flush()

    # Set default alias
    db_command.default_alias = None
    if aliases:
        default_alias_name = aliases[0]
        for alias in db_command.aliases:
            if alias.name == default_alias_name:
                db_command.default_alias = alias
                break

async def load_command(
    db: AsyncSession,
    channel_db_id: int,
    alias: str,
    *,
    enabled_only: bool = True,
) -> tuple[Command, CommandDefinition, tuple[CommandAlias, ...]]:
    alias_fold = alias.casefold()

    result = await db.execute(
        select(Command)
        .join(Command.definition)
        .options(
            joinedload(Command.definition).selectinload(CommandDefinition.tags),
            selectinload(Command.aliases),
        )
        .where(
            Command.channel_id == channel_db_id,
            Command.aliases.any(CommandAlias.name == alias_fold),
        )
        .order_by(CommandDefinition.priority.desc())
        .limit(1)
    )

    dbcmd = result.scalar_one_or_none()
    if dbcmd is None:
        raise KeyError(f"Unknown command: {alias}")

    if dbcmd.disabled or dbcmd.definition.disabled:
        raise ValueError(f"Command {alias} is disabled.")

    return dbcmd, dbcmd.definition, tuple(dbcmd.aliases_default_first)

async def invoke_command(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str,
    viewer: Viewer | None,
    connector: BaseConnector,
    message: evjstv.JSTVMessage | None,
    alias: str,
    argument: str | None,
    *,
    check_permissions: bool = True,
    check_cooldown: bool = True,
    pay: bool = True,
) -> bool | None:
    from app.connectors.joysticktv import JoystickTVConnector

    if not alias:
        return None

    jstv = connector.manager.get(JoystickTVConnector)
    if jstv is None:
        return None

    bound_viewer = jstv_db.BoundViewer(db, channel, user, viewer)

    channel = await bound_viewer.lazy_channel()
    user = await bound_viewer.lazy_user()

    try:
        bound_vcmd = await BoundViewerCommand.from_alias(
            db,
            alias,
            bound_viewer,
        )

    except KeyError:
        # Silently ignore unknown commands, as other bots may define them
        return None

    except ValueError as e:
        await jstv.send_chat(channel.channel_id, str(e), mention=user.username)
        return None

    cmdctx = await bound_vcmd.make_command_context(
        connector=connector,
        message=message,
        alias=alias,
        argument=argument,
    )

    return await bound_vcmd.invoke(
        ctx=cmdctx,
        check_permissions=check_permissions,
        check_cooldown=check_cooldown,
        pay=pay,
    )



async def get_or_create_channel_command_cooldown(
    db: AsyncSession,
    command_id: int,
) -> ChannelCommandCooldown:
    result = await db.execute(
        select(ChannelCommandCooldown)
        .filter_by(command_id=command_id)
    )

    cooldown = result.scalar_one_or_none()
    if cooldown is None:
        cooldown = ChannelCommandCooldown(
            command_id=command_id,
        )

        db.add(cooldown)
        await db.flush()

    return cooldown

async def get_or_create_viewer_command_cooldown(
    db: AsyncSession,
    command_id: int,
    user_id: int,
) -> ViewerCommandCooldown:
    result = await db.execute(
        select(ViewerCommandCooldown)
        .filter_by(command_id=command_id, user_id=user_id)
    )

    cooldown = result.scalar_one_or_none()
    if cooldown is None:
        cooldown = ViewerCommandCooldown(
            command_id=command_id,
            user_id=user_id,
        )

        db.add(cooldown)
        await db.flush()

    return cooldown

async def _check_channel_cooldown(
    ctx: JSTVCommandContext,
    channel: Channel,
    cooldown: ChannelCommandCooldown,
    *,
    now: datetime | None = None,
) -> bool:
    if now is None:
        now = utcnow()

    if cooldown.last_used_at is None:
        return True

    settings = ctx.settings

    if (
        settings.channel_limit > 0 and
        cooldown.cur_count >= settings.channel_limit and
        cooldown.last_used_at > channel.live_at
    ):
        await ctx.reply((
            f"Command {ctx.alias} already hit its"
            f" limit this stream ({settings.channel_limit})"
        ), mention=True)
        return False

    tpassed = (now - cooldown.last_used_at).total_seconds()
    tleft = settings.channel_cooldown - int(tpassed)
    if tleft > 0:
        tmin, tsec = divmod(tleft, 60)
        await ctx.reply((
            f"Command {ctx.alias} is on cooldown"
            f" for {tmin:,d}:{tsec:02d} remaining"
        ), mention=True)
        return False

    return True

async def _check_viewer_cooldown(
    ctx: JSTVCommandContext,
    channel: Channel,
    cooldown: ViewerCommandCooldown,
    *,
    now: datetime | None = None,
) -> bool:
    if now is None:
        now = utcnow()

    if cooldown.last_used_at is None:
        return True

    settings = ctx.settings

    if (
        settings.viewer_limit > 0 and
        cooldown.cur_count >= settings.viewer_limit and
        cooldown.last_used_at > channel.live_at
    ):
        await ctx.reply((
            f"Command {ctx.alias} already hit its per-viewer"
            f" limit this stream ({settings.viewer_limit})"
        ), mention=True)
        return False

    tpassed = (now - cooldown.last_used_at).total_seconds()
    tleft = settings.viewer_cooldown - int(tpassed)
    if tleft > 0:
        tmin, tsec = divmod(tleft, 60)
        await ctx.reply((
            f"Command {ctx.alias} is on per-viewer cooldown"
            f" for {tmin:,d}:{tsec:02d} remaining"
        ), mention=True)
        return False

    return True
