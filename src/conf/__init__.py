"""集中管理环境变量与项目路径。"""

from conf.settings import Settings, get_settings, project_root

__version__ = "0.1.0"

__all__ = ["Settings", "get_settings", "project_root", "__version__"]
