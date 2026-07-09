# coding=utf-8
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QWidget, QSplitter, QTreeWidget, QVBoxLayout, QListWidget, QLabel, QTreeWidgetItem, \
    QListWidgetItem

from cairn.core.index.models import FileDTO
from cairn.ui.search_window.components.file_list_mixin import FileListMixin
from cairn.ui.search_window.style_constants import _tree_style, _list_style, _detail_style
from cairn.ui.search_window.tabs.search_tab import FileListWidget, ResultItem
from cairn.ui.search_window.tabs.time_line_tab import BrowseWorker
from cairn.utils.fmt_tools import format_detail
from cairn.utils.open_file import open_file


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
            open_file(item.dto)

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
