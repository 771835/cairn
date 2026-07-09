# coding=utf-8
from PySide6 import QtCore
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QSize, QTimer, QThread
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QStyledItemDelegate, QWidget, QSplitter, QListWidget, QVBoxLayout, QListView, QLabel, \
    QListWidgetItem

from cairn.core.index.models import FileDTO
from cairn.ui.search_window.components.file_list_mixin import FileListMixin
from cairn.ui.search_window.style_constants import _list_style, _status_style, _detail_style
from cairn.ui.search_window.tabs.time_line_tab import BrowseWorker
from cairn.utils.fmt_tools import format_detail
from cairn.utils.open_file import open_file


class FileDTOModel(QAbstractListModel):
    """
    FileDTO 虚拟列表模型。
    QListView 只渲染可见行。
    支持分批追加数据。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[FileDTO] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        """返回数据总行数。"""
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """返回指定行的显示数据。"""
        if not index.isValid() or index.row() >= len(self._items):
            return None
        dto = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            folder_mark = "📁 " if dto.is_folder else ""
            return f"{folder_mark}{dto.filename}"
        if role == Qt.ItemDataRole.ToolTipRole:
            return dto.path
        if role == Qt.ItemDataRole.UserRole:
            return dto
        return None

    def set_items(self, items: list[FileDTO]) -> None:
        """全量替换数据。"""
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def append_items(self, items: list[FileDTO]) -> None:
        """追加数据（分批加载用）。"""
        if not items:
            return
        start = len(self._items)
        end = start + len(items) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._items.extend(items)
        self.endInsertRows()

    def get_dto(self, index: QModelIndex) -> FileDTO | None:
        """根据 index 取 DTO。"""
        if not index.isValid():
            return None
        return self._items[index.row()]

    def clear(self) -> None:
        """清空数据。"""
        self.beginResetModel()
        self._items = []
        self.endResetModel()


class FileItemDelegate(QStyledItemDelegate):
    """
    QListView 自定义条目绘制。
    深色背景，选中高亮，和 QListWidget 风格保持一致。
    """

    def sizeHint(self, option, index) -> QSize:
        """每行高度固定 36px。"""
        return QSize(option.rect.width(), 36)

    def paint(
            self,
            painter: QPainter,
            option,
            index: QModelIndex,
    ) -> None:
        """绘制条目背景和文字。"""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(4, 2, -4, -2)

        # 背景
        selected = bool(
            option.state
            & __import__(
                "PySide6.QtWidgets", fromlist=["QStyle"]
            ).QStyle.StateFlag.State_Selected
        )
        hovered = bool(
            option.state
            & __import__(
                "PySide6.QtWidgets", fromlist=["QStyle"]
            ).QStyle.StateFlag.State_MouseOver
        )

        if selected:
            painter.setBrush(QColor("#2d5a8e"))
        elif hovered:
            painter.setBrush(QColor("#2a2a2a"))
        else:
            painter.setBrush(QColor("#1e1e1e"))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 4, 4)

        # 文字
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.setPen(QPen(QColor("#d0d0d0")))
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(
            rect.adjusted(8, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.restore()


class TagTab(QWidget, FileListMixin):
    """标签视图，使用虚拟列表支持大量文件。"""

    _BATCH_SIZE = 50  # 每批渲染条数

    def __init__(self) -> None:
        super().__init__()
        self._all_files: list[FileDTO] = []
        self._loaded_idx: int = 0
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(16)  # ~60fps 分批追加
        self._load_timer.timeout.connect(self._load_next_batch)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建标签视图界面。"""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self._tag_list = QListWidget()
        self._tag_list.setStyleSheet(_list_style())
        self._tag_list.currentItemChanged.connect(self._on_tag_select)
        self._tag_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tag_list.customContextMenuRequested.connect(self._show_blank_menu)

        splitter.addWidget(self._tag_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 虚拟列表替换 QListWidget
        self._model = FileDTOModel()
        self._file_view = QListView()
        self._file_view.setModel(self._model)
        self._file_view.setItemDelegate(FileItemDelegate())
        self._file_view.setMouseTracking(True)  # 悬停高亮需要
        self._file_view.setStyleSheet(
            "QListView { background: #1e1e1e; border: none; outline: none; }"
        )
        self._file_view.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection  # 多选
        )
        self._file_view.activated.connect(self._open_item)
        self._file_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._file_view.customContextMenuRequested.connect(
            self._on_context_menu
        )
        right_layout.addWidget(self._file_view)

        self._status = QLabel()
        self._status.setStyleSheet(_status_style())
        right_layout.addWidget(self._status)

        self._detail = QLabel()
        self._detail.setStyleSheet(_detail_style())
        self._detail.setWordWrap(True)
        right_layout.addWidget(self._detail)

        self._file_view.selectionModel().currentChanged.connect(
            self._on_selection
        )

        splitter.addWidget(right)
        splitter.setSizes([180, 620])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def load(self) -> None:
        """异步加载标签列表。"""
        self._worker = BrowseWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.load_tags)
        self._worker.tag_list_ready.connect(self._build_tags)
        self._worker.tag_list_ready.connect(self._thread.quit)
        self._thread.start()

    def _build_tags(self, tags: list[tuple[str, str, int]]) -> None:
        """渲染标签列表。"""
        self._tag_list.clear()
        for name, display_name, count in tags:
            item = QListWidgetItem(f"{display_name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setData(Qt.ItemDataRole.DisplayRole, display_name)
            self._tag_list.addItem(item)

    def _on_tag_select(
            self,
            current: QListWidgetItem | None,
            previous: QListWidgetItem | None,
    ) -> None:
        """点击标签，异步加载文件，分批渲染。"""
        if current is None:
            return

        # 停止上一次分批加载
        self._load_timer.stop()
        self._model.clear()
        self._all_files = []
        self._loaded_idx = 0

        tag = current.data(Qt.ItemDataRole.UserRole)
        self._status.setText("加载中…")

        self._file_worker = BrowseWorker()
        self._file_thread = QThread(self)
        self._file_worker.moveToThread(self._file_thread)
        self._file_thread.started.connect(
            lambda: self._file_worker.load_tag_files(tag)
        )
        self._file_worker.tag_files_ready.connect(self._on_files_loaded)
        self._file_worker.tag_files_ready.connect(self._file_thread.quit)
        self._file_thread.start()

    def _on_files_loaded(self, files: list[FileDTO]) -> None:
        """文件加载完成，启动分批渲染。"""
        self._all_files = files
        self._loaded_idx = 0
        self._status.setText(f"共 {len(files)} 个文件，加载中…")
        self._load_timer.start()

    def _load_next_batch(self) -> None:
        """每帧追加一批数据到虚拟列表。"""
        batch = self._all_files[
            self._loaded_idx: self._loaded_idx + self._BATCH_SIZE
        ]
        if not batch:
            self._load_timer.stop()
            self._status.setText(f"共 {len(self._all_files)} 个文件")
            return
        self._model.append_items(batch)
        self._loaded_idx += len(batch)

    def _on_selection(
            self,
            current: QModelIndex,
            previous: QModelIndex,
    ) -> None:
        """更新底部详情。"""
        dto = self._model.get_dto(current)
        if dto:
            self._detail.setText(format_detail(dto))

    def _open_item(self, index: QModelIndex) -> None:
        """双击打开文件。"""
        dto = self._model.get_dto(index)
        if dto:
            open_file(dto)

    def _refresh_tag_list(self) -> None:
        """仅刷新左侧标签列表，保留当前选中的标签。"""
        # 记住当前选中的标签名
        current_item = self._tag_list.currentItem()
        current_tag = (
            current_item.data(Qt.ItemDataRole.UserRole)
            if current_item else None
        )

        self._worker = BrowseWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.load_tags)
        self._worker.tag_list_ready.connect(
            lambda tags: self._rebuild_tag_list(tags, current_tag)
        )
        self._worker.tag_list_ready.connect(self._thread.quit)
        self._thread.start()

    def _rebuild_tag_list(
            self,
            tags: list[tuple[str, int]],
            restore_tag: str | None,
    ) -> None:
        """重建标签列表并恢复选中状态。"""
        self._tag_list.clear()
        restore_row = 0
        for i, (name, display_name, count) in enumerate(tags):
            item = QListWidgetItem(f"#{display_name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._tag_list.addItem(item)
            if name == restore_tag:
                restore_row = i

        if self._tag_list.count() > 0:
            self._tag_list.setCurrentRow(restore_row)

    def _get_selected_dtos(self) -> list[FileDTO | None]:
        """返回当前选中条目的 DTO 列表。"""
        return [
            self._model.get_dto(index)
            for index in self._file_view.selectedIndexes()
            if isinstance(index, QModelIndex)
        ]

    def refresh(self) -> None:
        """刷新标签列表。"""
        self.load()

    def _remove_dtos_from_view(self, dtos: list[FileDTO]) -> None:
        """从虚拟列表移除条目，标签选中不变。"""
        ids = {d.id for d in dtos}
        # 同步更新 _all_files 缓存
        self._all_files = [f for f in self._all_files if f.id not in ids]

        # 找出需要移除的 model 行（倒序移除避免下标偏移）
        rows_to_remove = [
            row for row in range(self._model.rowCount())
            if (dto := self._model.get_dto(
                self._model.index(row)
            )) is not None and dto.id in ids
        ]
        for row in sorted(rows_to_remove, reverse=True):
            self._model.beginRemoveRows(
                QtCore.QModelIndex(), row, row
            )
            self._model._items.pop(row)  # NOQA
            self._model.endRemoveRows()

        self._status.setText(f"共 {len(self._all_files)} 个文件")

    def _on_item_updated(self, dto: FileDTO) -> None:
        """
        条目标签变化后：
        1. 刷新详情栏
        2. 异步刷新左侧标签列表计数
        """
        # 详情栏
        indexes = self._file_view.selectedIndexes()
        for idx in indexes:
            d = self._model.get_dto(idx)
            if d is not None and d.id == dto.id:
                self._detail.setText(format_detail(dto))
                break

        # 只刷标签列表，不动文件列表
        self._refresh_tag_list()
