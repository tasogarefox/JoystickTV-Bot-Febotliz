import enum


# ==============================================================================
# Enums

class AccessLevel(enum.IntEnum):
    """
    Command access level.

    NOTE: Some values are disabled because they cannot
          currently be tracked properly.
    """
    viewer = 0
    verified = 10
    # follower = 20
    # verified_follower = 30
    subscriber = 50
    # vip = 70
    moderator = 80
    streamer = 100
