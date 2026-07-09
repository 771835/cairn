# coding=utf-8
import hashlib
from pathlib import Path

from cairn.core.parser.base import ParseResult
from cairn.plugins.api import BaseParser
from cairn.plugins.registry import ParserRegistry
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class ParserManager:
    """
    解析器路由器。
    根据文件扩展名找到对应的解析器插件并调用。
    所有解析器均通过插件系统注册，无硬编码。
    """

    def parse(self, file_path: Path) -> ParseResult:
        parser = self._find_parser(file_path)

        if parser:
            logger.debug(f"使用解析器 '{parser.__class__.__name__}' 处理 {file_path.name}")
            result = parser.parse(file_path)
        else:
            logger.debug(f"无匹配解析器，使用降级结果：{file_path.name}")
            result = self.fallback(file_path)

        # 补充 file_hash（所有路径统一计算）
        result.file_hash = self._hash_file(file_path)
        return result

    def fallback(self, file_path: Path) -> ParseResult:
        """
        降级解析：无内容，仅保留文件名和扩展名。
        解析超时或无匹配解析器时使用。
        """
        return ParseResult(raw_path=file_path)

    def _find_parser(self, file_path: Path) -> BaseParser | None:
        parsers: list[BaseParser] = ParserRegistry.get_all()
        for parser in parsers:
            if parser.can_handle(file_path):
                return parser
        return None

    @staticmethod
    def _hash_file(file_path: Path) -> str:
        h = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
        except OSError:
            pass
        return h.hexdigest()
