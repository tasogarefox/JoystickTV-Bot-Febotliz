import asyncio
import uvicorn

from app import settings
from app.handlers.jstv import (
    plugin_finder as jstv_plugin_finder,
    events as event_handlers,
    commands as command_handlers,
)
from app.log import setup_logging
from app.db.database import async_setup_database


# ==============================================================================
# Main

async def async_main():
    setup_logging()

    await async_setup_database()

    jstv_plugin_finder.install()
    event_handlers.initialize()
    command_handlers.initialize()

    config = uvicorn.Config(
        app="app.server:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        log_level=settings.LOG_LEVEL,
        reload=settings.DEBUG,
    )

    server = uvicorn.Server(config)
    await server.serve()

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
