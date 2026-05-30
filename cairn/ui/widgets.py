# coding=utf-8
from PySide6.QtCore import Signal, Qt, QStringListModel
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit,
    QCompleter, QDialog, QVBoxLayout,
    QLabel, QDialogButtonBox,
)

from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class TagEditor(QWidget):
    """
    标签编辑控件。
    值格式：逗号分隔，无 # 前缀。
    补全作用于最后一个词，选中后只替换最后一个词，已输入的标签保留。
    """

    tags_changed: Signal = Signal(list)

    def __init__(self, tags: list[str], parent: QWidget | None = None) -> None:
        """初始化标签编辑控件并加载补全数据。"""
        super().__init__(parent)
        self._setup_ui(tags)
        self._load_completions()

    def _setup_ui(self, tags: list[str]) -> None:
        """构建输入框。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._edit = QLineEdit(", ".join(tags))
        self._edit.setPlaceholderText("标签（逗号分隔）")
        self._edit.setStyleSheet(
            "background: #2b2b2b; color: #e0e0e0; "
            "border: 1px solid #555; border-radius: 4px; padding: 4px 8px;"
        )
        self._edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._edit)

    def _load_completions(self) -> None:
        """从数据库加载所有已有标签作为补全候选。"""
        try:
            from cairn.core.index.manager import IndexManager
            all_tags = [name for name, _ in IndexManager().get_all_tags()]
        except Exception as e:
            logger.warning(f"加载标签补全失败：{e}")
            all_tags = []

        self._completion_model = QStringListModel(all_tags)

        self._completer = QCompleter(self._completion_model, self)
        self._completer.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self._completer.setFilterMode(
            Qt.MatchFlag.MatchContains  # 包含匹配，不只是前缀
        )
        self._completer.setWidget(self._edit)
        self._completer.activated.connect(self._on_completion_selected)

    def _on_text_changed(self, text: str) -> None:
        """文本变化时，对最后一个词触发补全。"""
        self.tags_changed.emit(self.get_tags())

        # 取最后一个逗号后的内容作为补全前缀
        parts = text.split(",")
        prefix = parts[-1].strip()

        if not prefix:
            self._completer.popup().hide()
            return

        self._completer.setCompletionPrefix(prefix)

        if self._completer.completionCount() > 0:
            # 定位到输入框光标处弹出
            cr = self._edit.cursorRect()
            cr.setWidth(
                self._completer.popup().sizeHintForColumn(0)
                + self._completer.popup().verticalScrollBar().sizeHint().width()
            )
            self._completer.complete(cr)
        else:
            self._completer.popup().hide()

    def _on_completion_selected(self, selected: str) -> None:
        """
        选中补全项后，只替换最后一个词，保留前面已输入的标签。
        例：输入 "笔记, py" 选中 "python" → "笔记, python"
        """
        current = self._edit.text()
        parts = current.split(",")

        # 替换最后一个词
        parts[-1] = f" {selected}"
        new_text = ",".join(parts)

        # 暂时断开信号，避免补全循环触发
        self._edit.blockSignals(True)
        self._edit.setText(new_text)
        self._edit.blockSignals(False)

        # 光标移到末尾
        self._edit.setCursorPosition(len(new_text))
        self._completer.popup().hide()

        self.tags_changed.emit(self.get_tags())

    def get_tags(self) -> list[str]:
        """返回当前标签列表（去空、去重、转小写）。"""
        seen: set[str] = set()
        result: list[str] = []
        for t in self._edit.text().split(","):
            tag = t.strip().lower()
            if tag and tag not in seen:
                seen.add(tag)
                result.append(tag)
        return result

    def set_tags(self, tags: list[str]) -> None:
        """设置标签，触发 tags_changed 信号。"""
        self._edit.setText(", ".join(tags))


class TagEditorDialog(QDialog):
    """
    标签编辑对话框，内嵌 TagEditor。
    """

    def __init__(
            self,
            tags: list[str],
            title: str = "编辑标签",
            hint: str = "逗号分隔，输入时自动补全",
            parent: QWidget | None = None,
    ) -> None:
        """初始化标签编辑对话框。"""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._setup_ui(tags, hint)
        self._apply_theme()

    def _setup_ui(self, tags: list[str], hint: str) -> None:
        """构建对话框界面。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        hint_lbl = QLabel(hint)
        hint_lbl.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint_lbl)

        self._editor = TagEditor(tags, parent=self)
        layout.addWidget(self._editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_tags(self) -> list[str]:
        """返回编辑后的标签列表。"""
        return self._editor.get_tags()

    def _apply_theme(self) -> None:
        """应用深色主题。"""
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #e0e0e0; }
            QLabel  { color: #e0e0e0; font-size: 13px; }
            QDialogButtonBox QPushButton {
                background: #2d5a8e; color: white; border: none;
                border-radius: 6px; padding: 6px 18px; font-size: 13px;
            }
            QDialogButtonBox QPushButton:hover { background: #3a6fa8; }
        """)
