# coding=utf-8
import logging
import sys
from pathlib import Path

from cairn.core.config import config

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S"
    )

    # 终端输出（INFO 及以上）
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(config.log_level)
    sh.setFormatter(fmt)

    # 文件输出（DEBUG 及以上）
    fh = logging.FileHandler(LOG_DIR / "cairn.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(sh)
    logger.addHandler(fh)

    return logger