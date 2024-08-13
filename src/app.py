from pathlib import Path
import litestar
from litestar.config.csrf import CSRFConfig
from litestar.config.compression import CompressionConfig
from litestar.template.config import TemplateConfig
from litestar.response import Template
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.logging import LoggingConfig

CWD = Path(__file__).parent


@litestar.get("/")
async def index() -> Template:
    return HTMXTemplate(template_name="index.html", context={})


app = litestar.Litestar(
    route_handlers=[index],
    csrf_config=CSRFConfig(secret="test-secret"),
    compression_config=CompressionConfig(backend="gzip"),
    template_config=TemplateConfig(directory=CWD / "templates", engine=JinjaTemplateEngine),
    logging_config=LoggingConfig(
        root={"level": "INFO", "handlers": ["queue_listener"]},
        formatters={
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        log_exceptions="debug",
    ),
)
