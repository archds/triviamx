import asyncio
import datetime
import uuid

import config
import litestar
import litestar.di
import litestar.events
import litestar.handlers
import litestar.status_codes
import session
import state
import utils
from api import OpenTriviaDB, get_open_trivia_db
from litestar.config.compression import CompressionConfig
from litestar.config.csrf import CSRFConfig
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, HXLocation
from litestar.logging import LoggingConfig
from litestar.response import Redirect, Template
from litestar.static_files import create_static_files_router
from litestar.stores.file import FileStore


def on_startup():
    config.ASSETS_DIR.mkdir(exist_ok=True)
    config.STORE_PATH.mkdir(exist_ok=True)


@litestar.get("/", status_code=litestar.status_codes.HTTP_302_FOUND)
async def index(
    request: litestar.Request,
    session_manager: state.GameSessionManager,
) -> Redirect:
    session_id = request.get_session_id()
    assert session_id
    game_session = await session_manager.open_session(session_id)

    return Redirect(path=f"/game/{game_session.id}")


@litestar.get("/game/{game_session_id:str}")
async def room(
    request: litestar.Request,
    game_session_id: uuid.UUID,
    player_session_id: str,
    session_manager: state.GameSessionManager,
) -> Template | Redirect:
    game_session = await session_manager.get_session(game_session_id)

    if not game_session:
        return Redirect(path="/")

    data = session.ClientSessionData(
        player_session_id=player_session_id,
        game_session=game_session,
    )

    request.set_session(data.model_dump())

    return HTMXTemplate(
        template_name="index.html",
        context=data.model_dump(),
        push_url=f"/{game_session.id}",
    )


@litestar.get("/redirect-to")
async def redirect_to(
    request: HTMXRequest,
    to: str,
    wait_session_timeout: bool = False,
) -> HXLocation:
    if wait_session_timeout:
        session = state.GameState(**request.session)
        while (datetime.datetime.now() - session.get_at) < OpenTriviaDB.timeout:
            await asyncio.sleep(0.5)

    return HXLocation(redirect_to=to, swap="outerHTML")


app = litestar.Litestar(
    route_handlers=[
        index,
        redirect_to,
        room,
        create_static_files_router(path="/static", directories=[config.ASSETS_DIR]),
        session.GameSessionHandler,
    ],
    csrf_config=CSRFConfig(secret="test-secret"),
    compression_config=CompressionConfig(backend="gzip"),
    template_config=config.template_config,
    logging_config=LoggingConfig(
        root={"level": "INFO", "handlers": ["queue_listener"]},
        formatters={
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        log_exceptions="always",
    ),
    middleware=[config.session_config.middleware],
    stores={"sessions": FileStore(path=config.STORE_PATH / "client_sessions")},
    dependencies={
        "trivia_db": litestar.di.Provide(get_open_trivia_db),
        "session_manager": litestar.di.Provide(
            state.GameSessionManager,
            use_cache=True,
            sync_to_thread=True,
        ),
        "player_session_id": litestar.di.Provide(utils.get_player_session_id),
    },
    on_startup=[on_startup],
    listeners=[session.update_players],
)
