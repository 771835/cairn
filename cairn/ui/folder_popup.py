# coding=utf-8
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel
)

from cairn.core.config import config


# ── 文件夹处理选择窗口 ────────────────────────────────────────
class FolderBatchChoicePopup(QWidget):
    """
    拖入文件夹时弹出的选择窗口。

    设计要点：
    - 无边框，半透明背景
    - 出现在鼠标释放位置附近
    - 一定时间内无操作自动关闭（默认展开）
    - 两个选择：展开处理 / 整体索引
    - 显示文件夹数量，用户选择统一处理模式。
    """

    choice_made = Signal(list, str)  # (list[Path], "expand" | "whole")

    def __init__(self):
        super().__init__()
        self._folders: list[Path] = []
        self._cfg = config.folder
        self._countdown = self._cfg.auto_close_s
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._on_timeout)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self._setup_ui()
        self._setup_window()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 150)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self._title = QLabel()
        self._title.setStyleSheet(
            "color: white; font-size: 13px; font-weight: bold;"
        )
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._detail = QLabel()
        self._detail.setStyleSheet(
            "color: rgba(255,255,255,0.7); font-size: 11px;"
        )
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

        self._hint = QLabel()
        self._hint.setStyleSheet(
            "color: rgba(255,255,255,0.5); font-size: 11px;"
        )
        layout.addWidget(self._hint)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._btn_expand = QPushButton("全部展开")
        self._btn_expand.setStyleSheet(self._btn_style("#4A9EFF"))
        self._btn_expand.clicked.connect(lambda: self._choose("expand"))

        self._btn_whole = QPushButton("全部整体索引")
        self._btn_whole.setStyleSheet(self._btn_style("#6C6C6C"))
        self._btn_whole.clicked.connect(lambda: self._choose("whole"))

        btn_layout.addWidget(self._btn_expand)
        btn_layout.addWidget(self._btn_whole)
        layout.addLayout(btn_layout)

    @staticmethod
    def _btn_style(color: str) -> str:
        return f"""
            QPushButton {{
                background: {color}; color: white;
                border: none; border-radius: 6px;
                padding: 6px 0; font-size: 12px;
            }}
            QPushButton:hover {{ background: {color}CC; }}
        """

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(30, 30, 30, 220))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 12, 12)

    def popup(self, folders: list[Path], near: QPoint):
        self._folders = folders
        self._countdown = 5

        if len(folders) == 1:
            self._title.setText(f"📁  {folders[0].name}")
        else:
            self._title.setText(f"📁  {len(folders)} 个文件夹")

        # 显示前三个文件夹名
        preview = "、".join(f.name for f in folders[:3])
        if len(folders) > 3:
            preview += f" 等 {len(folders)} 个"
        self._detail.setText(preview)
        self._update_hint()

        screen = QApplication.primaryScreen().geometry()
        x = min(near.x() + 12, screen.width() - self.width() - 8)
        y = min(near.y() + 12, screen.height() - self.height() - 8)
        self.move(x, y)

        self.show()
        self._auto_timer.start(self._cfg.auto_close_s * 1000)
        self._tick_timer.start()

    def _tick(self):
        self._countdown -= 1
        self._update_hint()

    def _update_hint(self):
        self._hint.setText(f"{self._countdown}s 后自动展开处理")

    def _on_timeout(self):
        self._choose(self._cfg.default_action)

    def _choose(self, mode: str):
        self._auto_timer.stop()
        self._tick_timer.stop()
        self.hide()
        self.choice_made.emit(self._folders, mode)
