import asyncio
import random
from functools import partial, wraps
from typing import Awaitable, Coroutine, Final

import config
import litestar
import pydantic


class Avatar(pydantic.BaseModel):
    name: str
    url: str


AVATARS: Final = [
    Avatar(name=path.stem[4:], url=f"/static/avatars/{path.name}")
    for path in config.AVATARS_DIR.iterdir()
]


def get_avatar(player_id: str | None = None) -> Avatar:
    return random.choice(AVATARS)


async def get_player_session_id(request: litestar.Request | litestar.WebSocket) -> str:
    session_id = request.get_session_id()

    if not session_id:
        raise ValueError("Session ID not found")

    return session_id


async def get_template_engine():
    return config.template_config.engine_instance


def create_delayed_task(coro: Coroutine, delay: int) -> asyncio.Task:
    async def _delayed() -> None:
        await asyncio.sleep(delay)
        await coro

    return asyncio.create_task(_delayed())


async def chain_awaitables(*awaitables: Awaitable):
    for a in awaitables:
        await a


def sync_to_async(func):
    @wraps(func)
    async def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = asyncio.get_event_loop()

        pfunc = partial(func, *args, **kwargs)

        return await loop.run_in_executor(executor, pfunc)

    return run
