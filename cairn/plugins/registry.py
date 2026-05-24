# coding=utf-8
from cairn.utils.logger import get_logger

logger = get_logger(__name__)

class OperatorRegistry:
    """
    操作注册表
    负责注册和存储全局的操作符。
    使用类方法访问，无需实例化。
    """
    _operators: dict[str, object] = {}

    @classmethod
    def register(cls, operator):
        """注册一个操作"""
        cls._operators[operator.dsl_keyword] = operator
        logger.debug(f"已注册操作：{operator.name}")


    @classmethod
    def get(cls, key: str):
        """按key获取操作，不存在返回 None"""
        return cls._operators.get(key, None)

class ActionRegistry:
    """
    行动注册表
    负责注册和存储全局的行动。
    使用类方法访问，无需实例化。
    """
    _actions: dict[str, object] = {}

    @classmethod
    def register(cls, action):
        """注册一个行动"""
        cls._actions[action.dsl_keyword] = action
        logger.debug(f"已注册行动：{action.name}")

    @classmethod
    def get(cls, key: str):
        """按key获取行动，不存在返回 None"""
        return cls._actions.get(key, None)

class ParserRegistry:
    """
    解析器注册表
    负责注册和存储全局的解析器。
    使用类方法访问，无需实例化。
    """
    _parsers: list[object] = {}

    @classmethod
    def register(cls, parser):
        """注册一个解析器"""
        cls._parsers.append(parser)
        logger.debug(f"已注册解析器：{parser.__class__.__name__}")

    @classmethod
    def get_all(cls):
        """获得所有解析器"""
        return cls._parsers