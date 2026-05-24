# coding=utf-8
import json
from pathlib import Path
from dataclasses import dataclass

CONFIG_PATH = Path("config/settings.json")


@dataclass
class NotifyConfig:
    batch_window_ms: int = 2000
    silent_threshold: int = 5


@dataclass
class OverlayConfig:
    edge: str = "right"
    size_ratio: float = 0.4
    width: int = 24


@dataclass
class AppConfig:
    store_root: Path
    overlay: OverlayConfig
    notify: NotifyConfig
    parse_timeout: int
    hotkey: str
    log_level: str
    dev_mode: bool

    @classmethod
    def load(cls) -> "AppConfig":
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return cls(
            store_root=Path(raw["store_root"]),
            overlay=OverlayConfig(**raw.get("overlay", {})),
            notify=NotifyConfig(**raw.get("notify", {})),
            parse_timeout=raw.get("parse_timeout", 30),
            hotkey=raw.get("hotkey", "control+shift+space"),
            log_level=raw.get("log_level", "INFO"),
            dev_mode=raw.get("dev_mode", False),
        )


# 全局单例，其他模块直接 import
config = AppConfig.load()