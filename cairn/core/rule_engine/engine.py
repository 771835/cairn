# coding=utf-8
from pathlib import Path

from cairn.core.config import config
from cairn.core.parser.base import ParseResult
from cairn.core.rule_engine.dsl_parser import DSLParser, FileContext, Rule
from cairn.plugins.registry import ActionRegistry
from cairn.utils.logger import get_logger

logger = get_logger(__name__)

RULES_PATH = Path("config/rules.nxs")


class RuleEngine:
    def __init__(self):
        self._rules: list[Rule] = []
        self._parser = DSLParser()
        self.reload()

    def reload(self):
        if not RULES_PATH.exists():
            logger.warning(f"规则文件不存在：{RULES_PATH}")
            self._rules = []
            return
        try:
            self._rules = self._parser.parse_file(RULES_PATH)
            logger.info(f"已加载 {len(self._rules)} 条规则")
        except Exception as e:
            logger.error(f"规则加载失败：{e}")
            self._rules = []

    def process(self, result: ParseResult) -> list[str]:
        ctx = FileContext.from_path(result.raw_path)
        matched_names = []

        for rule in self._rules:
            if not rule.filter_group.evaluate(ctx):
                continue

            matched_names.append(rule.name)
            logger.info(f"命中规则：'{rule.name}'")

            should_stop = self._execute(rule, result)
            if should_stop:
                break  # 真正停止后续规则匹配

        return matched_names

    def _execute(self, rule: Rule, result: ParseResult) -> bool:
        """返回 True 表示遇到 stop，外层应停止继续匹配"""
        for cmd in rule.commands:
            if cmd.name == "stop":
                return True  # 通知 process() 停止

            action = ActionRegistry.get(cmd.name)
            if action is None:
                logger.warning(f"未知指令：'{cmd.name}'，跳过")
                continue

            try:
                action.execute(result, cmd.args)
            except Exception as e:
                logger.error(
                    f"规则 '{rule.name}' 指令 '{cmd.name}' 执行失败：{e}"
                )
                if config.dev_mode:
                    import traceback
                    traceback.print_tb(e.__traceback__)

        return False  # 正常结束，继续匹配
