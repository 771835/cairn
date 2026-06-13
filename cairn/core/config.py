# coding=utf-8
import json
from pathlib import Path

from attrs import define, field

CONFIG_PATH = Path("config/settings.json")


@define(slots=True)
class NotifyConfig:
    batch_window_ms: int = 2000
    silent_threshold: int = 5
    info_duration_ms: int = 3000
    error_duration_ms: int = 4000


@define(slots=True)
class OverlayConfig:
    edge: str = "right"
    size_ratio: float = 0.4
    width: int = 24
    idle_alpha: int = 40
    hover_alpha: int = 180
    color: list[int] = field(factory=lambda: [100, 180, 255])
    border_radius: int = 6


@define(slots=True)
class DispatcherConfig:
    worker_threads: int = 8
    parse_threads: int = 4
    max_retry: int = 3
    retry_delay: float = 0.5


@define(slots=True)
class DbConfig:
    busy_timeout: int = 30
    journal_mode: str = "WAL"
    foreign_keys: bool = True


@define(slots=True)
class FolderConfig:
    auto_close_s: int = 5
    default_action: str = "expand"  # "expand" | "whole"


@define(slots=True)
class PluginsConfig:
    dir: str = "plugins"
    disabled: list[str] = field(factory=list)


@define(slots=True)
class AppConfig:
    store_root: Path
    db_path: Path
    overlay: OverlayConfig
    notify: NotifyConfig
    dispatcher: DispatcherConfig
    db: DbConfig
    folder: FolderConfig
    plugins: PluginsConfig
    parse_timeout: int
    hotkey: str
    log_level: str
    log_file: str
    dev_mode: bool

    @classmethod
    def load(cls) -> "AppConfig":
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return cls(
            store_root=Path(raw.get("store_root", "./.store")),
            db_path=Path(raw.get("db_path", "data/cairn.db")),
            overlay=OverlayConfig(**raw.get("overlay", {})),
            notify=NotifyConfig(**raw.get("notify", {})),
            dispatcher=DispatcherConfig(**raw.get("dispatcher", {})),
            db=DbConfig(**raw.get("db", {})),
            folder=FolderConfig(**raw.get("folder", {})),
            plugins=PluginsConfig(**raw.get("plugins", {})),
            parse_timeout=raw.get("parse_timeout", 30),
            hotkey=raw.get("hotkey", "control+shift+space"),
            log_level=raw.get("log_level", "INFO"),
            log_file=raw.get("log_file", "logs/cairn.log"),
            dev_mode=raw.get("dev_mode", False),
        )


# 全局单例，其他模块直接 import
config = AppConfig.load()
