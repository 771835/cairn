# coding=utf-8
import json
import os
from pathlib import Path

from cairn.core.config import config
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class PluginLoader:
    """
    插件加载器。
    扫描指定目录下所有子目录，
    读取 plugin.json 声明，动态加载插件类。
    """

    def __init__(self):
        self.plugins_dir = Path(config.plugins.dir)
        self.plugins_locals: dict[str, dict] = {}

    def load_all(self):
        if not self.plugins_dir.exists():
            logger.warning(f"插件目录不存在：{self.plugins_dir}")
            return

        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest = plugin_dir / "plugin.json"
            if not manifest.exists():
                continue
            self._load_plugin(plugin_dir, manifest)

    def _load_plugin(self, plugin_dir: Path, manifest: Path):
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"插件声明解析失败 {manifest}：{e}")
            return

        # 基本校验
        required_keys = {"name", "version", "entry", "class"}
        if not required_keys.issubset(meta):
            logger.error(f"插件声明缺少必要字段：{manifest}")
            return

        # 配置级禁用优先于插件自身声明
        plugin_name = str(meta["name"])
        if plugin_name in config.plugins.disabled:
            logger.debug(f"插件已被配置禁用，跳过：{plugin_name}")
            return

        if not meta.get("enabled", True):
            logger.debug(f"插件已禁用，跳过：{meta['name']}")
            return

        # 加载插件
        plugin_name = str(meta["name"])
        entry = plugin_dir / str(meta["entry"])
        code = entry.read_text(encoding="utf-8")
        # 获得插件的作用域
        plugin_locals = self.plugins_locals.get(plugin_name, {})
        try:
            global_env: dict = dict()
            global_env.update(
                {
                    "__path__": str(plugin_dir.resolve()),
                    "__package__": str(plugin_dir.resolve().relative_to(Path.cwd())).replace(os.sep, "."),
                    "__name__": plugin_name,
                    "__file__": str((plugin_dir / str(meta["entry"])).resolve()),
                    "__plugin_name__": plugin_name
                }
            )
            # 执行代码
            exec(code, global_env, plugin_locals)
            global_env.update(plugin_locals)
            self.plugins_locals[plugin_name] = plugin_locals
            # 搜索入口类
            if plugin_main_class := plugin_locals.get(meta["class"], None):
                instance = plugin_main_class()
                is_validate, reason = instance.validate()
                if not is_validate:
                    logger.warning(f"Plugin '{plugin_name}' is invalid, reason: {reason}")
                instance.initialize()
                instance.load()
            else:
                logger.error(f"插件 '{meta['name']}' 中找不到类：{meta['class']}")
                return
        except Exception as e:
            logger.error(f"插件 '{meta['name']}' 加载失败：{e}")
            return

        logger.info(f"已加载插件：{meta['name']} v{meta['version']}")
