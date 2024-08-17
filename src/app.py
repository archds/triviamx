import uuid

import config
import litestar
import litestar.di
import litestar.events
import litestar.handlers
import litestar.status_codes
import session
import utils
from api import get_open_trivia_db
from litestar.config.compression import CompressionConfig
from litestar.config.csrf import CSRFConfig
from litestar.contrib.htmx.response import HTMXTemplate
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
    session_manager: session.GameSessionManager,
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
    session_manager: session.GameSessionManager,
) -> Template | Redirect:
    game_session = await session_manager.get_session(game_session_id)

    if not game_session:
        return Redirect(path="/")

    data = session.ClientData(
        player_session_id=player_session_id,
        game_session=game_session,
    )

    request.set_session(data.model_dump())

    return HTMXTemplate(
        template_name="index.html",
        context=data.model_dump(),
        push_url=f"/{game_session.id}",
    )


app = litestar.Litestar(
    route_handlers=[
        index,
        room,
        create_static_files_router(path="/static", directories=[config.ASSETS_DIR]),
        session.GameWebsocketListener,
    ],
    csrf_config=CSRFConfig(secret="test-secret"),
    compression_config=CompressionConfig(backend="gzip"),
    template_config=config.template_config,
    logging_config=LoggingConfig(
        root={"level": "INFO", "handlers": ["queue_listener"]},
        formatters={
            "standard": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"}
        },
        log_exceptions="always",
    ),
    middleware=[config.session_config.middleware],
    stores={"sessions": FileStore(path=config.STORE_PATH / "client_sessions")},
    dependencies={
        "trivia_db": litestar.di.Provide(get_open_trivia_db),
        "session_manager": litestar.di.Provide(
            session.GameSessionManager,
            use_cache=True,
            sync_to_thread=True,
        ),
        "player_session_id": litestar.di.Provide(utils.get_player_session_id),
        "template_engine": litestar.di.Provide(utils.get_template_engine),
    },
    on_startup=[on_startup],
    # listeners=session.LISTENERS,
    websocket_class=session.GameWebsocket,
    plugins=[config.channels_plugin]
)
