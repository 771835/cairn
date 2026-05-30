# coding=utf-8
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6 import QtCore
from PySide6.QtCore import (
    Qt, QTimer, Signal, QThread, QObject, QEvent,
    QMimeData, QUrl, QPoint, QModelIndex, QAbstractListModel, QSize
)
from PySide6.QtGui import (
    QPainter, QColor, QDrag, QPen, QFont,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem, QLabel,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QSplitter,
    QListView, QStyledItemDelegate,
)

from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.core.index.search import SearchQuery, SearchResult
from cairn.ui.file_list_mixin import FileListMixin
from cairn.utils.fmt_tools import format_detail
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


# ── 异步 Worker ───────────────────────────────────────────────

class SearchWorker(QObject):
    """在独立线程中执行搜索，避免阻塞 UI。"""

    results_ready: Signal = Signal(list)

    def __init__(self, query: SearchQuery) -> None:
        super().__init__()
        self._query = query

    def run(self) -> None:
        """执行搜索并发出结果信号。"""
        try:
            results = IndexManager().search(self._query)
            self.results_ready.emit(results)
        except Exception as e:
            logger.error(f"搜索失败：{e}")
            self.results_ready.emit([])


class BrowseWorker(QObject):
    """在独立线程中加载浏览数据。"""

    folder_tree_ready: Signal = Signal(dict)
    tag_list_ready: Signal = Signal(list)  # list[(tag, count)]
    tag_files_ready: Signal = Signal(list)  # list[FileDTO]
    timeline_ready: Signal = Signal(dict)  # dict[str, list[FileDTO]]

    def load_folder_tree(self) -> None:
        """加载文件夹树数据。"""
        try:
            tree = IndexManager().get_folder_tree()
            self.folder_tree_ready.emit(tree)
        except Exception as e:
            logger.error(f"加载文件夹树失败：{e}")

    def load_tags(self) -> None:
        """加载标签列表。"""
        try:
            tags = IndexManager().get_all_tags()
            self.tag_list_ready.emit(tags)
        except Exception as e:
            logger.error(f"加载标签列表失败：{e}")

    def load_tag_files(self, tag: str) -> None:
        """加载指定标签下的文件。"""
        try:
            files = IndexManager().get_by_tag(tag)
            self.tag_files_ready.emit(files)
        except Exception as e:
            logger.error(f"加载标签文件失败：{e}")

    def load_timeline(self) -> None:
        """加载时间线数据。"""
        try:
            groups = IndexManager().get_by_indexed_date()
            self.timeline_ready.emit(groups)
        except Exception as e:
            logger.error(f"加载时间线失败：{e}")


# ── 文件列表条目（可拖拽）────────────────────────────────────

class FileListWidget(QListWidget):
    """
    支持拖出文件到系统的列表控件。
    拖动时临时复制哈希文件到 %TEMP%/cairn_drag/，
    用原始文件名命名后发起系统拖放。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self._drag_start: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        """记录拖拽起始位置。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """左键拖动超过阈值时发起拖放。"""
        if (
                event.buttons() & Qt.MouseButton.LeftButton  # NOQA
                and self._drag_start is not None
                and (event.pos() - self._drag_start).manhattanLength() > 10
        ):
            self._start_drag()
        super().mouseMoveEvent(event)

    def _start_drag(self) -> None:
        """准备临时文件并发起系统拖放。"""
        items = self.selectedItems()
        if not items:
            return

        tmp_dir = Path(tempfile.gettempdir()) / "cairn_drag"
        tmp_dir.mkdir(exist_ok=True)

        urls: list[QUrl] = []
        for item in items:
            if not isinstance(item, ResultItem):
                continue

            f = item.dto
            hash_path = IndexManager().get_store_path(f.file_hash)
            if not hash_path or not hash_path.exists():
                continue

            # 临时目录下用原始文件名
            tmp_file = tmp_dir / f.filename
            shutil.copy2(str(hash_path), str(tmp_file))
            urls.append(QUrl.fromLocalFile(str(tmp_file)))

        if not urls:
            return

        mime = QMimeData()
        mime.setUrls(urls)

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

        # 拖放结束后清理临时文件
        for url in urls:
            try:
                Path(url.toLocalFile()).unlink(missing_ok=True)
            except OSError:
                pass


class ResultItem(QListWidgetItem):
    """文件列表条目，持有 FileDTO。"""

    def __init__(self, dto: FileDTO, snippet: str = "") -> None:
        super().__init__()
        self.dto = dto
        self.snippet = snippet
        folder_mark = "📁 " if dto.is_folder else ""
        self.setText(f"{folder_mark}{dto.filename}")
        self.setToolTip(dto.path)


# ── 虚拟列表模型 ────────────────────────────────────────────────

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


# ── 各视图 Tab ────────────────────────────────────────────────

class SearchTab(QWidget, FileListMixin):
    """搜索视图。"""

    def __init__(self) -> None:
        super().__init__()
        self._search_thread: QThread | None = None
        self._worker: SearchWorker | None = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建搜索界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "搜索知识库…   #标签   .扩展名   普通文本"
        )
        self._input.setStyleSheet(_input_style())
        self._input.textChanged.connect(lambda _: self._debounce.start(300))
        self._input.installEventFilter(self)
        layout.addWidget(self._input)

        self._list = FileListWidget()
        self._list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection  # 多选
        )
        self._list.setStyleSheet(_list_style())
        self._list.itemActivated.connect(self._open_item)
        self._list.currentItemChanged.connect(self._on_selection)
        self._list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

        self._status = QLabel("输入关键词开始搜索")
        self._status.setStyleSheet(_status_style())
        layout.addWidget(self._status)

        self._detail = QLabel()
        self._detail.setStyleSheet(_detail_style())
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

    def focus_input(self) -> None:
        """聚焦搜索输入框。"""
        self._input.setFocus()
        self._input.selectAll()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """输入框键盘拦截。"""
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            key = event.key()  # NOQA
            if key == Qt.Key.Key_Down:
                self._list.setFocus()
                if self._list.count() > 0:
                    self._list.setCurrentRow(0)
                return True
            if key == Qt.Key.Key_Return:
                self._open_current()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        """ESC 关闭窗口。"""
        if event.key() == Qt.Key.Key_Escape:
            self.window().hide()
        else:
            super().keyPressEvent(event)

    def _do_search(self) -> None:
        """执行异步搜索。"""
        raw = self._input.text().strip()
        if not raw:
            self._list.clear()
            self._status.setText("输入关键词开始搜索")
            return

        query = _parse_query(raw)
        self._status.setText("搜索中…")

        if self._search_thread is not None and self._search_thread.isRunning():
            self._search_thread.quit()
            self._search_thread.wait(300)

        worker = SearchWorker(query)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.results_ready.connect(self._on_results)
        worker.results_ready.connect(thread.quit)
        self._worker = worker
        self._search_thread = thread
        thread.start()

    def _on_results(self, results: list[SearchResult]) -> None:
        """渲染搜索结果。"""
        self._list.clear()
        if not results:
            self._status.setText("无匹配结果")
            return
        for r in results:
            self._list.addItem(ResultItem(r.file, r.snippet))
        self._status.setText(f"{len(results)} 个结果")
        self._list.setCurrentRow(0)

    def _on_selection(
            self,
            current: QListWidgetItem | None,
            previous: QListWidgetItem | None,
    ) -> None:
        """更新底部详情。"""
        if not isinstance(current, ResultItem):
            self._detail.setText("")
            return
        self._detail.setText(format_detail(current.dto, current.snippet))

    def _open_current(self) -> None:
        """打开当前选中文件。"""
        item = self._list.currentItem()
        if isinstance(item, ResultItem):
            _open_file(item.dto, self._status)

    def _open_item(self, item: QListWidgetItem) -> None:
        """双击打开文件。"""
        if isinstance(item, ResultItem):
            _open_file(item.dto, self._status)

    def _get_selected_dtos(self) -> list[FileDTO]:
        """返回当前选中条目的 DTO 列表。"""
        return [
            item.dto
            for item in self._list.selectedItems()
            if isinstance(item, ResultItem)
        ]

    def refresh(self) -> None:
        """刷新搜索结果"""
        self._do_search()

    def _remove_dtos_from_view(self, dtos: list[FileDTO]) -> None:
        """直接从列表移除条目，不重新搜索。"""
        ids = {d.id for d in dtos}
        for row in range(self._list.count() - 1, -1, -1):
            item = self._list.item(row)
            if isinstance(item, ResultItem) and item.dto.id in ids:
                self._list.takeItem(row)
        count = self._list.count()
        self._status.setText(f"{count} 个结果")

    def _on_item_updated(self, dto: FileDTO) -> None:
        """条目数据更新后，若该条目当前选中则刷新详情栏。"""
        current = self._list.currentItem()
        if isinstance(current, ResultItem) and current.dto.id == dto.id:
            self._detail.setText(format_detail(dto, current.snippet))


class FolderTab(QWidget, FileListMixin):
    """文件夹树视图。"""

    def __init__(self) -> None:
        super().__init__()
        self._thread = None
        self._worker = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建文件夹树界面。"""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # 左侧目录树
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(_tree_style())
        self._tree.currentItemChanged.connect(self._on_tree_select)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_blank_menu)
        splitter.addWidget(self._tree)

        # 右侧文件列表
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 右侧文件列表
        self._file_list = FileListWidget()
        self._file_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection  # 多选
        )
        self._file_list.setStyleSheet(_list_style())
        self._file_list.itemActivated.connect(self._open_item)
        self._file_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._file_list.customContextMenuRequested.connect(
            self._on_context_menu
        )
        right_layout.addWidget(self._file_list)

        self._detail = QLabel()
        self._detail.setStyleSheet(_detail_style())
        self._detail.setWordWrap(True)
        right_layout.addWidget(self._detail)

        splitter.addWidget(right)
        splitter.setSizes([220, 580])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def load(self) -> None:
        """异步加载文件夹树。"""
        self._worker = BrowseWorker()  # 保存到 self，防止 GC
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.load_folder_tree)
        self._worker.folder_tree_ready.connect(self._build_tree)
        self._worker.folder_tree_ready.connect(self._thread.quit)
        self._thread.start()

    def _build_tree(self, tree_data: dict) -> None:
        """根据树数据构建 QTreeWidget。"""
        self._tree.clear()

        def add_node(parent, node: dict):
            item = QTreeWidgetItem(parent)
            item.setText(0, node["name"])
            item.setData(0, Qt.ItemDataRole.UserRole, node)
            for child in node["children"].values():
                add_node(item, child)

        for child in tree_data["children"].values():
            add_node(self._tree, child)

        self._tree.expandToDepth(1)

    def _on_tree_select(
            self,
            current: QTreeWidgetItem | None,
            previous: QTreeWidgetItem | None,
    ) -> None:
        """点击目录节点，显示该目录下的文件。"""
        if current is None:
            return
        node: dict = current.data(0, Qt.ItemDataRole.UserRole)
        self._file_list.clear()
        for dto in node.get("files", []):
            self._file_list.addItem(ResultItem(dto))

    def _open_item(self, item: QListWidgetItem) -> None:
        """双击打开文件。"""
        if isinstance(item, ResultItem):
            _open_file(item.dto)

    def _get_selected_dtos(self) -> list[FileDTO]:
        """返回当前选中条目的 DTO 列表。"""
        return [
            item.dto
            for item in self._file_list.selectedItems()
            if isinstance(item, ResultItem)
        ]

    def refresh(self) -> None:
        """刷新文件夹树。"""
        self.load()

    def _remove_dtos_from_view(self, dtos: list[FileDTO]) -> None:
        """从右侧文件列表移除条目，目录树不动。"""
        ids = {d.id for d in dtos}
        for row in range(self._file_list.count() - 1, -1, -1):
            item = self._file_list.item(row)
            if isinstance(item, ResultItem) and item.dto.id in ids:
                self._file_list.takeItem(row)

    def _on_item_updated(self, dto: FileDTO) -> None:
        """条目数据更新后，刷新选中条目的详情栏。"""
        current = self._file_list.currentItem()
        if isinstance(current, ResultItem) and current.dto.id == dto.id:
            self._detail.setText(format_detail(dto))


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

    def _build_tags(self, tags: list[tuple[str, int]]) -> None:
        """渲染标签列表。"""
        self._tag_list.clear()
        for name, count in tags:
            item = QListWidgetItem(f"#{name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, name)
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
            _open_file(dto)

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
        for i, (name, count) in enumerate(tags):
            item = QListWidgetItem(f"#{name}  ({count})")
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


class TimelineTab(QWidget, FileListMixin):
    """时间线视图。"""

    def __init__(self) -> None:
        super().__init__()
        self._thread = None
        self._worker = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建时间线界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(_tree_style())
        self._tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._tree.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection  # 多选
        )
        self._tree.customContextMenuRequested.connect(
            self._on_context_menu
        )
        self._tree.itemActivated.connect(self._open_item)
        layout.addWidget(self._tree)

        self._detail = QLabel()
        self._detail.setStyleSheet(_detail_style())
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

    def load(self) -> None:
        """异步加载时间线。"""
        self._worker = BrowseWorker()  # 保存到 self，防止 GC
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.load_timeline)
        self._worker.timeline_ready.connect(self._build_timeline)
        self._worker.timeline_ready.connect(self._thread.quit)
        self._thread.start()

    def _build_timeline(self, groups: dict[str, list[FileDTO]]) -> None:
        """渲染时间线树。"""
        self._tree.clear()
        for group_name, files in groups.items():
            if not files:
                continue
            group_item = QTreeWidgetItem(self._tree)
            group_item.setText(0, f"{group_name}  ({len(files)})")
            group_item.setData(0, Qt.ItemDataRole.UserRole, None)
            for dto in files:
                child = QTreeWidgetItem(group_item)
                child.setText(0, dto.filename)
                child.setToolTip(0, dto.path)
                child.setData(0, Qt.ItemDataRole.UserRole, dto)
            group_item.setExpanded(group_name == "今天")

    def _open_item(self, item: QTreeWidgetItem) -> None:
        """双击打开文件。"""
        dto = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(dto, FileDTO):
            _open_file(dto)

    def _get_selected_dtos(self) -> list[FileDTO]:
        """返回当前选中条目的 DTO 列表。"""
        return [
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self._tree.selectedItems()
            if isinstance(item, QTreeWidgetItem)
        ]

    def refresh(self) -> None:
        """刷新时间线。"""
        self.load()

    def _remove_dtos_from_view(self, dtos: list[FileDTO]) -> None:
        """移除时间线叶节点，更新分组计数。"""
        ids = {d.id for d in dtos}
        root = self._tree.invisibleRootItem()

        for g in range(root.childCount()):
            group_item = root.child(g)
            if group_item is None:
                continue

            # 倒序移除子节点
            for c in range(group_item.childCount() - 1, -1, -1):
                child = group_item.child(c)
                if child is None:
                    continue
                dto = child.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(dto, FileDTO) and dto.id in ids:
                    group_item.removeChild(child)

            # 更新分组标题计数
            remaining = group_item.childCount()
            name = group_item.text(0).split("  ")[0]
            group_item.setText(0, f"{name}  ({remaining})")

    def _on_item_updated(self, dto: FileDTO) -> None:
        """条目数据更新后刷新详情栏。"""
        current = self._tree.currentItem()
        if current is not None:
            d = current.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(d, FileDTO) and d.id == dto.id:
                self._detail.setText(format_detail(dto))

# ── 主窗口 ────────────────────────────────────────────────────

class SearchWindow(QWidget):
    """
    Cairn 主搜索与浏览窗口。

    Tab 布局：[搜索] [文件夹] [标签] [时间线]
    全局快捷键或托盘点击呼出，ESC 隐藏。
    """

    debug = False

    def __init__(self) -> None:
        super().__init__()
        self._setup_window()
        self._setup_ui()

    def _setup_window(self) -> None:
        """配置无边框透明窗口。"""
        if not self.debug:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(900, 600)

    def _setup_ui(self) -> None:
        """构建主界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_tab_style())

        self._search_tab = SearchTab()
        self._folder_tab = FolderTab()
        self._tag_tab = TagTab()
        self._timeline_tab = TimelineTab()

        self._tabs.addTab(self._search_tab, "🔍  搜索")
        self._tabs.addTab(self._folder_tab, "📁  文件夹")
        self._tabs.addTab(self._tag_tab, "🏷  标签")
        self._tabs.addTab(self._timeline_tab, "🕐  时间线")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs)

    def paintEvent(self, event) -> None:
        """绘制半透明深色圆角背景。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(18, 18, 18, 245))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 14, 14)

    def show_and_focus(self) -> None:
        """居中显示并聚焦搜索框。"""
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 3,
        )
        self.show()
        self.raise_()
        self.activateWindow()
        self._tabs.setCurrentIndex(0)
        self._search_tab.focus_input()

    def keyPressEvent(self, event) -> None:
        """ESC 隐藏窗口。"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def _on_tab_changed(self, index: int) -> None:
        """切换 Tab 时按需加载数据。"""
        if index == 1:
            self._folder_tab.load()
        elif index == 2:
            self._tag_tab.load()
        elif index == 3:
            self._timeline_tab.load()


# ── 共享工具函数 ──────────────────────────────────────────────

def _open_file(dto: FileDTO, status: QLabel | None = None) -> None:
    """用系统默认程序打开文件。"""
    store_path = IndexManager().get_store_path(dto.file_hash)
    path = store_path if store_path and store_path.exists() else None

    if path is None:
        msg = f"文件不存在：{dto.filename}"
        logger.warning(msg)
        if status:
            status.setText(msg)
        return

    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.run(["xdg-open", str(path)])


def _parse_query(raw: str) -> SearchQuery:
    """解析搜索前缀语法。"""
    tags: list[str] = []
    exts: list[str] = []
    words: list[str] = []

    for token in re.split(r'[;, /\\]', raw):
        if token.startswith("#"):
            tags.append(token[1:].lower())
        elif token.startswith("."):
            exts.append(token[1:].lower())
        else:
            words.append(token)

    return SearchQuery(text=" ".join(words), tags=tags, ext=exts, limit=30)


# ── 样式常量 ──────────────────────────────────────────────────

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
