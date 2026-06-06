# coding=utf-8

from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (
    QFileDialog, QMenu, QMessageBox, QDialog,
)
from PySide6.QtGui import QCursor

from cairn.core.config import config
from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.ui.file_context_menu import FileContextMenu
from cairn.ui.widgets import TagEditorDialog
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

    # ── 子类实现 ──────────────────────────────────────────
    def _on_item_updated(self, dto: FileDTO) -> None:
        """
        单个条目数据变化后调用。
        默认只刷新详情栏，子类按需扩展。
        """
        pass  # 子类实现

    def _get_selected_dtos(self) -> list[FileDTO]:
        """返回当前选中的所有 FileDTO。子类实现。"""
        raise NotImplementedError

    def refresh(self) -> None:
        """全量刷新视图。"""
        raise NotImplementedError

    def _remove_dtos_from_view(self, dtos: list[FileDTO]) -> None:
        """
        从视图中移除指定条目，不触发全量刷新。
        子类按需重写，默认回退到 refresh()。
        """
        self.refresh()

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
        """空白区域右键。"""
        menu = QMenu(self)  # type: ignore[call-arg]
        menu.addAction("🔄  刷新").triggered.connect(self.refresh)
        menu.exec(QCursor.pos())

    def _show_batch_menu(self, dtos: list[FileDTO]) -> None:
        """多选批量菜单。"""
        n = len(dtos)
        menu = QMenu(self)  # type: ignore[call-arg]

        menu.addAction(f"📂  还原 {n} 个文件到原始位置").triggered.connect(
            lambda: self._batch_restore(dtos)
        )
        menu.addAction(f"💾  将 {n} 个文件另存为…").triggered.connect(
            lambda: self._batch_save_as(dtos)
        )
        menu.addSeparator()
        menu.addAction(f"🗑  删除 {n} 个文件").triggered.connect(
            lambda: self._batch_delete_index(dtos)
        )
        if config.dev_mode:
            menu.addAction(f"⚠️  [DEV] 从知识库彻底删除 {n} 个文件").triggered.connect(
                lambda: self._batch_delete_store(dtos)
            )
        menu.addAction(f"🏷  为 {n} 个文件批量添加标签…").triggered.connect(
            lambda: self._batch_add_tags(dtos)
        )

        menu.addAction(f"🏷  为 {n} 个文件批量替换标签…").triggered.connect(
            lambda: self._batch_set_tags(dtos)
        )
        menu.addSeparator()
        menu.addAction("🔄  刷新").triggered.connect(self.refresh)
        menu.exec(QCursor.pos())

    # ── 批量操作 ──────────────────────────────────────────────

    def _batch_restore(self, dtos: list[FileDTO]) -> None:
        """批量还原到原始位置。"""
        no_origin = [d for d in dtos if not d.origin_path]
        has_origin = [d for d in dtos if d.origin_path]
        succeeded: list[FileDTO] = []

        for dto in has_origin:
            ok, _ = IndexManager().restore_file(dto.id)
            if ok:
                succeeded.append(dto)

        if no_origin:
            target_dir = QFileDialog.getExistingDirectory(
                self,  # type: ignore[arg-type]
                f"选择目标目录（{len(no_origin)} 个文件无原始路径）",
            )
            if target_dir:
                for dto in no_origin:
                    ok, _ = IndexManager().restore_file(
                        dto.id,
                        target_path=Path(target_dir) / dto.filename,
                    )
                    if ok:
                        succeeded.append(dto)

        failed = len(dtos) - len(succeeded)
        QMessageBox.information(
            self,  # type: ignore[arg-type]
            "批量还原完成",
            f"成功：{len(succeeded)} 个\n失败：{failed} 个",
        )
        if succeeded:
            self._remove_dtos_from_view(succeeded)

    def _batch_save_as(self, dtos: list[FileDTO]) -> None:
        """批量另存为到指定目录。"""
        target_dir = QFileDialog.getExistingDirectory(
            self, "选择目标目录"  # type: ignore[arg-type]
        )
        if not target_dir:
            return

        succeeded: list[FileDTO] = []
        for dto in dtos:
            dest = Path(target_dir) / dto.filename
            if dest.exists():
                stem, suffix = dest.stem, dest.suffix
                i = 1
                while dest.exists():
                    dest = dest.parent / f"{stem}_{i}{suffix}"
                    i += 1
            ok, _ = IndexManager().restore_file(dto.id, target_path=dest)
            if ok:
                succeeded.append(dto)

        failed = len(dtos) - len(succeeded)
        QMessageBox.information(
            self,  # type: ignore[arg-type]
            "批量另存为完成",
            f"成功：{len(succeeded)} 个\n失败：{failed} 个",
        )
        if succeeded:
            self._remove_dtos_from_view(succeeded)

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
            IndexManager().delete(dto.id)
        self._remove_dtos_from_view(dtos)

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
        self._remove_dtos_from_view(dtos)

    def _batch_add_tags(self, dtos: list[FileDTO]) -> None:
        """批量追加标签。"""
        dlg = TagEditorDialog(
            tags=[],
            title=f"批量添加标签（{len(dtos)} 个文件）",
            hint="输入要追加的标签，不会覆盖已有标签",
            parent=self,  # type: ignore[arg-type]
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_tags = dlg.get_tags()
        if not new_tags:
            return

        for dto in dtos:
            merged = list({*dto.tags, *new_tags})
            IndexManager().update_tags(dto.id, merged)
            dto.tags = merged
            self._on_item_updated(dto)  # 通知每个条目更新

        QMessageBox.information(
            self,  # type: ignore[arg-type]
            "完成",
            f"已为 {len(dtos)} 个文件追加标签：{', '.join(new_tags)}",
        )

    def _batch_set_tags(self, dtos: list[FileDTO]) -> None:
        """批量替换标签。"""
        dlg = TagEditorDialog(
            tags=[],
            title=f"批量替换标签（{len(dtos)} 个文件）",
            hint="输入新标签，将覆盖所有选中文件的原有标签",
            parent=self,  # type: ignore[arg-type]
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_tags = dlg.get_tags()
        if not new_tags:
            return

        for dto in dtos:
            IndexManager().update_tags(dto.id, new_tags)
            dto.tags = new_tags
            self._on_item_updated(dto)

        QMessageBox.information(
            self,  # type: ignore[arg-type]
            "完成",
            f"已为 {len(dtos)} 个文件设置标签：{', '.join(new_tags)}",
        )
