import asyncio
import datetime
import litestar
from litestar.config.csrf import CSRFConfig
from litestar.config.compression import CompressionConfig
import litestar.di
from litestar.template.config import TemplateConfig
from litestar.response import Template
from litestar.contrib.htmx.response import HTMXTemplate, HXLocation
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.logging import LoggingConfig
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.stores.file import FileStore
from litestar.contrib.htmx.request import HTMXRequest
from litestar.static_files import create_static_files_router
import state
from api import OpenTriviaDB, get_open_trivia_db
import config

session_config = ServerSideSessionConfig()


def on_startup():
    config.ASSETS_DIR.mkdir(exist_ok=True)


@litestar.get("/")
async def index(request: litestar.Request, trivia_db: OpenTriviaDB) -> Template:
    result = await trivia_db.get(amount=1)
    question = result[0]
    session_id = request.get_session_id()
    assert session_id

    session_data = state.GameState(
        question=state.GameQuestion(
            text=question.text,
            correct_answer=question.correct_answer,
            incorrect_answers=question.incorrect_answers,
        ),
    )
    request.set_session(session_data)

    return HTMXTemplate(template_name="index.html", context=session_data.model_dump())


@litestar.get("/answers")
async def answers(request: HTMXRequest, guess: str) -> Template:
    session = state.GameState.model_validate(request.session)
    session.question.guess = guess

    return HTMXTemplate(
        template_name="answers.html",
        context=session.model_dump(),
        re_swap="outerHTML",
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


@litestar.websocket_listener("/gameroom")
async def gameroom(data: dict[str, str], socket: litestar.WebSocket) -> None:
    pass


app = litestar.Litestar(
    route_handlers=[
        index,
        answers,
        redirect_to,
        gameroom,
        create_static_files_router(path="/static", directories=[config.ASSETS_DIR]),
    ],
    csrf_config=CSRFConfig(secret="test-secret"),
    compression_config=CompressionConfig(backend="gzip"),
    template_config=TemplateConfig(
        directory=config.CWD / "templates", engine=JinjaTemplateEngine
    ),
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
    stores={"sessions": FileStore(path=config.CWD / "sessions")},
    dependencies={
        "trivia_db": litestar.di.Provide(get_open_trivia_db),
    },
    on_startup=[on_startup],
)
