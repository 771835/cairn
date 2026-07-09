# coding=utf-8
def _input_style() -> str:
    return """
        QLineEdit {
            background: #2b2b2b; color: #e0e0e0;
            border: 1px solid #555; border-radius: 8px;
            padding: 10px 14px; font-size: 15px;
        }
        QLineEdit:focus { border-color: #4A9EFF; }
    """


def _list_style() -> str:
    return """
        QListWidget {
            background: #1e1e1e; color: #d0d0d0;
            border: none; border-radius: 8px;
            font-size: 13px; outline: none;
        }
        QListWidget::item { padding: 8px 12px; border-radius: 4px; }
        QListWidget::item:selected { background: #2d5a8e; color: white; }
        QListWidget::item:hover    { background: #2a2a2a; }
    """


def _tree_style() -> str:
    return """
        QTreeWidget {
            background: #1e1e1e; color: #d0d0d0;
            border: none; font-size: 13px; outline: none;
        }
        QTreeWidget::item { padding: 5px 8px; border-radius: 4px; }
        QTreeWidget::item:selected { background: #2d5a8e; color: white; }
        QTreeWidget::item:hover    { background: #2a2a2a; }
    """


def _tab_style() -> str:
    return """
        QTabWidget::pane {
            border: none;
            background: transparent;
        }
        QTabBar::tab {
            background: #2a2a2a; color: #aaa;
            border: none; border-radius: 6px;
            padding: 6px 16px; margin-right: 4px;
            font-size: 13px;
        }
        QTabBar::tab:selected { background: #2d5a8e; color: white; }
        QTabBar::tab:hover    { background: #333; }
    """


def _status_style() -> str:
    return "color: rgba(200,200,200,0.5); font-size: 11px; padding: 0 4px;"


def _detail_style() -> str:
    return (
        "color: rgba(200,200,200,0.6); font-size: 11px; "
        "padding: 2px 4px;"
    )
