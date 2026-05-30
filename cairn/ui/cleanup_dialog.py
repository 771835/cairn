# coding=utf-8
from pathlib import Path

from PySide6.QtCore import QThread, QObject, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QProgressBar, QWidget,
)

from cairn.core.index.manager import IndexManager
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class ScanWorker(QObject):
    """异步扫描孤立文件。"""

    scan_done: Signal = Signal(list, int)

    def run(self) -> None:
        """执行扫描。"""
        try:
            orphans, total = IndexManager().scan_orphaned_files()
            self.scan_done.emit(orphans, total)
        except Exception as e:
            logger.error(f"扫描失败：{e}")
            self.scan_done.emit([], 0)


class CleanWorker(QObject):
    """异步执行清理。"""

    clean_done: Signal = Signal(int, int)

    def __init__(self, orphans: list[Path]) -> None:
        super().__init__()
        self._orphans = orphans

    def run(self) -> None:
        """执行清理。"""
        try:
            deleted, freed = IndexManager().clean_orphaned_files(self._orphans)
            self.clean_done.emit(deleted, freed)
        except Exception as e:
            logger.error(f"清理失败：{e}")
            self.clean_done.emit(0, 0)


class CleanupDialog(QDialog):
    """
    存储整理对话框。
    独立置顶窗口，不被 SearchWindow 遮挡。
    流程：扫描 → 预览 → 确认 → 执行 → 关闭。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("存储整理")
        self.setMinimumWidth(420)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint  # 和 SearchWindow 同层级
            | Qt.WindowType.WindowCloseButtonHint
        )
        self._orphans: list[Path] = []
        self._setup_ui()
        self._start_scan()

    # ── 界面 ──────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """构建界面。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self._status = QLabel("正在扫描孤立文件…")
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(60)
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        layout.addWidget(self._progress)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._confirm_btn = QPushButton("确认清理")
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(self._start_clean)
        self._confirm_btn.setStyleSheet(
            "QPushButton {"
            "  background: #c0392b; color: white;"
            "  border: none; border-radius: 6px; padding: 7px 18px;"
            "}"
            "QPushButton:hover:enabled { background: #e74c3c; }"
            "QPushButton:disabled { background: #555; color: #888; }"
        )

        self._close_btn = QPushButton("关闭")
        self._close_btn.setEnabled(False)  # 扫描期间不可关闭
        self._close_btn.clicked.connect(self.accept)
        self._close_btn.setStyleSheet(
            "QPushButton {"
            "  background: #444; color: #ddd;"
            "  border: none; border-radius: 6px; padding: 7px 18px;"
            "}"
            "QPushButton:hover:enabled { background: #555; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )

        btn_layout.addWidget(self._confirm_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

    # ── 扫描 ──────────────────────────────────────────────────

    def _start_scan(self) -> None:
        """启动异步扫描。"""
        self._set_progress(indeterminate=True)
        self._confirm_btn.setEnabled(False)
        self._close_btn.setEnabled(False)
        self._status.setText("正在扫描孤立文件…")

        self._scan_worker = ScanWorker()
        self._scan_thread = QThread(self)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.scan_done.connect(self._on_scan_done)
        self._scan_worker.scan_done.connect(self._scan_thread.quit)
        self._scan_thread.start()

    def _on_scan_done(self, orphans: list[Path], total_size: int) -> None:
        """扫描完成。"""
        self._orphans = orphans
        self._set_progress(indeterminate=False, value=1)

        if not orphans:
            self._status.setText(
                "✅  知识库整洁，没有发现孤立文件。"
            )
            # 无垃圾：只能关闭，确认按钮无意义
            self._confirm_btn.setEnabled(False)
            self._close_btn.setEnabled(True)
            self._close_btn.setFocus()
            return

        size_mb = total_size / 1024 / 1024
        self._status.setText(
            f"发现 {len(orphans)} 个无引用的孤立文件，"
            f"共占用 {size_mb:.3f} MB。\n\n"
            f"点击「确认清理」永久删除，此操作不可恢复。"
        )
        self._confirm_btn.setEnabled(True)
        self._close_btn.setEnabled(True)
        self._confirm_btn.setFocus()

    # ── 清理 ──────────────────────────────────────────────────

    def _start_clean(self) -> None:
        """启动异步清理。"""
        self._confirm_btn.setEnabled(False)
        self._close_btn.setEnabled(False)
        self._status.setText("正在清理…")
        self._set_progress(indeterminate=True)

        self._clean_worker = CleanWorker(self._orphans)
        self._clean_thread = QThread(self)
        self._clean_worker.moveToThread(self._clean_thread)
        self._clean_thread.started.connect(self._clean_worker.run)
        self._clean_worker.clean_done.connect(self._on_clean_done)
        self._clean_worker.clean_done.connect(self._clean_thread.quit)
        self._clean_thread.start()

    def _on_clean_done(self, deleted: int, freed: int) -> None:
        """清理完成。"""
        self._set_progress(indeterminate=False, value=1)
        freed_mb = freed / 1024 / 1024
        self._status.setText(
            f"✅  清理完成。\n"
            f"已删除 {deleted} 个文件，"
            f"释放 {freed_mb:.3f} MB。"
        )
        # 清理完成：只留关闭按钮
        self._confirm_btn.setEnabled(False)
        self._close_btn.setEnabled(True)
        self._close_btn.setFocus()

    # ── 工具 ──────────────────────────────────────────────────

    def _set_progress(
            self,
            indeterminate: bool,
            value: int = 0,
    ) -> None:
        """切换进度条模式。"""
        if indeterminate:
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, 1)
            self._progress.setValue(value)