import random
from typing import Final

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
