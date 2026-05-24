# coding=utf-8

from pathlib import Path
from PySide6.QtCore import QThread, QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QProgressBar, QWidget,
)
from cairn.core.index.manager import IndexManager
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


class ScanWorker(QObject):
    """异步扫描孤立文件。"""
    scan_done: Signal = Signal(list, int)  # (orphans, total_size)

    def run(self) -> None:
        """执行扫描。"""
        orphans, total = IndexManager().scan_orphaned_files()
        self.scan_done.emit(orphans, total)


class CleanWorker(QObject):
    """异步执行清理。"""
    clean_done: Signal = Signal(int, int)  # (deleted, freed)

    def __init__(self, orphans: list[Path]) -> None:
        super().__init__()
        self._orphans = orphans

    def run(self) -> None:
        """执行清理。"""
        deleted, freed = IndexManager().clean_orphaned_files(self._orphans)
        self.clean_done.emit(deleted, freed)


class CleanupDialog(QDialog):
    """
    存储整理对话框。
    扫描 → 预览 → 用户确认 → 执行。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("存储整理(严重风险，将导致数据完全丢失，无法找回)")
        self.setMinimumWidth(400)
        self._orphans: list[Path] = []
        self._total_size: int = 0
        self._setup_ui()
        self._start_scan()

    def _setup_ui(self) -> None:
        """构建界面。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._status = QLabel("正在扫描孤立文件…")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # 不确定进度条
        layout.addWidget(self._progress)

        btn_layout = QHBoxLayout()

        self._confirm_btn = QPushButton("确认清理")
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(self._start_clean)
        self._confirm_btn.setStyleSheet(
            "background: #c0392b; color: white; "
            "border: none; border-radius: 6px; padding: 6px 16px;"
        )

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(
            "background: #555; color: white; "
            "border: none; border-radius: 6px; padding: 6px 16px;"
        )

        btn_layout.addWidget(self._confirm_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _start_scan(self) -> None:
        """启动异步扫描。"""
        self._worker = ScanWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.scan_done.connect(self._on_scan_done)
        self._worker.scan_done.connect(self._thread.quit)
        self._thread.start()

    def _on_scan_done(self, orphans: list[Path], total_size: int) -> None:
        """扫描完成，显示预览。"""
        self._orphans = orphans
        self._total_size = total_size
        self._progress.setRange(0, 1)
        self._progress.setValue(1)

        if not orphans:
            self._status.setText("✅ 知识库整洁，没有孤立文件。")
            return

        size_mb = total_size / 1024 / 1024
        self._status.setText(
            f"发现 {len(orphans)} 个无引用的孤立文件，\n"
            f"共占用 {size_mb:.1f} MB。\n\n"
            f"确认后将永久删除，此操作不可恢复。"
        )
        self._confirm_btn.setEnabled(True)

    def _start_clean(self) -> None:
        """启动异步清理。"""
        self._confirm_btn.setEnabled(False)
        self._status.setText("正在清理…")
        self._progress.setRange(0, 0)

        self._clean_worker = CleanWorker(self._orphans)
        self._clean_thread = QThread(self)
        self._clean_worker.moveToThread(self._clean_thread)
        self._clean_thread.started.connect(self._clean_worker.run)
        self._clean_worker.clean_done.connect(self._on_clean_done)
        self._clean_worker.clean_done.connect(self._clean_thread.quit)
        self._clean_thread.start()

    def _on_clean_done(self, deleted: int, freed: int) -> None:
        """清理完成，显示结果。"""
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        freed_mb = freed / 1024 / 1024
        self._status.setText(
            f"✅ 清理完成。\n"
            f"已删除 {deleted} 个文件，释放 {freed_mb:.1f} MB。"
        )