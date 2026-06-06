# coding=utf-8
"""
右键菜单

"""
import os
import subprocess
import sys
from pathlib import Path
from PySide6.QtWidgets import QMenu, QWidget, QApplication, QDialog, QVBoxLayout, QTextEdit, \
    QDialogButtonBox

from cairn.core.config import config
from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.ui.file_detail_dialog import FileDetailDialog

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

        # ── 打开 ──────────────────────────────────────────────
        self.addAction("打开文件").triggered.connect(self._open_file)

        self.addAction("复制原始路径").triggered.connect(self._copy_path)
        self.addAction("复制文件名").triggered.connect(self._copy_filename)

        self.addSeparator()

        # ── 编辑 ──────────────────────────────────────────────
        self.addAction("编辑标签…").triggered.connect(self._edit_tags)
        self.addAction("编辑注释…").triggered.connect(self._edit_comment)
        self.addAction("查看详情…").triggered.connect(self._show_detail)

        self.addSeparator()

        # ── 还原 ──────────────────────────────────────────────
        restore_act = self.addAction("还原到原始位置")
        restore_act.triggered.connect(self._restore)
        if not self._dto.origin_path:
            restore_act.setEnabled(False)

        self.addAction("另存为…").triggered.connect(self._save_as)

        self.addSeparator()

        # ── 删除 ──────────────────────────────────────────────
        self.addAction("删除").triggered.connect(self._delete)

        if config.dev_mode:
            self.addSeparator()
            sep = self.addAction("── 开发者模式 ──")
            sep.setEnabled(False)
            self.addAction("[DEV] 只删索引记录").triggered.connect(
                self._dev_delete_index
            )
            self.addAction("[DEV] 强制删除物理文件").triggered.connect(
                self._dev_delete_store
            )

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
        from cairn.ui.widgets import TagEditorDialog
        dlg = TagEditorDialog(
            tags=self._dto.tags,
            title=f"编辑标签 — {self._dto.filename}",
            parent=self._parent,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tags = dlg.get_tags()
            IndexManager().update_tags(self._dto.id, tags)
            self._dto.tags = tags
            self._notify_updated()

    def _edit_comment(self) -> None:
        """弹出注释编辑对话框。"""
        dlg = CommentDialog(self._dto.comment, self._parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            comment = dlg.get_comment()
            IndexManager().update_comment(self._dto.id, comment)
            self._dto.comment = comment
            self._notify_updated()

    def _delete(self) -> None:
        IndexManager().delete(self._dto.id)
        self._notify_deleted()

    def _dev_delete_index(self) -> None:
        IndexManager().delete(self._dto.id, dev_mode=True)
        self._notify_deleted()

    def _dev_delete_store(self) -> None:
        IndexManager().delete_from_store(self._dto.id)
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

    def _copy_filename(self) -> None:
        """复制文件名到剪贴板。"""
        QApplication.clipboard().setText(self._dto.filename)

    def _show_detail(self) -> None:
        """弹出文件详情窗口。"""
        dlg = FileDetailDialog(self._dto, self._parent)
        dlg.exec()

    def _notify_deleted(self) -> None:
        """通知父视图移除当前条目。"""
        from cairn.ui.file_list_mixin import FileListMixin
        if isinstance(self._parent, FileListMixin):
            self._parent._remove_dtos_from_view([self._dto]) # NOQA
        elif hasattr(self._parent, "refresh"):
            self._parent.refresh()

    def _notify_updated(self) -> None:
        """通知父视图条目数据已更新。"""
        from cairn.ui.file_list_mixin import FileListMixin
        if isinstance(self._parent, FileListMixin):
            self._parent._on_item_updated(self._dto) # NOQA


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