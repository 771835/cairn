# coding=utf-8
import os
import subprocess
import sys

from PySide6.QtWidgets import QLabel

from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


def open_file(dto: FileDTO, status: QLabel | None = None) -> None:
    """用系统默认程序打开文件。"""
    store_path = IndexManager().get_store_path(dto.file_hash)
    path = store_path if store_path and store_path.exists() else None

    if path is None:
        msg = f"文件不存在：{dto.filename}"
        logger.warning(msg)
        if status:
            status.setText(msg)
        return

    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.run(["xdg-open", str(path)])
