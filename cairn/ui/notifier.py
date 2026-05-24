# coding=utf-8
from collections import defaultdict
from PySide6.QtCore import QObject, QTimer, Signal
from cairn.core.config import config
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class BatchNotifier(QObject):
    """
    批量聚合通知。

    - 收到处理结果后开启计时窗口（默认 2 秒）
    - 窗口内继续收集，窗口结束时合并发出一条通知
    - 超过 silent_threshold 个文件：只更新 tooltip，不弹窗
    - 单个错误：立即弹窗
    """

    notify_signal = Signal(str, bool)  # (message, is_silent)
    tooltip_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending: dict[str, int] = defaultdict(int)  # rule_name → count
        self._errors: list[str] = []
        self._total: int = 0

        cfg = config.notify
        self._threshold = cfg.silent_threshold
        self._window_ms = cfg.batch_window_ms

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def on_done(self, message: str):
        """接收单个文件处理完成的消息"""
        self._total += 1

        # 解析规则名（格式："已处理：xxx\n命中规则：yyy"）
        rule = "无匹配规则"
        if "命中规则：" in message:
            rule = message.split("命中规则：")[-1].strip()
        self._pending[rule] += 1

        # 实时更新 tooltip
        self.tooltip_signal.emit(f"Cairn — 处理中（{self._total} 个文件）")

        # 重置计时窗口
        self._timer.start(self._window_ms)

    def on_error(self, message: str):
        """错误立即弹窗，不等窗口"""
        self._errors.append(message)
        self.error_signal.emit(message)
        logger.error(f"处理错误：{message}")

    def _flush(self):
        """计时窗口结束，合并发出通知"""
        if not self._pending:
            return

        total = self._total
        silent = total >= self._threshold

        # 构建消息
        if total == 1:
            rule = next(iter(self._pending))
            msg = f"已处理 1 个文件\n{rule}"
        else:
            lines = [f"已处理 {total} 个文件"]
            for rule, count in sorted(
                    self._pending.items(), key=lambda x: -x[1]
            ):
                lines.append(f"  {rule} × {count}")
            msg = "\n".join(lines)

        self.notify_signal.emit(msg, silent)
        self.tooltip_signal.emit(f"Cairn — 就绪（最近处理 {total} 个）")

        # 重置
        self._pending.clear()
        self._total = 0