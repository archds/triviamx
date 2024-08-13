import litestar
from litestar.config.csrf import CSRFConfig


@litestar.get("/")
async def index() -> str:
    return "Hello, world!"


app = litestar.Litestar(
    route_handlers=[index], csrf_config=CSRFConfig(secret="test-secret")
)
