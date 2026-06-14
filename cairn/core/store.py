# coding=utf-8
import hashlib
import os
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
            if dest.stat().st_size != source.stat().st_size:
                logger.error(
                    f"哈希异常：{source.name} 与已存文件大小不符，"
                    f"哈希={file_hash[:12]}，跳过入库，"
                    f"热知识，这种情况出现的可能性为2⁻¹²⁸哦"
                )
                # 不删源文件，抛出异常让 dispatcher 处理
                raise ValueError(f"哈希相同但文件大小不符：{source.name}")
            else:
                if config.safe_mode and self._hash_file(dest) != file_hash:
                    logger.error(f"哈希冲突或存储损坏：{file_hash[:12]}...，源文件保留")
                    raise ValueError(f"哈希冲突或存储损坏：{source.name}")
                logger.debug(f"去重：{source.name} → 已存在 {file_hash[:12]}...")
                source.unlink(missing_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(source, 0o600)
                shutil.move(str(source), str(dest))
                os.chmod(dest, 0o400)
                logger.info(f"已入库：{source.name} → {file_hash[:12]}...")
            except OSError as e:
                logger.error(f"文件入库错误：{e}")

        return dest, file_hash

    def remove(self, file_hash: str) -> bool:
        """安全删除存储文件，自动处理只读权限。返回是否成功删除。"""
        path = self._hash_to_path(file_hash)
        if not path.exists():
            return False
        try:
            os.chmod(path, 0o600)
            path.unlink()
            try:
                path.parent.rmdir()  # 目录为空时才会成功，非空自动抛出 OSError 被忽略
            except OSError:
                pass
            logger.info(f"已从库中移除：{file_hash[:12]}...")
            return True
        except OSError as e:
            logger.error(f"删除失败：{file_hash[:12]}... — {e}")
            return False

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
