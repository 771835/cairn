# coding=utf-8

from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (
    QFileDialog, QMenu, QMessageBox,
)
from  PySide6.QtGui import QCursor

from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.ui.file_context_menu import FileContextMenu
from cairn.utils.logger import get_logger

logger = get_logger(__name__)

class FileListMixin:
    """
    文件列表公共行为 Mixin。
    混入此类的视图 Tab 自动获得：
    - 右键菜单（单选完整菜单 / 多选批量菜单 / 空白刷新）
    - 批量还原、另存为、删除
    用法：视图 Tab 继承 (QWidget, FileListMixin)，
    实现 _get_selected_dtos() 和 refresh()。
    """

    # ── 子类必须实现 ──────────────────────────────────────────

    def _get_selected_dtos(self) -> list[FileDTO]:
        """返回当前选中的所有 FileDTO。子类实现。"""
        raise NotImplementedError

    def refresh(self) -> None:
        """刷新视图。子类实现。"""
        raise NotImplementedError

    # ── 右键菜单入口 ──────────────────────────────────────────

    def _on_context_menu(self, pos: QPoint) -> None:
        """
        统一右键菜单入口。
        空白区域 → 刷新
        单选     → 完整 FileContextMenu
        多选     → 批量操作菜单
        """
        dtos = self._get_selected_dtos()

        if not dtos:
            self._show_blank_menu()
            return

        if len(dtos) == 1:

            if isinstance(dtos[0], FileDTO):
                menu = FileContextMenu(dtos[0], self)  # type: ignore[arg-type]
                menu.exec(QCursor.pos())
            else:
                self._show_blank_menu()
            return

        self._show_batch_menu(dtos)

    def _show_blank_menu(self) -> None:
        """空白区域右键：只有刷新。"""
        menu = QMenu(self)  # type: ignore[call-arg]
        menu.addAction("🔄  刷新").triggered.connect(self.refresh)
        menu.exec(QCursor.pos())

    def _show_batch_menu(self, dtos: list[FileDTO]) -> None:
        """多选批量操作菜单。"""
        n = len(dtos)
        menu = QMenu(self)  # type: ignore[call-arg]

        restore_act = menu.addAction(f"📂  还原 {n} 个文件到原始位置")
        restore_act.triggered.connect(lambda: self._batch_restore(dtos))

        saveas_act = menu.addAction(f"💾  将 {n} 个文件另存为…")
        saveas_act.triggered.connect(lambda: self._batch_save_as(dtos))

        menu.addSeparator()

        del_idx_act = menu.addAction(f"🗑  从索引删除 {n} 个文件")
        del_idx_act.triggered.connect(lambda: self._batch_delete_index(dtos))

        del_store_act = menu.addAction(f"⚠️  从知识库彻底删除 {n} 个文件")
        del_store_act.triggered.connect(
            lambda: self._batch_delete_store(dtos)
        )

        menu.addSeparator()
        menu.addAction("🔄  刷新").triggered.connect(self.refresh)

        menu.exec(QCursor.pos())

    # ── 批量操作实现 ──────────────────────────────────────────

    def _batch_restore(self, dtos: list[FileDTO]) -> None:
        """批量还原到原始位置，无原始路径的引导选目录。"""
        no_origin = [d for d in dtos if not d.origin_path]
        has_origin = [d for d in dtos if d.origin_path]

        success = failed = 0

        # 有原始路径的直接还原
        for dto in has_origin:
            ok, _ = IndexManager().restore_file(dto.id)
            if ok:
                success += 1
            else:
                failed += 1

        # 无原始路径的引导选目录
        if no_origin:
            target_dir = QFileDialog.getExistingDirectory(
                self,  # type: ignore[arg-type]
                f"选择目标目录（{len(no_origin)} 个文件无原始路径）",
            )
            if target_dir:
                for dto in no_origin:
                    dest = Path(target_dir) / dto.filename
                    ok, _ = IndexManager().restore_file(
                        dto.id, target_path=dest
                    )
                    if ok:
                        success += 1
                    else:
                        failed += 1

        QMessageBox.information(
            self,  # type: ignore[arg-type]
            "批量还原完成",
            f"成功：{success} 个\n失败：{failed} 个",
        )
        self.refresh()

    def _batch_save_as(self, dtos: list[FileDTO]) -> None:
        """批量另存为到指定目录。"""
        target_dir = QFileDialog.getExistingDirectory(
            self, "选择目标目录"  # type: ignore[arg-type]
        )
        if not target_dir:
            return

        success = failed = 0
        for dto in dtos:
            dest = Path(target_dir) / dto.filename
            # 同名文件自动重命名
            if dest.exists():
                stem, suffix = dest.stem, dest.suffix
                i = 1
                while dest.exists():
                    dest = dest.parent / f"{stem}_{i}{suffix}"
                    i += 1
            ok, _ = IndexManager().restore_file(dto.id, target_path=dest)
            if ok:
                success += 1
            else:
                failed += 1

        QMessageBox.information(
            self,  # type: ignore[arg-type]
            "批量另存为完成",
            f"成功：{success} 个\n失败：{failed} 个",
        )
        self.refresh()

    def _batch_delete_index(self, dtos: list[FileDTO]) -> None:
        """批量从索引删除。"""
        reply = QMessageBox.question(
            self,  # type: ignore[arg-type]
            "确认删除",
            f"确认从索引删除 {len(dtos)} 个文件？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for dto in dtos:
            IndexManager().delete_from_index(dto.id)
        self.refresh()

    def _batch_delete_store(self, dtos: list[FileDTO]) -> None:
        """批量从知识库彻底删除。"""
        reply = QMessageBox.question(
            self,  # type: ignore[arg-type]
            "确认彻底删除",
            f"将从知识库彻底删除 {len(dtos)} 个文件，此操作不可恢复。\n确认继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for dto in dtos:
            IndexManager().delete_from_store(dto.id)
        self.refresh()