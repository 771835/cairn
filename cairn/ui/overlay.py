# coding=utf-8
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QApplication

from cairn.core.config import config
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class DropOverlay(QWidget):
    """
    屏幕边缘透明拖放接收区。
    唯一的文件输入入口。

    发出信号：
        files_dropped(list[str])  接收到的文件路径列表
    """

    files_dropped = Signal(list)  # list[Path]，普通文件
    folders_dropped = Signal(list, QPoint)  # list[Path], QPoint

    def __init__(self):
        super().__init__()
        self._is_hovering = False
        self._cfg = config.overlay
        self._setup_window()
        self._position_on_edge()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setToolTip("拖入文件以触发 Cairn 处理")

    def _position_on_edge(self):
        """贴靠屏幕边缘，尺寸由配置决定。"""
        screen = QApplication.primaryScreen().geometry()
        w = self._cfg.width
        h = int(screen.height() * self._cfg.size_ratio)
        edge = self._cfg.edge

        if edge == "right":
            self.setGeometry(
                screen.width() - w, (screen.height() - h) // 2, w, h
            )
        elif edge == "left":
            self.setGeometry(0, (screen.height() - h) // 2, w, h)
        elif edge == "top":
            self.setGeometry(
                (screen.width() - h) // 2, 0, h, w
            )
        elif edge == "bottom":
            self.setGeometry(
                (screen.width() - h) // 2, screen.height() - w, h, w
            )
        else:
            # 兜底：默认右侧
            self.setGeometry(
                screen.width() - w, (screen.height() - h) // 2, w, h
            )

    # ── 绘制 ──────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = self._cfg.hover_alpha if self._is_hovering else self._cfg.idle_alpha
        r, g, b = self._cfg.color
        painter.setBrush(QColor(r, g, b, alpha))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), self._cfg.border_radius, self._cfg.border_radius)

    # ── 拖放事件 ──────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            self._is_hovering = True
            self.update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._is_hovering = False
        self.update()

    def dropEvent(self, event):
        self._is_hovering = False
        self.update()

        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()
                 if u.isLocalFile()]
        folders = [p for p in paths if p.is_dir()]
        files = [p for p in paths if p.is_file()]

        if files:
            self.files_dropped.emit(files)

        if folders:
            global_pos = self.mapToGlobal(event.position().toPoint())
            self.folders_dropped.emit(folders, global_pos)
