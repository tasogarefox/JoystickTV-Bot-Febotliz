import enum


# ==============================================================================
# Enums

class CommandAccessLevel(enum.IntEnum):
    viewer = 0
    follower = 10
    subscriber = 20
    vip = 30
    moderator = 40
    broadcaster = 50
