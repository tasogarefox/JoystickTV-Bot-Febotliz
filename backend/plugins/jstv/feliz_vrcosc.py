from app.db.enums import AccessLevel
from app.handlers import HandlerTags
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings
from app.connectors.vrchat import VRChatConnector


# ==============================================================================
# Helpers

def parse_bool(value: str) -> bool:
    value_lower = value.lower()
    if value_lower in ("true", "t", "yes", "y", "1"):
        return True
    if value_lower in ("false", "f", "no", "n", "0"):
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")

VALUE_PARSERS = {
    "float": ("float", float),
    "f": ("float", float),
    "int": ("int", int),
    "i": ("int", int),
    "bool": ("bool", parse_bool),
    "b": ("bool", parse_bool),
}
"""Map from value type to (name, parser) tuple."""


# ==============================================================================
# Commands

class TestVRCOSCCommand(JSTVCommand):
    key = "core.feliz.vrcosc"
    title = "Test VRChat OSC"
    description = "Send a OSC parameter to VRChat"
    tags = frozenset({HandlerTags.hidden})

    settings = JSTVCommandSettings(
        aliases = ("testvrcosc", "vrcosc",),
        min_access_level=AccessLevel.streamer,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return f"Usage: {alias} <address> <type> <value>"

    @classmethod
    async def handle(cls, ctx) -> bool:
        vrc = ctx.connector_manager.get(VRChatConnector)
        if not vrc:
            await ctx.reply("VRChat not connected")
            return False

        address, _, argument = ctx.argument.partition(" ")
        address = address.strip()
        if not address:
            await cls.reply_usage(ctx)
            return False

        value_type, _, argument = argument.partition(" ")
        value_type = value_type.strip()
        if not value_type:
            await cls.reply_usage(ctx)
            return False

        value_raw, _, argument = argument.partition(" ")
        value_raw = value_raw.strip()
        if not value_raw:
            await cls.reply_usage(ctx)
            return False

        value_type_name, value_parser = VALUE_PARSERS.get(value_type, (None, None))
        if not value_parser:
            await ctx.reply((
                f"Invalid value type: {value_type!r}"
                f"; valid types: {', '.join(VALUE_PARSERS)}"
            ), mention=True)
            return False

        try:
            value = value_parser(value_raw)
        except ValueError as e:
            await ctx.reply(f"Value parsing error: {e}", mention=True)
            return False

        address_full = address
        if not address_full.startswith("/"):
            address_full = f"/avatar/parameters/{address_full}"

        await vrc.sendosc(address_full, value)

        await ctx.reply(f"Sent OSC: {address_full} {value_type_name} {value}")
        return True
