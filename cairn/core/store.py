# coding=utf-8
import hashlib
import shutil
from pathlib import Path

from cairn.core.config import config
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class FileStore:
    """
    文件物理存储管理。
    职责：把文件按内容哈希存入 store_root，天然去重。

    目录结构：
        {store_root}/
            ab/
                abcdef1234567890...  （文件内容，无扩展名）
            cd/
                cdabef...
    """

    def __init__(self):
        self._root = config.store_root
        self._root.mkdir(parents=True, exist_ok=True)

    def store(self, source: Path) -> tuple[Path, str]:
        """
        将文件存入哈希目录。
        - 已存在（相同哈希）：跳过复制，直接返回已有路径（去重）
        - 不存在：移动文件到哈希路径

        返回 (store_path, file_hash)
        """
        file_hash = self._hash_file(source)
        dest = self._hash_to_path(file_hash)

        if dest.exists():
            # 内容完全相同，去重，删除源文件
            logger.debug(f"去重：{source.name} → 已存在 {file_hash[:12]}...")
            source.unlink(missing_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
            logger.info(f"已入库：{source.name} → {file_hash[:12]}...")

        return dest, file_hash

    def get_path(self, file_hash: str) -> Path | None:
        """根据哈希值取回文件路径，不存在返回 None"""
        path = self._hash_to_path(file_hash)
        return path if path.exists() else None

    def _hash_to_path(self, file_hash: str) -> Path:
        """哈希前两位作为子目录，其余作为文件名"""
        return self._root / file_hash[:2] / file_hash

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()