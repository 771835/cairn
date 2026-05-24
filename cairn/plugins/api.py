# coding=utf-8
from pathlib import Path
from cairn.core.parser.base import ParseResult


class ParserPlugin:
    """
    文件解析插件基类。
    将文件内容转化为 ParseResult。
    """
    name: str = ""
    supported_extensions: list[str] = []

    def parse(self, file_path: Path) -> ParseResult:
        raise NotImplementedError

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions


class ActionPlugin:
    """
    规则动作插件基类。
    """
    name: str = ""
    dsl_keyword: str = ""

    def configure(self, args: dict): pass

    def execute(self, result: ParseResult, args: list[str]):
        """
        args: DSL 中指令的位置参数列表
        例：move "/dest/"     → args = ["/dest/"]
            tag "a", "b"     → args = ["a", "b"]
        """
        raise NotImplementedError


class OperatorPlugin:
    """
    自定义操作符插件。
    注册后可在 DSL 过滤器中作为 IDENT 操作符使用。

    示例：
        (filepath startswith "/home")
        (content matches "HELP.*")
    """
    name: str = ""  # 操作符名，即 DSL 中的 IDENT
    dsl_keyword: str = ""  # 同 name，保持插件系统统一

    def evaluate(self, actual, args: list) -> bool:
        """
        actual:  从 FileContext 取出的字段值
        list: DSL 中操作符右侧的参数（已转换为 Python 原生类型）
        """
        raise NotImplementedError