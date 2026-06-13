# coding=utf-8

import os
import re
from attrs import define, field
from datetime import datetime
from pathlib import Path

from lark import Lark, Transformer, Token

from cairn.utils.logger import get_logger

logger = get_logger(__name__)

NXS_GRAMMAR = r"""
    start: rule+

    rule: "rule" STRING ("." NUMBER)? filter_section "=>" rule_body

    filter_section: "(" filt_list ")"
    filt_list: filt_item ("," filt_item)*

    filt_item: IDENT (OP value_or_list)?

    value_or_list: value                        
                 | "(" value ("," value)* ")"   

    value: NUMBER UNIT?
        | STRING
        | IDENT

    UNIT: "pb" | "eb" | "tb" | "gb" | "mb" | "kb" | "b"

    OP: "==" | "=" | ">=" | "<=" | ">" | "<" | "~" | "in" | IDENT

    rule_body: "{" command_list "}"
    command_list: command*
    command: IDENT arguments?
    arguments: STRING ("," STRING)*

    IDENT:  /[a-zA-Z_][a-zA-Z0-9_]*/
    NUMBER: /[0-9]+(\.[0-9]+)?/
    STRING: /\"[^\"]*\"|'[^']*'/

    %ignore /[ \t\r\n]+/
    %ignore /\/\/.*/
"""

_UNIT_MULTIPLIERS = {
    "b": 1,
    "kb": 1024,
    "mb": 1024 ** 2,
    "gb": 1024 ** 3,
    "tb": 1024 ** 4,
    "pb": 1024 ** 5,
    "eb": 1024 ** 6,
}

_BUILTIN_OPS = {"=", "==", ">", "<", ">=", "<=", "~", "in"}


# ── 运行时数据结构 ────────────────────────────────────────────

@define(slots=True)
class FileContext:
    filename: str
    ext: str
    filepath: str
    size: int
    system: str
    modified: datetime = field(factory=datetime.now)

    @classmethod
    def from_path(cls, path: Path) -> "FileContext":
        stat = path.stat() if path.exists() else None
        return cls(
            filename=path.name,
            ext=path.suffix.lstrip(".").lower(),
            filepath=str(path.resolve()),
            size=stat.st_size if stat else 0,
            system=os.name,
            modified=datetime.fromtimestamp(stat.st_mtime) if stat else datetime.now(),
        )

    def get(self, key: str):
        return getattr(self, key, None)


@define(slots=True)
class FilterItem:
    field_name: str
    op: str | None = None
    values: list = field(factory=list)  # 统一为列表

    def evaluate(self, ctx: FileContext) -> bool:
        actual = ctx.get(self.field_name)

        # 无操作符：字段存在且非空
        if self.op is None:
            return bool(actual)

        if actual is None:
            return False

        # 内置符号操作符
        if self.op in _BUILTIN_OPS:
            return self._builtin_eval(actual)

        # 插件操作符
        from cairn.plugins.registry import OperatorRegistry
        operator = OperatorRegistry.get(self.op)
        if operator is None:
            logger.warning(f"未知操作符：'{self.op}'，跳过")
            return False

        return operator.evaluate(actual, self.values)

    def _builtin_eval(self, actual) -> bool:
        op = self.op

        # == / = 对列表做 OR 匹配
        if op in ("=", "=="):
            if isinstance(actual, int):
                return any(
                    actual == v
                    for v in self.values
                )
            else:
                return any(
                    str(actual).lower() == str(v).lower()
                    for v in self.values
                )
        if op == "~":
            # 列表中任意一个正则命中即为真
            for v in self.values:
                try:
                    if re.search(str(v), str(actual), re.IGNORECASE):
                        return True
                except re.error as e:
                    logger.warning(f"正则错误：{v} — {e}")
            return False
        if op == "in":
            return any(
                str(v).lower() in str(actual).lower()
                for v in self.values
            )

        # 数值比较：取第一个值
        expected = self.values[0] if self.values else None
        if expected is None:
            return False

        if op == ">":
            return _to_num(actual) > _to_num(expected)
        if op == "<":
            return _to_num(actual) < _to_num(expected)
        if op == ">=":
            return _to_num(actual) >= _to_num(expected)
        if op == "<=":
            return _to_num(actual) <= _to_num(expected)

        return False


@define(slots=True)
class FilterGroup:
    items: list[FilterItem] = field(factory=list)

    def evaluate(self, ctx: FileContext) -> bool:
        return all(item.evaluate(ctx) for item in self.items)


@define(slots=True)
class Command:
    name: str
    args: list[str] = field(factory=list)


@define(slots=True)
class Rule:
    name: str
    priority: float
    filter_group: FilterGroup
    commands: list[Command] = field(factory=list)


# ── Transformer ───────────────────────────────────────────────

class NXSTransformer(Transformer):

    def start(self, rules):
        return list(rules)

    def rule(self, items):
        name = _strip_quotes(str(items[0]))

        if len(items) == 4:
            # rule "name".10 (filter) => { body }
            priority = float(items[1])
            filter_group = items[2]
            commands = items[3]
        else:
            # rule "name" (filter) => { body }
            priority = 50.0
            filter_group = items[1]
            commands = items[2]

        return Rule(
            name=name,
            priority=priority,
            filter_group=filter_group,
            commands=commands,
        )

    def filter_section(self, items):
        return items[0]

    def filt_list(self, items):
        return FilterGroup(items=list(items))

    def filt_item(self, items):
        field_name = str(items[0])

        if len(items) == 1:
            # 无操作符：布尔检查
            return FilterItem(field_name=field_name)

        op = str(items[1])
        values = items[2]  # value_or_list 已解析为 list
        return FilterItem(field_name=field_name, op=op, values=values)

    def OP(self, token):
        return str(token)

    def value_or_list(self, items):
        # items 里每个元素是 value() 返回的 str 或 float
        # 直接铺平返回，不要嵌套
        return [item for item in items]

    def value(self, items):
        token = items[0]

        if isinstance(token, Token) and token.type == "STRING":
            return _strip_quotes(str(token))

        if isinstance(token, Token) and token.type == "NUMBER":
            num = float(token)
            if len(items) > 1:
                unit = str(items[1]).lower()
                num *= _UNIT_MULTIPLIERS.get(unit, 1)
            return num

        # IDENT 裸标识符
        return str(token)

    def unit(self, items):
        return str(items[0])

    def rule_body(self, items):
        return items[0]

    def command_list(self, items):
        return list(items)

    def command(self, items):
        name = str(items[0])
        args = items[1] if len(items) > 1 else []
        return Command(name=name, args=args)

    def arguments(self, items):
        return [_strip_quotes(str(t)) for t in items]


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
        return s[1:-1]
    return s


def _to_num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        logger.warning(f"{v} cannot be converted to a number")
        return 0.0


# ── 解析器入口 ────────────────────────────────────────────────

class DSLParser:
    def __init__(self):
        self._lark = Lark(NXS_GRAMMAR, parser="earley", ambiguity="resolve")
        self._transformer = NXSTransformer()

    def parse_file(self, path: Path) -> list[Rule]:
        return self.parse_text(path.read_text(encoding="utf-8"))

    def parse_text(self, text: str) -> list[Rule]:
        try:
            tree = self._lark.parse(text)
            rules = self._transformer.transform(tree)
            rules.sort(key=lambda r: r.priority)
            logger.debug(f"解析完成，共 {len(rules)} 条规则")
            return rules
        except Exception as e:
            logger.error(f"DSL 解析失败：{e}")
            raise
