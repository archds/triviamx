
from pathlib import Path

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

