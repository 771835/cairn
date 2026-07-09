# coding=utf-8
import global_hotkeys as hotkey
from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSystemTrayIcon, QMenu

from cairn.core.config import config
from cairn.ui.notifier import BatchNotifier
from cairn.ui.stats_dialog import StatsDialog
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class CairnTray(QSystemTrayIcon):
    hotkey = Signal()

    def __init__(self, app):
        icon = app.style().standardIcon(
            app.style().StandardPixmap.SP_DriveHDIcon
        )
        super().__init__(icon)
        self._app = app
        self._notifier = BatchNotifier()
        self._search_window = None  # 延迟初始化

        self._notifier.notify_signal.connect(self._on_notify)
        self._notifier.tooltip_signal.connect(self.setToolTip)
        self._notifier.error_signal.connect(self._on_error)

        # 全局快捷键
        hotkey.register_hotkey(config.hotkey, None, self._wake_hot_key)
        hotkey.start_checking_hotkeys()
        self.hotkey.connect(self._on_hot_key)

        self._setup_menu()
        self.setToolTip("Cairn")
        self.setVisible(True)
        self.activated.connect(self._on_activated)

    def _setup_menu(self):
        menu = QMenu()

        search_action = QAction("搜索知识库  Ctrl+Shift+Space", menu)
        search_action.triggered.connect(self.open_search)
        menu.addAction(search_action)

        stats_action = QAction("知识库统计…", menu)
        stats_action.triggered.connect(lambda: StatsDialog().exec())
        menu.addAction(stats_action)

        cleanup_action = QAction("存储整理…", menu)
        cleanup_action.triggered.connect(self._open_cleanup)
        menu.addAction(cleanup_action)

        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _on_activated(self, reason):
        """单击托盘图标打开搜索"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_search()

    def open_search(self):
        from cairn.ui.search_window import SearchWindow
        if self._search_window is None:
            self._search_window = SearchWindow()
        self._search_window.show_and_focus()

    def _open_cleanup(self) -> None:
        """打开存储整理对话框。"""
        from cairn.ui.cleanup_dialog import CleanupDialog
        dlg = CleanupDialog()
        dlg.exec()

    def _on_notify(self, message: str, is_silent: bool):
        if is_silent:
            logger.info(f"静默通知：{message}")
        else:
            self.showMessage("Cairn", message,
                             QSystemTrayIcon.MessageIcon.Information, config.notify.info_duration_ms)

    def _on_error(self, message: str):
        self.showMessage("Cairn — 错误", message,
                         QSystemTrayIcon.MessageIcon.Critical, config.notify.error_duration_ms)

    def _wake_hot_key(self):
        self.hotkey.emit()

    @Slot()
    def _on_hot_key(self):
        self.open_search()

    @property
    def notifier(self) -> BatchNotifier:
        return self._notifier
