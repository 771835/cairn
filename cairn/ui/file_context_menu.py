# coding=utf-8
"""
右键菜单

"""
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QMenu, QWidget, QApplication, QInputDialog, QDialog, QVBoxLayout, QTextEdit, \
    QDialogButtonBox

from cairn.core.config import config
from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class FileContextMenu(QMenu):
    """文件条目右键菜单。"""

    def __init__(self, dto: FileDTO, parent: QWidget) -> None:
        super().__init__(parent)
        self._dto = dto
        self._parent = parent
        self._build()

    def _build(self) -> None:
        """构建菜单项。"""
        open_act = self.addAction("打开文件")
        open_act.triggered.connect(self._open_file)

        copy_act = self.addAction("复制原始路径")
        copy_act.triggered.connect(self._copy_path)
        if not self._dto.origin_path:
            copy_act.setEnabled(False)

        self.addSeparator()

        tag_act = self.addAction("编辑标签…")
        tag_act.triggered.connect(self._edit_tags)

        comment_act = self.addAction("编辑注释…")
        comment_act.triggered.connect(self._edit_comment)

        self.addSeparator()

        del_idx_act = self.addAction("从索引删除")
        del_idx_act.triggered.connect(self._delete_index)

        del_all_act = self.addAction("从知识库彻底删除")
        del_all_act.triggered.connect(self._delete_store)

        if config.dev_mode:
            self.addSeparator()
            dev_label = self.addAction("── 开发者模式 ──")
            dev_label.setEnabled(False)

            dev_idx_act = self.addAction("[DEV] 只删索引记录")
            dev_idx_act.triggered.connect(self._dev_delete_index)

            dev_all_act = self.addAction("[DEV] 强制删除物理文件")
            dev_all_act.triggered.connect(self._dev_delete_store)

        self.addSeparator()

        restore_act = self.addAction("还原到原始位置")
        restore_act.triggered.connect(self._restore)
        if not self._dto.origin_path:
            restore_act.setEnabled(False)

        saveas_act = self.addAction("另存为…")
        saveas_act.triggered.connect(self._save_as)

    def _open_file(self) -> None:
        """用系统默认程序打开文件。"""
        store_path = IndexManager().get_store_path(self._dto.file_hash)
        path = store_path if store_path and store_path.exists() else None
        if path is None:
            logger.warning(f"文件不存在：{self._dto.filename}")
            return
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.run(["xdg-open", str(path)])

    def _copy_path(self) -> None:
        """复制原始路径到剪贴板。"""
        QApplication.clipboard().setText(self._dto.origin_path or "")

    def _edit_tags(self) -> None:
        """弹出标签编辑对话框。"""
        current = ", ".join(self._dto.tags)
        text, ok = QInputDialog.getText(
            self._parent,
            "编辑标签",
            "标签（逗号分隔）：",
            text=current,
        )
        if ok:
            tags = [t.strip() for t in text.split(",") if t.strip()]
            IndexManager().update_tags(self._dto.id, tags)
            self._dto.tags = tags

    def _edit_comment(self) -> None:
        """弹出注释编辑对话框。"""
        dlg = CommentDialog(self._dto.comment, self._parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            comment = dlg.get_comment()
            IndexManager().update_comment(self._dto.id, comment)
            self._dto.comment = comment

    def _delete_index(self) -> None:
        IndexManager().delete_from_index(self._dto.id)
        self._notify_deleted()

    def _delete_store(self) -> None:
        IndexManager().delete_from_store(self._dto.id)
        self._notify_deleted()

    def _dev_delete_index(self) -> None:
        IndexManager().delete_from_index(self._dto.id, dev_mode=True)
        self._notify_deleted()

    def _dev_delete_store(self) -> None:
        IndexManager().delete_from_store(self._dto.id, dev_mode=True)
        self._notify_deleted()

    def _restore(self) -> None:
        """还原到原始位置。"""
        ok, msg = IndexManager().restore_file(self._dto.id)
        if ok:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self._parent, "还原成功", f"已还原到：\n{msg}"
            )
            self._notify_deleted()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._parent, "还原失败", msg)

    def _save_as(self) -> None:
        """另存为到用户选择的位置。"""
        from PySide6.QtWidgets import QFileDialog
        dest, _ = QFileDialog.getSaveFileName(
            self._parent,
            "另存为",
            self._dto.filename,
        )
        if not dest:
            return
        ok, msg = IndexManager().restore_file(
            self._dto.id, target_path=Path(dest)
        )
        if ok:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self._parent, "保存成功", f"已保存到：\n{msg}"
            )
            self._notify_deleted()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._parent, "保存失败", msg)

    def _notify_deleted(self) -> None:
        """通知父窗口刷新列表。"""
        if hasattr(self._parent, "refresh"):
            self._parent.refresh()


class CommentDialog(QDialog):
    """注释编辑对话框。"""

    def __init__(self, current: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑注释")
        self.setMinimumSize(400, 200)

        layout = QVBoxLayout(self)

        self._editor = QTextEdit()
        self._editor.setPlainText(current)
        self._editor.setStyleSheet(
            "background: #2b2b2b; color: #e0e0e0; "
            "border: 1px solid #555; border-radius: 6px; "
            "padding: 8px; font-size: 13px;"
        )
        layout.addWidget(self._editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel  # NOQA
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_comment(self) -> str:
        """返回编辑后的注释内容。"""
        return self._editor.toPlainText().strip()
