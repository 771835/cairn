# coding=utf-8
import shutil
from pathlib import Path

from cairn.core.parser.base import ParseResult
from cairn.plugins.api import ActionPlugin
from cairn.plugins.registry import ActionRegistry
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class MoveAction(ActionPlugin):
    name = "move"
    dsl_keyword = "move"

    def execute(self, result: ParseResult, args: list[str]):
        if not args:
            logger.warning("move 指令缺少目标路径")
            return
        dest = Path(args[0]) / result.filename
        Path(args[0]).mkdir(parents=True, exist_ok=True)
        shutil.move(str(result.raw_path), str(dest))
        logger.info(f"已移动：{result.filename} → {args[0]}")
        result.raw_path = dest


class StoreAction(ActionPlugin):
    """store 指令：将文件入库（哈希存储 + 索引写入）"""
    name = "store"
    dsl_keyword = "store"

    def execute(self, result: ParseResult, args: list[str]):
        from cairn.core.store import FileStore
        from cairn.core.index.manager import IndexManager

        for tag in args:
            if tag not in result.tags:
                result.tags.append(tag)

        # 保留原始信息，入库前记录
        original_filename = result.filename
        original_path = result.raw_path

        store = FileStore()
        store_path, file_hash = store.store(result.raw_path)

        # 更新路径和哈希，但 filename 保持原始文件名
        result.raw_path = store_path
        result.file_hash = file_hash
        result.metadata["origin_path"] = str(original_path)
        result.metadata["origin_filename"] = original_filename

        IndexManager().index_file(result, original_path=original_path)

        logger.info(
            f"已入库：{original_filename} | "
            f"哈希：{file_hash[:12]}... | "
            f"标签：{result.tags}"
        )
class TagAction(ActionPlugin):
    name = "tag"
    dsl_keyword = "tag"

    def execute(self, result: ParseResult, args: list[str]):
        for t in args:
            if t not in result.tags:
                result.tags.append(t)
        logger.debug(f"已打标签：{args} → {result.filename}")


class IndexAction(ActionPlugin):
    """单独索引，不移动文件（用于已在知识库内的文件）"""
    name = "index"
    dsl_keyword = "index"

    def execute(self, result: ParseResult, args: list[str]):
        from cairn.core.index.manager import IndexManager
        IndexManager().index_file(result)


def register_builtin_actions():
    """将所有内置动作注册"""
    for action in (StoreAction(), MoveAction(), TagAction(), IndexAction()):
        ActionRegistry.register(action)
    logger.debug("内置动作已注册")