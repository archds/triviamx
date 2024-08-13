import asyncio
import datetime
import html
from pathlib import Path
import random
from typing import Annotated
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
import pydantic
import utils
from api import OpenTriviaDB, OpenTriviaQuestion, get_open_trivia_db
import config

session_config = ServerSideSessionConfig()


def on_startup():
    config.ASSETS_DIR.mkdir(exist_ok=True)


class SessionAnswerEntry(pydantic.BaseModel):
    text: str
    button_class: str


class SessionQuestion(pydantic.BaseModel):
    text: str
    correct_answer: str
    incorrect_answers: list[str]
    guess: str | None = None

    @pydantic.computed_field
    def answers(self) -> list[SessionAnswerEntry]:
        rnd = random.Random(self.text)
        answ = self.incorrect_answers + [self.correct_answer]
        rnd.shuffle(answ)
        return [
            SessionAnswerEntry(text=ans, button_class=self.get_button_class(ans))
            for ans in answ
        ]

    def get_button_class(self, button_text: str) -> str:
        default_class = "button"

        if button_text == self.correct_answer and self.guess == self.correct_answer:
            return default_class + " success bounce"
        if button_text == self.correct_answer and self.guess:
            return default_class + " success"
        if button_text != self.correct_answer and button_text == self.guess:
            return default_class + " error shake"
        if button_text != self.correct_answer and self.guess:
            return default_class + " error"

        return default_class


class SessionState(pydantic.BaseModel):
    question: SessionQuestion
    get_at: datetime.datetime = pydantic.Field(default_factory=datetime.datetime.now)
    answers_url: str = "/answers"
    avatar: utils.Avatar


@litestar.get("/")
async def index(request: litestar.Request, trivia_db: OpenTriviaDB) -> Template:
    result = await trivia_db.get(amount=1)
    question = result[0]

    session_data = SessionState(
        question=SessionQuestion(
            text=question.text,
            correct_answer=question.correct_answer,
            incorrect_answers=question.incorrect_answers,
        ),
        avatar=utils.get_avatar(request.get_session_id()),
    )
    request.set_session(session_data)

    return HTMXTemplate(template_name="index.html", context=session_data.model_dump())


@litestar.get("/answers")
async def answers(request: HTMXRequest, guess: str) -> Template:
    session = SessionState.model_validate(request.session)
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
        session = SessionState(**request.session)
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
