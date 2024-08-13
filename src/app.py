from litestar import Litestar, get


@get("/")
async def index() -> str:
    return "Hello, world!"


app = Litestar(route_handlers=[index])