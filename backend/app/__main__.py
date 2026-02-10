import asyncio
import uvicorn

from app import settings, commands
from app.log import setup_logging
from app.db.database import async_setup_database


# ==============================================================================
# Main

async def async_main():
    setup_logging()

    await async_setup_database()

    commands.initialize()

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
