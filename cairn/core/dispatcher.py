# coding=utf-8
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from cairn.core.config import config
from cairn.core.index.manager import IndexManager
from cairn.core.parser.base import ParseResult
from cairn.core.parser.manager import ParserManager
from cairn.core.rule_engine.engine import RuleEngine
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class FileEventDispatcher(QObject):
    process_done = Signal(str)
    process_error = Signal(str)

    def __init__(self):
        super().__init__()
        self._parser_manager = ParserManager()
        self._rule_engine = RuleEngine()

        cfg = config.dispatcher
        self._parse_timeout = cfg.max_retry and config.parse_timeout
        self._max_retry = cfg.max_retry
        self._retry_delay = cfg.retry_delay

        self._executor = ThreadPoolExecutor(max_workers=cfg.worker_threads)
        self._parse_executor = ThreadPoolExecutor(max_workers=cfg.parse_threads)

    def dispatch(self, file_paths: list[Path]):
        for path in file_paths:
            self._executor.submit(self._process_file, path)

    def dispatch_folder_expand(self, folder_path: Path):
        files = [f for f in folder_path.rglob("*") if f.is_file()]
        logger.info(f"展开文件夹：{folder_path.name}，共 {len(files)} 个文件")
        for f in files:
            self._executor.submit(self._process_file, f)

    def dispatch_folder_whole(self, folder_path: Path):
        self._executor.submit(self._process_folder_whole, folder_path)

    def _process_file(self, file_path: Path):
        logger.info(f"开始处理：{file_path.name}")
        try:
            # 解析用独立线程池，避免嵌套死锁
            future = self._parse_executor.submit(
                self._parser_manager.parse, file_path
            )
            try:
                result = future.result(timeout=self._parse_timeout)
            except TimeoutError:
                logger.warning(f"解析超时，降级：{file_path.name}")
                result = self._parser_manager.fallback(file_path)

            matched = self._rule_engine.process(result)

            if matched:
                msg = f"已处理：{file_path.name}\n命中规则：{', '.join(matched)}"
            else:
                msg = f"已处理：{file_path.name}（无匹配规则）"

            self.process_done.emit(msg)

        except Exception as e:
            logger.exception(f"处理失败：{file_path.name}")
            self.process_error.emit(f"处理失败：{file_path.name}\n{e}")

    def _process_folder_whole(self, folder_path: Path) -> None:
        """整体索引模式：递归处理每个文件，文件夹条目聚合子文件 id。"""
        files = [f for f in folder_path.rglob("*") if f.is_file()]
        logger.info(f"整体索引：{folder_path.name}，共 {len(files)} 个文件")

        child_ids: list[int] = []
        child_results: list[ParseResult] = []

        for f in files:
            try:
                future = self._parse_executor.submit(
                    self._parser_manager.parse, f
                )
                result = future.result(timeout=self._parse_timeout)
            except Exception:
                result = self._parser_manager.fallback(f)

            # 每个文件单独哈希入库
            try:
                from cairn.core.store import FileStore
                store = FileStore()
                store_path, file_hash = store.store(result.raw_path)
                original_path = result.raw_path
                result.raw_path = store_path
                result.file_hash = file_hash
                file_id = self._index_with_retry(
                    result, original_path=original_path
                )
                child_ids.append(file_id)
                child_results.append(result)
            except Exception as e:
                logger.error(f"子文件入库失败：{f.name} — {e}")

        # 建立文件夹聚合条目
        try:
            from cairn.core.index.manager import IndexManager
            IndexManager().index_folder_entry(
                folder_path, child_ids, child_results
            )
            self.process_done.emit(
                f"已整体索引：{folder_path.name}\n共 {len(child_ids)} 个文件"
            )
        except Exception as e:
            logger.exception(f"文件夹条目建立失败：{folder_path.name}")
            self.process_error.emit(f"文件夹索引失败：{folder_path.name}\n{e}")

    def _index_with_retry(
            self,
            result: ParseResult,
            original_path: Path | None = None,
    ) -> int | None:
        """
        写入索引，失败时自动重试。
        数据库锁（OperationalError）重试，其他错误直接放弃。
        """
        import sqlite3
        from sqlalchemy.exc import OperationalError

        delay = self._retry_delay
        for attempt in range(1, self._max_retry + 1):
            try:
                return IndexManager().index_file(result, original_path)
            except (OperationalError, sqlite3.OperationalError) as e:
                # 数据库繁忙/锁，等待后重试
                if attempt < self._max_retry:
                    logger.warning(
                        f"数据库繁忙，{delay:.1f}s 后重试"
                        f"（{attempt}/{self._max_retry}）：{result.filename}"
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(
                        f"写入失败，已重试 {self._max_retry} 次放弃："
                        f"{result.filename} — {e}"
                    )
                    return None
            except Exception as e:
                # 其他错误（UNIQUE 已在 index_file 内部处理）直接记录
                logger.error(f"写入失败：{result.filename} — {e}")
                return None
        return None
