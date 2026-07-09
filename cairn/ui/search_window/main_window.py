# coding=utf-8
"""
Cairn 主搜索与浏览窗口。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QApplication

from cairn.ui.search_window.style_constants import _tab_style
from cairn.ui.search_window.tabs.folder_tab import FolderTab
from cairn.ui.search_window.tabs.search_tab import SearchTab
from cairn.ui.search_window.tabs.tag_tab import TagTab
from cairn.ui.search_window.tabs.time_line_tab import TimelineTab


class SearchWindow(QWidget):
    """
    Cairn 主搜索与浏览窗口。

    Tab 布局：[搜索] [文件夹] [标签] [时间线]
    全局快捷键或托盘点击呼出，ESC 隐藏。
    """

    debug = False

    def __init__(self) -> None:
        super().__init__()
        self._setup_window()
        self._setup_ui()

    def _setup_window(self) -> None:
        """配置无边框透明窗口。"""
        if not self.debug:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(900, 600)

    def _setup_ui(self) -> None:
        """构建主界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_tab_style())

        self._search_tab = SearchTab()
        self._folder_tab = FolderTab()
        self._tag_tab = TagTab()
        self._timeline_tab = TimelineTab()

        self._tabs.addTab(self._search_tab, "🔍  搜索")
        self._tabs.addTab(self._folder_tab, "📁  文件夹")
        self._tabs.addTab(self._tag_tab, "🏷  标签")
        self._tabs.addTab(self._timeline_tab, "🕐  时间线")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs)

    def paintEvent(self, event) -> None:
        """绘制半透明深色圆角背景。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(18, 18, 18, 245))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 14, 14)

    def show_and_focus(self) -> None:
        """居中显示并聚焦搜索框。"""
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 3,
        )
        self.show()
        self.raise_()
        self.activateWindow()
        self._tabs.setCurrentIndex(0)
        self._search_tab.focus_input()

    def keyPressEvent(self, event) -> None:
        """ESC 隐藏窗口。"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def _on_tab_changed(self, index: int) -> None:
        """切换 Tab 时按需加载数据。"""
        if index == 1:
            self._folder_tab.load()
        elif index == 2:
            self._tag_tab.load()
        elif index == 3:
            self._timeline_tab.load()
