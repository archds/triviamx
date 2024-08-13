import litestar
from litestar.config.csrf import CSRFConfig
from litestar.config.compression import CompressionConfig
from litestar.template.config import TemplateConfig


@litestar.get("/")
async def index() -> str:
    return "Hello, world!"


app = litestar.Litestar(
    route_handlers=[index],
    csrf_config=CSRFConfig(secret="test-secret"),
    compression_config=CompressionConfig(backend="gzip"),
    template_config=TemplateConfig(directory="templates", engine="jinja2"),
)
