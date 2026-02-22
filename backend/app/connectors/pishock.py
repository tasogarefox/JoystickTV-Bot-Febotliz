from typing import NamedTuple, ClassVar, Any, Iterator
from dataclasses import dataclass
import enum
import logging
import asyncio
import httpx
from datetime import datetime
import os
import re
from json import JSONDecodeError
import random

from pydantic import TypeAdapter, ValidationError

from app.connector import (
    ConnectorMessage, ConnectorManager, WebSocketConnector,
    ConnectorReconnect,
)
from app.utils.asyncio import async_select
from app.utils.pydantic import FrozenBaseModel, LoggedBaseModel

logger = logging.getLogger(__name__)

semaphore = asyncio.Semaphore(5)  # Limit concurrent web requests


# ==============================================================================
# Config

WEB_TIMEOUT = 10

USERNAME = os.getenv("PISHOCK_USERNAME")
APIKEY = os.getenv("PISHOCK_APIKEY")
SHARECODE = os.getenv("PISHOCK_SHARECODE")
assert USERNAME, "Missing environment variable: PISHOCK_USERNAME"
assert APIKEY, "Missing environment variable: PISHOCK_APIKEY"
assert SHARECODE, "Missing environment variable: PISHOCK_SHARECODE"

WS_BASE_URL = "wss://broker.pishock.com/v2"

NAME = "PiShock"
URL = f"{WS_BASE_URL}?Username={USERNAME}&ApiKey={APIKEY}"

API_AUTH_URL= "https://auth.pishock.com/Auth"
API_PS_URL= "https://ps.pishock.com/PiShock"


# ==============================================================================
# Errors

class PiShockError(Exception): pass
class PiShockWebError(PiShockError): pass
class PiShockWebResponseError(PiShockWebError): pass


# ==============================================================================
# Enums

class ShockMode(enum.Enum):
    Vibrate = "v"
    Shock = "s"
    Beep = "b"
    EmergencyStop = "e"
    Emergency = EmergencyStop


# ==============================================================================
# Models

class PiShockLoggedModel(LoggedBaseModel):
    logger = logger

# class APIKey(
#     FrozenBaseModel,
#     PiShockLoggedModel,
# ):
#     APIKey: str
#     Name: str
#     UserAPIKeyId: int
#     User: None
#     Generated: datetime
#     Expiry: None
#     Scopes: None

class UserInfo(
    FrozenBaseModel,
    # PiShockLoggedModel,
):
    UserId: int
    # Username: str
    # Password: str  # Hashed
    # Emails: None
    # Images: None
    # LastLogin: datetime
    # IPAddress: None
    # AccessPermissions: None
    # Sessions: None
    # OAuthLinks: None
    # APIKeys: tuple[APIKey, ...]

class Shocker(
    FrozenBaseModel,
    # PiShockLoggedModel,
):
    name: str
    shockerId: int
    # shockerType: int
    isPaused: bool

    @property
    def isAvailable(self) -> bool:
        return not self.isPaused

class Device(
    FrozenBaseModel,
    PiShockLoggedModel,
):
    clientId: int
    name: str
    userId: int
    username: str
    shockers: tuple[Shocker, ...]

class PiShockMessage(
    FrozenBaseModel,
    PiShockLoggedModel,
):
    ErrorCode: int | None
    IsError: bool
    Message: Any
    OriginalCommand: str

class PiShockPing(PiShockMessage):
    Message: str


# ==============================================================================
# Shock Command

class ShockFrame(NamedTuple):
    mode: ShockMode

    duration: float
    """Duration in seconds"""

    intensity: int
    """Intensity of vibration or shock in percent"""

    warning: float = 0
    """If this is greater than 0, vibrate and wait this many seconds before shocking"""

    def __str__(self) -> str:
        return f"<{self.__class__.__name__} {self.mode.name} {self.duration}s {self.intensity}%>"

    def __bool__(self) -> bool:
        return self.duration > 0.001  # Minimum duration is 1ms

    @property
    def duration_ms(self) -> int:
        return int(self.duration * 1000)

@dataclass(frozen=True, slots=True)
class ShockGroup:
    frames: tuple[ShockFrame, ...]

    channel_id: str = ""
    username: str = ""

    def __str__(self) -> str:
        return f"<{self.__class__.__name__} {len(self.frames)} items for {self.get_duration()}s>"

    def __bool__(self) -> bool:
        return bool(self.frames)

    def __len__(self) -> int:
        return len(self.frames)

    def __getitem__(self, index: int) -> ShockFrame:
        return self.frames[index]

    def __iter__(self) -> Iterator[ShockFrame]:
        return iter(self.frames)

    def get_duration(self) -> float:
        return sum(item.duration for item in self.frames)


# ==============================================================================
# Functions

def parse_shocks(vibestr: str) -> tuple["ShockFrame", ...]:
    NAME_MODE_MAP = {
        "vibrate": ShockMode.Vibrate,
        "vibe": ShockMode.Vibrate,
        "shock": ShockMode.Shock,
        "s": ShockMode.Shock,
        "v": ShockMode.Vibrate,
        "beep": ShockMode.Beep,
        "b": ShockMode.Beep,
        # "emergency": ShockMode.EmergencyStop,
        # "e": ShockMode.EmergencyStop,
    }

    # Values
    mode: ShockMode | None = None
    duration: float | None = None
    intensity: int | None = None
    warning: float | None = None

    # Parse the arguments
    # NOTE: Raise ValueError if the arguments are invalid
    for arg in vibestr.split(" "):
        arg = arg.strip()
        if not arg:
            continue

        if not arg[0].isdigit():  # This is the mode
            if mode is not None:
                raise ValueError(f"Currently only one mode can be specified: {arg}")

            try:
                mode = NAME_MODE_MAP[arg.casefold()]
                continue
            except KeyError:
                raise ValueError(f"Invalid mode: {arg}")

        elif arg.endswith("%"):  # This is the intensity in percent
            if intensity is not None:
                raise ValueError(f"Currently only one intensity can be specified: {arg}")

            try:
                intensity = int(arg[:-1])
                continue
            except ValueError:
                pass

            m = re.fullmatch(r'(\d+)%?-(\d+)%', arg)
            if m:
                low = int(m.group(1))
                high = int(m.group(2) or low)
                intensity = random.randint(low, high)
                continue

            raise ValueError(f"Invalid intensity format: {arg}")

        elif arg.endswith("s"):  # This is the duration in seconds
            if duration is not None:
                raise ValueError(f"Currently only one duration can be specified: {arg}")

            try:
                duration = float(arg[:-1])
                continue
            except ValueError:
                pass

            m = re.fullmatch(r'((?:\d+?\.)?\d+)s?-((?:\d+?\.)?\d+)s', arg)
            if m:
                low = float(m.group(1))
                high = float(m.group(2) or low)
                duration = random.uniform(low, high)
                continue

            raise ValueError(f"Invalid duration format: {arg}")

        # elif arg.endswith("w"):  # This is the duration after warning in seconds
        #     if warning is not None:
        #         raise ValueError(f"Currently only one warning duration can be specified: {arg}")

        #     try:
        #         warning = float(arg[:-1])
        #         continue
        #     except ValueError:
        #         pass

        #     m = re.fullmatch(r'((?:\d+?\.)?\d+)s?-((?:\d+?\.)?\d+)s', arg)
        #     if m:
        #         low = float(m.group(1))
        #         high = float(m.group(2) or low)
        #         warning = random.uniform(low, high)
        #         continue

        #     raise ValueError(f"Invalid warning format: {arg}")

        else:  # Invalid argument
            raise ValueError(f"Invalid argument: {arg}")

    frame = ShockFrame(
        mode or ShockMode.Shock,
        duration or 0.3,
        intensity or random.randint(1, 10),
        warning or 0,
    )

    return (frame,)

async def fetch_user_info() -> UserInfo:
    params = {
        "apikey": APIKEY,
        "username": USERNAME,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    url = f"{API_AUTH_URL}/GetUserIfAPIKeyValid"

    data = None
    try:
        async with semaphore, httpx.AsyncClient(timeout=WEB_TIMEOUT) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            return UserInfo.model_validate(data)
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error while fetching user ID: %s", e.response.text)
        raise PiShockWebError("HTTP error while fetching user ID") from e
    except httpx.RequestError as e:
        logger.error("Network error while fetching user ID: %s", e)
        raise PiShockWebError("Network error while fetching user ID") from e
    except JSONDecodeError as e:
        logger.error("Invalid JSON while fetching user ID: %s", e)
        raise PiShockWebError("Invalid JSON while fetching user ID") from e
    except ValidationError as e:
        logger.error("Invalid data while fetching user ID::\nErrors: %s\nData: %s", e, data)
        raise PiShockWebError("Invalid data while fetching user ID") from e

async def fetch_devices(user_id: int) -> tuple[Device, ...]:
    params = {
        "UserId": user_id,
        "Token": APIKEY,
        "api": True,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    url = f"{API_PS_URL}/GetUserDevices"

    data = None
    try:
        async with semaphore, httpx.AsyncClient(timeout=WEB_TIMEOUT) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            return TypeAdapter(tuple[Device, ...]).validate_python(data)
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error while fetching devices: %s", e.response.text)
        raise PiShockWebError("HTTP error while fetching devices") from e
    except httpx.RequestError as e:
        logger.error("Network error while fetching devices: %s", e)
        raise PiShockWebError("Network error while fetching devices") from e
    except JSONDecodeError as e:
        logger.error("Invalid JSON while fetching devices: %s", e)
        raise PiShockWebError("Invalid JSON while fetching devices") from e
    except ValidationError as e:
        logger.error("Invalid data while fetching devices:\nErrors: %s\nData: %s", e, data)
        raise PiShockWebError("Invalid data while fetching devices") from e


# ==============================================================================
# PiShock Connector

class PiShockConnector(WebSocketConnector):
    NAME: ClassVar[str] = NAME

    user_info: UserInfo | None = None
    devices: tuple[Device, ...] = tuple()
    device_pings: dict[int, datetime]

    def __init__(self, manager: ConnectorManager):
        super().__init__(manager)
        self.device_pings = {}

    # @property
    # def user_id(self) -> int | None:
    #     return self.user_info.UserId if self.user_info else None

    def _get_url(self) -> str:
        return URL

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        self.logger.info("Connector message received: %r, data: %s", msg, msg.data)

        if msg.action == "shock":
            if isinstance(msg.data, ShockFrame):
                try:
                    await self.send_shock(msg.data)
                except PiShockWebError:  # NOTE: Errors logged in send_command
                    pass
            return True

        return False

    async def on_connected(self) -> None:
        await super().on_connected()

        # self.logger.info("Pinging...")
        # await self.sendnow({"Operation": "PING"})

        info = self.user_info
        if not info:
            self.logger.info("Fetching user ID...")

            try:
                info = self.user_info = await fetch_user_info()
            except PiShockWebError as e:  # NOTE: Errors logged in fetch_user_info
                raise ConnectorReconnect("Failed to fetch user ID") from e

        user_id = info.UserId

        devices = self.devices
        if not devices:
            self.logger.info("Fetching devices...")

            try:
                devices = self.devices = await fetch_devices(user_id)
            except PiShockWebError as e:  # NOTE: Errors logged in fetch_devices
                raise ConnectorReconnect("Failed to fetch devices") from e

        # self.logger.info("Subscribing to devices...")
        # await self.sendnow({
        #     "Operation": "SUBSCRIBE",
        #     "Targets": [
        #         item
        #         for device in devices
        #         for item in
        #         [f"{device.clientId}-ping", f"{device.clientId}-log"]
        #     ],
        #     "PublishCommands": None,
        # })

        self.logger.info("Done initializing")

    async def on_disconnected(self):
        await super().on_disconnected()

    async def on_error(self, error: Exception) -> None:
        return await super().on_error(error)

    async def on_message(self, data: dict[Any, Any]):
        self.logger.info("Received: %s", data)

    async def send_shock(self, cmd: ShockFrame) -> bool:
        # self.logger.info("Sending shock: %s", cmd)

        user_id = self.user_info.UserId if self.user_info else None
        if not user_id:
            return False

        try:
            device = random.choice(self.devices)
            shocker = random.choice(device.shockers)
        except IndexError:
            return False

        if not shocker.isAvailable:
            return False

        targets = [(device, shocker)]

        data = {
        	"Operation": "PUBLISH",
        	"PublishCommands": [{
    			"Target": f"c{device.clientId}-ops",  # for example c{clientId}-ops or c{clientId}-sops-{sharecode}
    			"Body": {
    				"id": shocker.shockerId,  # shocker ID,
    				"m": cmd.mode.value,  # 'v', 's', 'b', or 'e'
    				"i": cmd.intensity,  # Could be vibIntensity, shockIntensity or a randomized value
    				"d": cmd.duration_ms,  # Calculated duration in milliseconds
    				"r": True,  # true or false, always set to true.
    				"l": {
    					"u": user_id,  # User ID from first step
    	                "ty": "api",  # 'sc' for ShareCode, 'api' for Normal
    	                "w": False,  # true or false, if this is a warning vibrate, it affects the logs
    	                "h": False,  # true if button is held or continuous is being sent.
    	                "o": self.logger.name,  # send to change the name shown in the logs.
    	            },
    			},
            } for device, shocker in targets],
        }

        return await self.sendnow(data)
