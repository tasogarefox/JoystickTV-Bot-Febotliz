from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, Request, status
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from app import settings, paths, log
from app.routes import router
from app.bot import Bot


# ==============================================================================
# Logging

log.setup_logging()
log.hijack_uvicorn_logs()  # must be called before FastAPI/uvicorn startup


# ==============================================================================
# Lifespan

@asynccontextmanager
async def lifespan(app: FastAPI):
    bot = Bot()

    # Start bot background task
    bot_task = asyncio.create_task(bot.run())
    app.state.bot = bot  # Store it on app for routes to access

    try:
        yield  # Application runs here
    finally:
        # Stop the bot
        await bot.shutdown()

        # Cancel the top-level task
        bot_task.cancel()

        # Await it safely
        try:
            await bot_task
        except asyncio.CancelledError:
            pass


# ==============================================================================
# App

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Setup exception handlers
log.setup_fastapi_exception_handlers(app)

# Setup CORS (allow frontend to access API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

# Setup templates
templates = Jinja2Templates(directory=paths.TEMPLATE_DIR)

# Mount routers
app.include_router(router)

# Mount static files
app.mount(
    settings.SERVER_STATIC_PATH,
    StaticFiles(directory=paths.STATIC_DIR),
    name="static",
)

# Redirect root to frontend
@app.get("/", include_in_schema=False)
async def redirect_root():
    return RedirectResponse(url=settings.FRONTEND_BASE_URL, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

# Mount frontend
if paths.FRONTEND_DIST_DIR.exists():
    # Serve frontend dist
    app.mount(
        settings.FRONTEND_BASE_URL,
        StaticFiles(directory=paths.FRONTEND_DIST_DIR, html=True),
        name="frontend",
    )
else:
    # Frontend not built, serve fallback
    @app.get(settings.FRONTEND_BASE_URL, include_in_schema=False)
    async def read_app(request: Request):
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "APP_NAME": settings.APP_NAME,
                "FRONTEND_DIST_DIR": paths.FRONTEND_DIST_DIR,
            },
        )
