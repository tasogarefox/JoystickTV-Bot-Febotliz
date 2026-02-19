import enum


# ==============================================================================
# Enums

class CommandAccessLevel(enum.IntEnum):
    viewer = 0
    verified = 10
    follower = 20
    verified_follower = 30
    subscriber = 50
    vip = 70
    moderator = 80
    broadcaster = 100
