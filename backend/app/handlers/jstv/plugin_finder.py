import logging

from app import paths
from app.plugins import PluginFinder

__all__ = [
    "plugin_finder",
    "load_jstv_plugins",
]

PLUGIN_NAME = "jstv"
PLUGIN_DIRS = (
    paths.BACKEND_DIR / "plugins" / PLUGIN_NAME,
    paths.BACKEND_DIR / "plugins" / "local" / PLUGIN_NAME,
)

logger = logging.getLogger(__package__ or __name__)

plugin_finder = PluginFinder(PLUGIN_NAME, PLUGIN_DIRS)


# ==============================================================================
# Interface

def load_jstv_plugins():
    plugin_finder.install()

    for fullname, ispkg in sorted(plugin_finder.iter_plugins()):
        basename = fullname.rpartition(".")[2]
        if basename.startswith("_"):
            continue

        try:
            plugin_finder.import_plugin(fullname)
        except Exception as e:
            logger.exception("Failed to import plugin %r", fullname)
            continue

        logger.info("Loaded plugin %r", fullname)
