# coding=utf-8
from PySide6.QtCore import QObject, Signal, Qt, QThread
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QListWidget, QLabel, QTreeWidgetItem

from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.ui.search_window.components.file_list_mixin import FileListMixin
from cairn.ui.search_window.style_constants import _tree_style, _detail_style
from cairn.utils.fmt_tools import format_detail
from cairn.utils.logger import get_logger
from cairn.utils.open_file import open_file

logger = get_logger(__name__)


class BrowseWorker(QObject):
    """在独立线程中加载浏览数据。"""

    folder_tree_ready: Signal = Signal(dict)
    tag_list_ready: Signal = Signal(list)  # list[(tag, display_name, count)]
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
            tags = IndexManager().get_all_tags_and_display_name()
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
            open_file(dto)

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
        ids = {d.id for d in dtos if d}
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
