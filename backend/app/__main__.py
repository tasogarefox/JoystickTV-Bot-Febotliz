import asyncio
import uvicorn

from app import settings
from app.handlers.jstv import load_jstv_plugins
from app.handlers.jstv.commands import db as dbcmdhandlers
from app.log import setup_logging
from app.db.database import async_setup_database


# ==============================================================================
# Main

async def async_main():
    setup_logging()

    await async_setup_database()

    load_jstv_plugins()

    await dbcmdhandlers.sync_command_definitions(delete_missing=True)
    await dbcmdhandlers.sync_commands(reset_existing=True, delete_missing=True)

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
