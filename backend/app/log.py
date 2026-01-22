import os

import logging
from logging.handlers import RotatingFileHandler

from colorama import Fore, Style, init

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app import settings

LOGGING_HANDLERS = []


# ==============================================================================
# Colorama

# Initialize colorama (important on Windows)
# init(autoreset=False)


# ==============================================================================
# ColorFormatter

class ColorFormatter(logging.Formatter):
    COLORS = {
        "RESET": Style.RESET_ALL,
        "MSG": Fore.WHITE,
        "TIME": Fore.CYAN,
        "NAME": Fore.LIGHTCYAN_EX,
        "FILENAME": Fore.LIGHTMAGENTA_EX,
        "LEVEL": {
            "DEBUG": Fore.BLUE,
            "INFO": Fore.GREEN,
            "WARNING": Fore.YELLOW,
            "ERROR": Fore.RED,
            "CRITICAL": Fore.MAGENTA,
        }
    }

    def format(self, record: logging.LogRecord) -> str:
        C = self.COLORS

        # Make a shallow copy so we don't break file logging or other handlers
        new_record = logging.makeLogRecord(record.__dict__)

        # Colorize level name
        lvl_color = C["LEVEL"].get(record.levelname, "")
        new_record.levelname = f"{lvl_color}{record.levelname}{C['RESET']}"

        # Colorize logger name
        new_record.name = f"{C['NAME']}{record.name}{C['RESET']}"

        # Colorize filename
        new_record.filename = f"{C['FILENAME']}{record.filename}{C['RESET']}"

        # Colorize message
        new_record.msg = f"{C['MSG']}{record.msg}{C['RESET']}"

        # Now call super formatter using modified record
        return super().format(new_record)

    def formatTime(self, record, datefmt=None):
        ts = super().formatTime(record, datefmt)
        return f"{self.COLORS['TIME']}{ts}{self.COLORS['RESET']}"


# ==============================================================================
# Functions

def get_logger() -> logging.Logger:
    return logging.getLogger(settings.APP_SLUG.capitalize())

def get_logging_handlers() -> tuple[logging.Handler, ...]:
    return tuple(LOGGING_HANDLERS)

__done_setup_logging = False
def has_setup_logging() -> bool:
    return __done_setup_logging

def setup_logging() -> None:
    global __done_setup_logging
    if __done_setup_logging:
        return
    __done_setup_logging = True

    # Create log directory
    if not os.path.exists(settings.LOG_DIR):
        os.makedirs(settings.LOG_DIR)

    # log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(filename)s:%(lineno)d:  %(message)s"
    log_format = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"

    # Create colored stream handler
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter(log_format))
    LOGGING_HANDLERS.append(handler)

    # Create rotating file handler
    handler = RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=1_000_000,
        backupCount=10,
        encoding="utf-8",
        errors="backslashreplace",
    )
    handler.setFormatter(logging.Formatter(log_format))
    LOGGING_HANDLERS.append(handler)

    # Add filter to ignore obswsc.client
    class IgnoreOBSWSC(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return not record.pathname.replace("\\", "/").endswith("/obswsc/client.py")

    for handler in LOGGING_HANDLERS:
        handler.addFilter(IgnoreOBSWSC())

    # # Add handlers to logger
    # logger = get_logger()
    # for handler in LOGGING_HANDLERS:
    #     logger.addHandler(handler)

    # Set up logging configuration
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format=log_format,
        handlers=LOGGING_HANDLERS,
    )

def hijack_uvicorn_logs() -> None:
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_error = logging.getLogger("uvicorn.error")

    logger = get_logger()

    for log in (uvicorn_logger, uvicorn_access, uvicorn_error):
        log.handlers = []  # Remove uvicorn's default console handler
        log.propagate = True
        logger.debug(f"Redirected uvicorn logger: {log.name}")

def setup_fastapi_exception_handlers(app: FastAPI) -> None:
    logger = get_logger().getChild("FastAPI")

    @app.middleware("http")
    async def exception_middleware(request: Request, call_next) -> Response:
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception(f"Exception during {request.method} {request.url.path}")
            raise
        return response

    @app.exception_handler(Exception)
    async def default_exception_handler(request: Request, exc: Exception) -> Response:
        logger.exception(f"Exception during {request.method} {request.url.path}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal Server Error"}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
        logger.warning(
            f"422 Validation error on {request.method} {request.url.path}\n"
            f"Query: {dict(request.query_params)}\n"
            f"Body: {await request.body()!r}\n"
            f"Details: {exc.errors()}"
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()}
        )
