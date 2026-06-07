# coding=utf-8
import os
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QFrame, QScrollArea,
    QProgressBar,
)
from sqlmodel import Session, select, func, col, case

from cairn.core.config import config
from cairn.core.index.manager import IndexManager
from cairn.core.index.models import File, Tag, FileTagLink
from cairn.utils.fmt_tools import format_size
from cairn.utils.logger import get_logger

logger = get_logger(__name__)



def get_folder_size_blocks(path, block_size=4096):
    """计算目录占用的实际磁盘块数（考虑文件系统块大小）"""
    total_blocks = 0
    for dirpath, dirnames, filenames in os.walk(path):
        # 计算目录本身占用的块数
        dir_stat = os.stat(dirpath)
        total_blocks += (dir_stat.st_size + block_size - 1) // block_size

        # 计算文件占用的块数
        for filename in filenames:
            filepath = os.path.join(dirpath, filename) # noqa
            try:
                file_stat = os.stat(filepath)
                # 计算文件占用的块数（向上取整）
                blocks = (file_stat.st_size + block_size - 1) // block_size
                total_blocks += blocks
            except OSError:
                continue
    return total_blocks * block_size  # 转换为字节


# ── 数据类 ────────────────────────────────────────────────────

class StatsData:
    """统计数据容器。"""

    def __init__(self) -> None:
        """初始化统计数据。"""
        self.total_files: int = 0
        self.total_folders: int = 0
        self.total_size: int = 0
        self.actual_size: int = 0
        self.total_tags: int = 0
        self.ext_counts: list[tuple[str, int]] = []
        self.top_tags: list[tuple[str, int]] = []
        self.recent_file: str = "—"
        self.recent_time: str = "—"
        self.orphan_hint: str = ""


# ── 异步加载 Worker ───────────────────────────────────────────

class StatsWorker(QObject):
    """在独立线程中加载统计数据。"""

    data_ready: Signal = Signal(object)

    def run(self) -> None:
        """执行统计查询。"""
        try:
            data = self._load()
            self.data_ready.emit(data)
        except Exception as e:
            logger.error(f"统计加载失败：{e}")
            self.data_ready.emit(StatsData())

    @staticmethod
    def _load() -> StatsData:
        """执行所有统计查询，返回 StatsData。"""
        idx = IndexManager()
        data = StatsData()

        data.actual_size = get_folder_size_blocks(config.store_root)

        with Session(idx.engine) as session:
            # ── 文件数 / 文件夹数 / 总大小 ────────────────────────
            # 用 case() 在一次查询里同时统计三个值
            overview = session.exec(
                select(
                    func.sum(
                        case((col(File.is_folder) == False, 1), else_=0)
                    ),
                    func.sum(
                        case((col(File.is_folder) == True, 1), else_=0)
                    ),
                    func.coalesce(func.sum(File.size), 0),
                )
            ).one()
            data.total_files = int(overview[0] or 0)
            data.total_folders = int(overview[1] or 0)
            data.total_size = int(overview[2] or 0)

            # ── 标签总数 ──────────────────────────────────────────
            tag_count = session.exec(
                select(func.count(Tag.id))
            ).one()
            data.total_tags = int(tag_count or 0)

            # ── 扩展名分布（前 8）────────────────────────────────
            ext_rows = session.exec(
                select(File.ext, func.count(File.id))
                .where(col(File.is_folder) == False)  # noqa: E712
                .where(col(File.ext) != "")
                .group_by(col(File.ext))
                .order_by(func.count(File.id).desc())
                .limit(8)
            ).all()
            data.ext_counts = [
                (str(row[0]), int(row[1])) for row in ext_rows
            ]

            # ── 热门标签（前 10）─────────────────────────────────
            tag_rows = session.exec(
                select(Tag.name, func.count(FileTagLink.file_id))
                .join(FileTagLink, col(FileTagLink.tag_id) == col(Tag.id))
                .group_by(col(Tag.name))
                .order_by(func.count(FileTagLink.file_id).desc())
                .limit(10)
            ).all()
            data.top_tags = [
                (str(row[0]), int(row[1])) for row in tag_rows
            ]

            # ── 最近索引 ──────────────────────────────────────────
            recent = session.exec(
                select(File)
                .order_by(col(File.indexed_at).desc())
                .limit(1)
            ).first()
            if recent is not None:
                data.recent_file = recent.filename
                data.recent_time = (
                    recent.indexed_at.strftime("%Y-%m-%d %H:%M")
                    if recent.indexed_at is not None
                    else "—"
                )



        return data


# ── 统计窗口 ──────────────────────────────────────────────────

class StatsDialog(QDialog):
    """
    知识库统计窗口。
    列表式布局，每 30 秒自动刷新，也可手动刷新。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化统计窗口。"""
        super().__init__(parent)
        self.setWindowTitle("知识库统计")
        self.setMinimumSize(420, 560)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self._worker: StatsWorker | None = None
        self._thread: QThread | None = None
        self._setup_ui()
        self._apply_theme()

        # 自动刷新定时器
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(30_000)
        self._auto_timer.timeout.connect(self._load)
        self._auto_timer.start()

        # 首次加载
        self._load()

    def _setup_ui(self) -> None:
        """构建统计界面。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 标题栏
        root.addWidget(self._build_titlebar())

        # 进度条（加载时可见）
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(2)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { background: #1e1e1e; border: none; }"
            "QProgressBar::chunk { background: #2d5a8e; }"
        )
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # 可滚动内容区
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(20, 16, 20, 16)
        self._content_layout.setSpacing(0)
        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll)

        # 底部时间戳
        self._footer = QLabel("加载中…")
        self._footer.setStyleSheet(
            "color: #444; font-size: 11px; "
            "padding: 6px 20px; border-top: 1px solid #2a2a2a;"
        )
        root.addWidget(self._footer)

    def _build_titlebar(self) -> QWidget:
        """构建标题栏。"""
        bar = QWidget()
        bar.setStyleSheet("background: #1a1a1a;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 14, 16, 14)

        title = QLabel("知识库统计")
        title.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #e0e0e0;"
        )
        layout.addWidget(title)
        layout.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedWidth(54)
        refresh_btn.setStyleSheet(
            "background: #2a2a2a; color: #aaa; border: none; "
            "border-radius: 6px; padding: 5px 10px; font-size: 12px;"
        )
        refresh_btn.clicked.connect(self._load)
        layout.addWidget(refresh_btn)

        return bar

    # ── 数据加载 ──────────────────────────────────────────────
    def _load(self) -> None:
        """启动异步统计加载。"""
        if self._thread and self._thread.isRunning():
            return

        self._progress.setVisible(True)

        self._worker = StatsWorker()
        self._thread = QThread(self)
        assert isinstance(self._worker, StatsWorker) and isinstance(self._thread, QThread)
        self._worker.moveToThread(self._thread)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.data_ready.connect(self._thread.quit)
        self._thread.start()

    def _on_data_ready(self, data: StatsData) -> None:
        """数据加载完成，重建内容区。"""
        self._progress.setVisible(False)
        self._rebuild_content(data)
        self._footer.setText(
            f"上次更新：{datetime.now().strftime('%H:%M:%S')}  ·  每 30 秒自动刷新"
        )

    # ── 内容构建 ──────────────────────────────────────────────

    def _rebuild_content(self, data: StatsData) -> None:
        """清空并重建统计内容。"""
        # 清空旧内容
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item and (item_widget := item.widget()):
                item_widget.deleteLater()

        self._content_layout.addWidget(self._section("概览"))
        self._content_layout.addWidget(self._divider())
        self._content_layout.addLayout(
            self._build_overview(data)
        )

        self._content_layout.addSpacing(16)
        self._content_layout.addWidget(self._section("扩展名分布"))
        self._content_layout.addWidget(self._divider())
        self._content_layout.addLayout(
            self._build_bar_chart(data.ext_counts, suffix="个")
        )

        self._content_layout.addSpacing(16)
        self._content_layout.addWidget(self._section("热门标签"))
        self._content_layout.addWidget(self._divider())
        self._content_layout.addLayout(
            self._build_bar_chart(data.top_tags, prefix="#", suffix="个")
        )

        self._content_layout.addSpacing(16)
        self._content_layout.addWidget(self._section("最近索引"))
        self._content_layout.addWidget(self._divider())
        self._content_layout.addLayout(
            self._build_recent(data)
        )

        self._content_layout.addStretch()

    def _build_overview(self, data: StatsData) -> QVBoxLayout:
        """构建概览键值对。"""
        layout = QVBoxLayout()
        layout.setSpacing(6)

        rows = [
            ("文件总数", f"{data.total_files:,} 个"),
            ("文件夹数", f"{data.total_folders:,} 个"),
            ("总计大小", format_size(data.total_size)),
            ("占用空间", format_size(data.actual_size)),
            ("标签总数", f"{data.total_tags} 个"),
        ]
        for label, value in rows:
            layout.addWidget(self._kv_row(label, value))

        return layout

    def _build_bar_chart(
            self,
            items: list[tuple[str, int]],
            prefix: str = "",
            suffix: str = "",
    ) -> QVBoxLayout:
        """
        构建简易横向条形图。
        每行：标签/扩展名  ████░░░  数量
        """
        layout = QVBoxLayout()
        layout.setSpacing(5)

        if not items:
            empty = QLabel("暂无数据")
            empty.setStyleSheet("color: #555; font-size: 12px; padding: 4px 0;")
            layout.addWidget(empty)
            return layout

        max_count = max(count for _, count in items) or 1

        for name, count in items:
            row = QHBoxLayout()
            row.setSpacing(8)

            # 名称标签，固定宽度对齐
            name_lbl = QLabel(f"{prefix}{name}")
            name_lbl.setFixedWidth(110)
            name_lbl.setStyleSheet("color: #ccc; font-size: 12px;")
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(name_lbl)

            # 条形
            bar_container = QWidget()
            bar_container.setFixedHeight(14)
            bar_container.setFixedWidth(160)

            fill_width = int(160 * count / max_count)
            bar_bg = QFrame(bar_container)
            bar_bg.setGeometry(0, 2, 160, 10)
            bar_bg.setStyleSheet("background: #2a2a2a; border-radius: 5px;")

            bar_fill = QFrame(bar_container)
            bar_fill.setGeometry(0, 2, max(fill_width, 4), 10)
            bar_fill.setStyleSheet("background: #2d5a8e; border-radius: 5px;")

            row.addWidget(bar_container)

            # 数量
            count_lbl = QLabel(f"{count:,} {suffix}")
            count_lbl.setStyleSheet("color: #666; font-size: 11px;")
            row.addWidget(count_lbl)
            row.addStretch()

            layout.addLayout(row)

        return layout

    def _build_recent(self, data: StatsData) -> QVBoxLayout:
        """构建最近索引行。"""
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.addWidget(self._kv_row("文件名", data.recent_file))
        layout.addWidget(self._kv_row("时间", data.recent_time))
        return layout

    # ── 通用控件 ──────────────────────────────────────────────

    @staticmethod
    def _kv_row(label: str, value: str) -> QWidget:
        """构建键值对行。"""
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(12)

        lbl = QLabel(label)
        lbl.setFixedWidth(80)
        lbl.setStyleSheet(
            "color: #666; font-size: 12px;"
        )
        lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        val = QLabel(value)
        val.setStyleSheet("color: #d0d0d0; font-size: 13px;")
        val.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout.addWidget(lbl)
        layout.addWidget(val)
        layout.addStretch()
        return w

    @staticmethod
    def _section(title: str) -> QLabel:
        """分节标题。"""
        lbl = QLabel(title)
        lbl.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #555; "
            "padding-top: 6px; padding-bottom: 2px; letter-spacing: 1px;"
        )
        return lbl

    @staticmethod
    def _divider() -> QFrame:
        """水平分割线。"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2a2a2a; margin-bottom: 4px;")
        return line

    def _apply_theme(self) -> None:
        """应用深色主题。"""
        self.setStyleSheet("""
            QDialog   { background: #121212; color: #e0e0e0; }
            QScrollArea { background: transparent; border: none; }
            QWidget   { background: #121212; }
            QScrollBar:vertical {
                background: #1a1a1a; width: 5px; border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: #333; border-radius: 2px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """)

    def closeEvent(self, event) -> None:
        """关闭时停止自动刷新定时器。"""
        self._auto_timer.stop()
        super().closeEvent(event)
