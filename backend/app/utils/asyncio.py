from typing import Any

import asyncio


# ==============================================================================
# Async Utils

async def async_select(*tasks: asyncio.Task[Any]) -> set[asyncio.Task[Any]]:
    """
    Wait until one of the given asyncio Tasks completes, like Go's `select` statement.
    Returns the set of completed tasks and cancels the rest.
    """
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()

    # for task in pending:
    #     try:
    #         await task
    #     except asyncio.CancelledError:
    #         pass

    # assert done, "Expected at least one task to complete"
    return done
