"""面板图/背景图网页编辑器。

启用方式: 配置 WavesPanelEditPassword (HTTP Basic Auth 密码), 然后访问
/waves/panel-edit/。模块导入即注册路由, 不依赖额外 startup hook。
"""

from gsuid_core.config import CONFIG_DEFAULT, core_config
from gsuid_core.logger import logger

from . import routes  # noqa: F401
from .auth import is_enabled


def _log_url_banner() -> None:
    host = core_config.get_config("HOST") or CONFIG_DEFAULT.get("HOST")
    port = core_config.get_config("PORT") or CONFIG_DEFAULT.get("PORT")
    display_host = "127.0.0.1" if host in (None, "", "0.0.0.0") else host
    base = f"http://{display_host}:{port}/waves/panel-edit/"
    if is_enabled():
        logger.success(f"[鸣潮·面板编辑] 已启用, 访问 {base} (HTTP Basic Auth: 用户名 admin)")
    else:
        logger.info(
            f"[鸣潮·面板编辑] 未启用 — 访问 {base} 仅显示提示页, "
            "在 WutheringWavesConfig 中设置 WavesPanelEditPassword 后即可启用"
        )


_log_url_banner()
