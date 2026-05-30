# coding=utf-8
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from cairn.core.dispatcher import FileEventDispatcher
from cairn.core.rule_engine.builtin_actions import register_builtin_actions
from cairn.core.rule_engine.builtin_operators import register_builtin_operators
from cairn.plugins.loader import PluginLoader
from cairn.ui.overlay import DropOverlay
from cairn.ui.folder_popup import FolderBatchChoicePopup
from cairn.ui.tray import CairnTray
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Cairn")

    # 插件与内置组件注册
    PluginLoader().load_all()
    register_builtin_operators()
    register_builtin_actions()

    # 核心组件
    dispatcher = FileEventDispatcher()
    tray = CairnTray(app)
    overlay = DropOverlay()
    popup = FolderBatchChoicePopup()

    # 信号连接
    overlay.files_dropped.connect(dispatcher.dispatch)
    overlay.folders_dropped.connect(popup.popup)


    def on_folder_choice(folders: list[Path], mode: str):
        for folder in folders:
            if mode == "expand":
                dispatcher.dispatch_folder_expand(folder)
            else:
                dispatcher.dispatch_folder_whole(folder)

    popup.choice_made.connect(on_folder_choice)

    # 通知接入 BatchNotifier
    dispatcher.process_done.connect(tray.notifier.on_done)
    dispatcher.process_error.connect(tray.notifier.on_error)


    if "--debug-window" in sys.argv:
        # 调试模式：窗口不置顶，不透明
        from cairn.ui.search_window import SearchWindow
        # 开启搜索窗口调试选项
        SearchWindow.debug = True

        logger.setLevel(logging.DEBUG)

        logger.info("调试模式已启用")

    overlay.show()
    logger.info("Cairn 已启动")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
