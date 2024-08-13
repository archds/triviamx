import html
from pathlib import Path
import random
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
import pydantic

from api import OpenTriviaDB, OpenTriviaQuestion, get_open_trivia_db

CWD = Path(__file__).parent
session_config = ServerSideSessionConfig()

class SessionData(pydantic.BaseModel):
    question: OpenTriviaQuestion
    

@litestar.get("/")
async def index(request: litestar.Request, trivia_db: OpenTriviaDB) -> Template:
    result = await trivia_db.get(amount=1)
    question = result[0]
    answers = question.incorrect_answers + [question.correct_answer]
    random.shuffle(answers)

    request.set_session(SessionData(question=question))

    return HTMXTemplate(
        template_name="index.html",
        context={
            "question": html.unescape(question.question),
            "answers": [html.unescape(a) for a in answers],
            "answer_url": "/answer",
            "answer_given": False,
        },
    )



@litestar.get("/answer")
async def answer(request: HTMXRequest, answer: str) -> Template:
    session = SessionData(**request.session)
    from devtools import debug
    debug(session)
    is_correct = session.question.correct_answer == answer

    return HTMXTemplate(
        template_name="answer.html",
        context={
            "answer": answer,
            "highlight": "success" if is_correct else "error shake",
            "answer_url": "/answer",
            "answer_given": True,
        },
        re_swap="outerHTML",
    )


@litestar.get("/redirect-to")
async def redirect_to(request: HTMXRequest, to: str) -> HXLocation:
    return HXLocation(redirect_to=to, swap="outerHTML")


app = litestar.Litestar(
    route_handlers=[index, answer, redirect_to],
    csrf_config=CSRFConfig(secret="test-secret"),
    compression_config=CompressionConfig(backend="gzip"),
    template_config=TemplateConfig(
        directory=CWD / "templates", engine=JinjaTemplateEngine
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
    stores={"sessions": FileStore(path=CWD / "sessions")},
    dependencies={
        "trivia_db": litestar.di.Provide(get_open_trivia_db),
    },
)
