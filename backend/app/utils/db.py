from typing import Any

from sqlalchemy import select, inspect
from sqlalchemy.orm import relationship as sa_relationship
from sqlalchemy.ext.asyncio import AsyncSession

def relationship(*args, **kwargs):
    """SQLAlchemy relationship with lazy="select" by default."""
    kwargs.setdefault("lazy", "select")
    return sa_relationship(*args, **kwargs)

async def async_lazy(session: AsyncSession, obj, rel_name: str) -> Any:
    """
    Async-safe “lazy loader” for one-to-one relationships.

    - Checks if the relationship is loaded
    - If not, queries the database explicitly
    - Returns the related object (or None)
    """
    state = inspect(obj)

    # Already loaded? Return cached value
    if rel_name not in state.unloaded:
        return state.attrs[rel_name].loaded_value

    # Not loaded, manually query using foreign key
    rel_prop = getattr(type(obj), rel_name).property

    if rel_prop.uselist:
        raise NotImplementedError("Only supports one-to-one relationships for now")

    target_cls = rel_prop.mapper.class_
    local_col = list(rel_prop.local_columns)[0]
    target_id = getattr(obj, local_col.name)

    if target_id is None:
        return None

    # remote_side is a set; get the single element
    remote_col = next(iter(rel_prop.remote_side))

    # Async query the related object
    related_obj = await session.scalar(
        select(target_cls).filter(getattr(target_cls, remote_col.name) == target_id)
    )

    # Cache it on the object
    setattr(obj, rel_name, related_obj)
    return related_obj
