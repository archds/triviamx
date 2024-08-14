import asyncio
import datetime
import random
import uuid
import litestar
from litestar.config.csrf import CSRFConfig
from litestar.config.compression import CompressionConfig
import litestar.di
import litestar.status_codes
from litestar.template.config import TemplateConfig
from litestar.response import Template
from litestar.contrib.htmx.response import HTMXTemplate, HXLocation, ClientRedirect
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.logging import LoggingConfig
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.stores.file import FileStore
from litestar.contrib.htmx.request import HTMXRequest
from litestar.static_files import create_static_files_router
from litestar.response import Redirect
import pydantic
import state
from api import OpenTriviaDB, get_open_trivia_db
import config
import utils

session_config = ServerSideSessionConfig()
template_config = TemplateConfig(
    directory=config.CWD / "templates", engine=JinjaTemplateEngine
)


class ClientSessionData(pydantic.BaseModel):
    player_session_id: str
    game_session: state.GameSession


class ClientSessionMessage(pydantic.BaseModel):
    guess: str


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
    session_manager: state.GameSessionManager,
) -> Template:
    player_session_id = request.get_session_id()
    assert player_session_id
    game_session = await session_manager.get_session(game_session_id)
    data = ClientSessionData(
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


@litestar.websocket_listener("/ws", send_mode="text")
async def ws(
    data: dict[str, str],
    socket: litestar.WebSocket,
    game_session_id: uuid.UUID,
    session_manager: state.GameSessionManager,
) -> str:
    msg = ClientSessionMessage.model_validate(data)
    player_session_id = socket.get_session_id()
    assert player_session_id
    game_session = await session_manager.get_session(game_session_id)    
    
    await session_manager.set_player_guess(
        session_id=game_session_id,
        player_session_id=player_session_id,
        guess=msg.guess,
    )
    ctx = ClientSessionData(
        player_session_id=player_session_id,
        game_session=game_session,
    )

    template = template_config.engine_instance.get_template("answers.html")

    return template.render(**ctx.model_dump())


app = litestar.Litestar(
    route_handlers=[
        index,
        redirect_to,
        ws,
        room,
        create_static_files_router(path="/static", directories=[config.ASSETS_DIR]),
    ],
    csrf_config=CSRFConfig(secret="test-secret"),
    compression_config=CompressionConfig(backend="gzip"),
    template_config=template_config,
    logging_config=LoggingConfig(
        root={"level": "INFO", "handlers": ["queue_listener"]},
        formatters={
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        log_exceptions="always",
    ),
    middleware=[session_config.middleware],
    stores={"sessions": FileStore(path=config.STORE_PATH / "client_sessions")},
    dependencies={
        "trivia_db": litestar.di.Provide(get_open_trivia_db),
        "session_manager": litestar.di.Provide(
            state.GameSessionManager,
            use_cache=True,
            sync_to_thread=True,
        ),
    },
    on_startup=[on_startup],
)
