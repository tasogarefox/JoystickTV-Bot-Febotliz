import logging

from app import paths
from app.plugins import PluginFinder

from .command import Command

__all__ = [
    "get",
    "get_by_alias",
    "initialize",
]

PLUGIN_NAME = "commands"
PLUGIN_DIRS = (
    paths.BACKEND_DIR / "plugins" / PLUGIN_NAME,
)

COMMANDS: dict[str, type[Command]] = {}
COMMANDS_BY_ALIAS: dict[str, type[Command]] = {}

logger = logging.getLogger(__package__ or __name__)

command_finder = PluginFinder(PLUGIN_NAME, PLUGIN_DIRS)


# ==============================================================================
# Interface

get = COMMANDS.get

get_by_alias = COMMANDS_BY_ALIAS.get

def initialize():
    command_finder.install()
    for name, ispkg in command_finder.iter_plugins():
        try:
            plugin = command_finder.import_plugin(name)
        except ImportError:
            logger.exception("Failed to import plugin %r", name)
            continue

        try:
            for cmd in plugin.__dict__.values():
                if cmd is Command or not isinstance(cmd, type) or not issubclass(cmd, Command):
                    continue

                try:
                    register(cmd)
                except ValueError as e:
                    logger.exception("Failed to register command %r: %s", cmd.key, e)
                    continue

        except Exception:
            logger.exception("Failed to import plugin %r", name)
            continue

        logger.info("Initialized plugin %r", name)

def register(cmd: type[Command]):
    if cmd.key in COMMANDS:
        raise ValueError(f"Command already registered: {cmd.key}")

    COMMANDS[cmd.key] = cmd

    for alias in cmd.aliases:
        if alias in COMMANDS_BY_ALIAS:
            continue
        COMMANDS_BY_ALIAS[alias] = cmd

    logger.info("Registered command %r", cmd.key)
