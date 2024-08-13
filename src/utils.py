import random
from typing import Final
import pydantic

import config


class Avatar(pydantic.BaseModel):
    name: str
    url: str

AVATARS: Final = [
    Avatar(name=path.stem[4:], url=f"/static/avatars/{path.name}")
    for path in config.AVATARS_DIR.iterdir()
]


def get_avatar(session_id: str | None = None) -> Avatar:
    return random.choice(AVATARS)