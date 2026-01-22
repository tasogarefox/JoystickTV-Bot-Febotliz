from typing import Optional, Any
import os

from ..connector import ConnectorMessage, ConnectorManager, WebSocketConnector


# ==============================================================================
# Config

WS_HOST = os.getenv("WARUDO_WS_HOST")
assert WS_HOST, "Missing environment variable: WARUDO_WS_HOST"

NAME = "Warudo"
URL = WS_HOST


# ==============================================================================
# Quirky Animals Map

QUIRKY_ANIMALS_MAP: dict[str, str] = {
    "Arctic Fox": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/ArcticFox",
    "Ox": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/Ox",
    "Penguin": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/Penguin",
    "Polar Bear": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/PolarBear",
    "Reindeer": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/Reindeer",
    "Sea Lion": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/SeaLion",
    "Snow Owl": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/SnowOwl",
    "Snow Weasel": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/SnowWeasel",
    "Walrus": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Arctic Vol.1/Prefabs/Walrus",
    "Buffalo": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Buffalo",
    "Chick": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Chick",
    "Cow": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Cow",
    "Donkey": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Donkey",
    "Duck": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Duck",
    "Hen": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Hen",
    "Pig": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Pig",
    "Rooster": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Rooster",
    "Sheep": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Farm Vol.1/Prefabs/Sheep",
    "Crow": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Crow",
    "Eagle": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Eagle",
    "Fox": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Fox",
    "Hog": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Hog",
    "Hornbill": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Hornbill",
    "Owl": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Owl",
    "Raccoon": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Raccoon",
    "Snake": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Snake",
    "Wolf": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Forest Vol.1/Prefabs/Wolf",
    "Cat": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Cat",
    "Dog": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Dog",
    "Dove": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Dove",
    "Goldfish": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Goldfish",
    "Mouse": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Mouse",
    "Parrot": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Parrot",
    "Pigeon": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Pigeon",
    "Rabbit": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Rabbit",
    "Tortoise": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Pets Vol.1/Prefabs/Tortoise",
    "Cheetah": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Cheetah",
    "Elephant": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Elephant",
    "Flamingo": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Flamingo",
    "Gazelle": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Gazelle",
    "Hippo": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Hippo",
    "Hyena": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Hyena",
    "Ostrich": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Ostrich",
    "Rhino": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Rhino",
    "Zebra": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.1/Safari Vol.1/Prefabs/Zebra",
    "Armadillo": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/Armadillo",
    "Bighorn": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/Bighorn",
    "Camel": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/Camel",
    "Coyote": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/Coyote",
    "Gila Monster": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/GilaMonster",
    "Golden Eagle": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/GoldenEagle",
    "Horned Lizard": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/HornedLizard",
    "Pronghorn": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/Pronghorn",
    "Rattlesnake": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Desert Vol.1/Prefabs/Rattlesnake",
    "Emu": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/Emu",
    "Kangaroo": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/Kangaroo",
    "Koala": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/Koala",
    "Kookaburra": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/Kookaburra",
    "Platypus": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/Platypus",
    "Possum": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/Possum",
    "Quokka": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/Quokka",
    "Tasmanian Devil": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/TasmanianDevil",
    "Wombat": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Island Vol.1/Prefabs/Wombat",
    "Bat": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/Bat",
    "Cobra": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/Cobra",
    "Gorilla": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/Gorilla",
    "Panda": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/Panda",
    "Peacock": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/Peacock",
    "Red Panda": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/RedPanda",
    "Sloth": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/Sloth",
    "Tapir": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/Tapir",
    "Tiger": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Jungle Vol.1/Prefabs/Tiger",
    "Arowana": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/Arowana",
    "Beaver": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/Beaver",
    "Carp": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/Carp",
    "Crocodile": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/Crocodile",
    "Frog": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/Frog",
    "Kingfisher": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/Kingfisher",
    "Manatee": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/Manatee",
    "Snapping Turtle": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/SnappingTurtle",
    "Swan": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/River Vol.1/Prefabs/Swan",
    "Clownfish": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/Clownfish",
    "Crab": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/Crab",
    "Dolphin": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/Dolphin",
    "Lobster": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/Lobster",
    "Orca": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/Orca",
    "Pelican": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/Pelican",
    "Sea Horse": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/SeaHorse",
    "Sea Otter": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/SeaOtter",
    "Squid": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.2/Sea Vol.1/Prefabs/Squid",
    "Beluga": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/Beluga",
    "Cougar": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/Cougar",
    "Hare": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/Hare",
    "Husky": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/Husky",
    "Lynx": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/Lynx",
    "Moose": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/Moose",
    "Narwhal": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/Narwhal",
    "Puffin": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/Puffin",
    "Snow Leopard": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Arctic Vol.2/Prefabs/SnowLeopard",
    "Alpaca": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Alpaca",
    "Bull": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Bull",
    "Goat": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Goat",
    "Goose": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Goose",
    "Horse": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Horse",
    "Lamb": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Lamb",
    "Llama": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Llama",
    "Mallard": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Mallard",
    "Turkey": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Farm Vol.2/Prefabs/Turkey",
    "Badger": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Badger",
    "Bear": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Bear",
    "Cardinal": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Cardinal",
    "Deer": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Deer",
    "Lemur": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Lemur",
    "Marten": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Marten",
    "Mole": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Mole",
    "Skunk": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Skunk",
    "Toucan": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Forest Vol.2/Prefabs/Toucan",
    "Chameleon": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Chameleon",
    "Chipmunk": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Chipmunk",
    "Ferret": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Ferret",
    "Hamster": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Hamster",
    "Hedgehog": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Hedgehog",
    "Iguana": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Iguana",
    "Monkey": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Monkey",
    "Python": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Python",
    "Squirrel": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Pets Vol.2/Prefabs/Squirrel",
    "Antelope": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Antelope",
    "Baboon": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Baboon",
    "Bison": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Bison",
    "Giraffe": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Giraffe",
    "Jackal": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Jackal",
    "Lion": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Lion",
    "Lioness": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Lioness",
    "Serval": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Serval",
    "Wildebeest": "gameobject://resources/Props/Quirky Series Ultimate/Quirky Series Vol.3/Safari Vol.2/Prefabs/Wildebeest",
}


# ==============================================================================
# Warudo Connector

class WarudoConnector(WebSocketConnector):
    def __init__(self, manager: ConnectorManager, name: Optional[str] = None, url: Optional[str] = None):
        super().__init__(manager, name or NAME, url or URL)

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        if await super().talk_receive(msg):
            return True

        if msg.action == "action":
            await self.sendnow(msg.data)
            return True

        return False

    async def on_message(self, data: dict[Any, Any]):
        self.logger.info("Received: %s", data)
