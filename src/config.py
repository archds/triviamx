
from pathlib import Path

from litestar.channels import ChannelsPlugin
from litestar.channels.backends.memory import MemoryChannelsBackend
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.template.config import TemplateConfig

CWD = Path(__file__).parent
ASSETS_DIR = CWD / "assets"
AVATARS_DIR = ASSETS_DIR / "avatars"
STORE_PATH = CWD / "store"

template_config = TemplateConfig(
    directory=CWD / "templates",
    engine=JinjaTemplateEngine,
)
session_config = ServerSideSessionConfig()
channels_plugin = ChannelsPlugin(
    backend=MemoryChannelsBackend(),
    arbitrary_channels_allowed=True,
    create_ws_route_handlers=True,
)
