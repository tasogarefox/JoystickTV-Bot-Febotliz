from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends

from app.bot import Bot
from app.connectors.joysticktv import JoystickTVConnector
from app.handlers.jstv.commands import db as dbcmdhandlers
from app.jstv import jstv_db
from app.db.database import depend_async_db_transaction

router = APIRouter(prefix="/command", tags=["command"])


# ==============================================================================
# Endpoints

@router.post("/")
async def run_command(
    channel_id: str,
    username: str,
    command: str,
    db: AsyncSession = Depends(depend_async_db_transaction),
):
    command = command.strip()
    if not command:
        return {"status": "error", "message": "Empty command"}

    alias, _, argument = command.partition(" ")
    alias, argument = alias.strip(), argument.strip()

    if alias.startswith("!"):
        alias = alias[1:]

    if not alias:
        return {"status": "error", "message": "Empty command name"}

    try:
        bot = next(iter(Bot.INSTANCES))
    except StopIteration:
        return {"status": "error", "message": "Bot not running"}

    jstv_connector = bot.get(JoystickTVConnector)
    if jstv_connector is None:
        return {"status": "error", "message": "JoystickTV connector not found"}

    channel = await jstv_db.get_channel(db, channel_id)
    if channel is None:
        return {"status": "error", "message": "Channel not found"}

    user = await jstv_db.get_user(db, username)
    if user is None:
        return {"status": "error", "message": "User not found"}

    viewer = await jstv_db.get_viewer(db, channel, user)
    if viewer is None:
        return {"status": "error", "message": "Viewer not found"}

    cmd_result = await dbcmdhandlers.invoke_command(
        db,
        channel=channel,
        user=user,
        viewer=viewer,
        connector=jstv_connector,
        message=None,
        alias=alias,
        argument=argument,
        check_permissions=False,
        check_cooldown=False,
        pay=False,
    )

    if cmd_result is None:
        return {"status": "error", "message": "Command not found"}

    if cmd_result is False:
        return {"status": "error", "message": "Command execution failed"}

    return {"status": "ok"}
