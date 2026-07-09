# coding=utf-8
import re
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QPoint, Qt, QUrl, QMimeData, QThread, QTimer, QEvent
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QVBoxLayout, QLineEdit, QLabel

from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.core.index.search import SearchQuery, SearchResult
from cairn.ui.search_window.components.file_list_mixin import FileListMixin
from cairn.ui.search_window.style_constants import _input_style, _list_style, _status_style, _detail_style
from cairn.utils.fmt_tools import format_detail
from cairn.utils.logger import get_logger
from cairn.utils.open_file import open_file

logger = get_logger(__name__)


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
            open_file(item.dto, self._status)

    def _open_item(self, item: QListWidgetItem) -> None:
        """双击打开文件。"""
        if isinstance(item, ResultItem):
            open_file(item.dto, self._status)

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
