# coding=utf-8
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QDateTime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QDateTimeEdit,
    QWidget, QFrame, QScrollArea,
    QPushButton, QApplication,
)
from charset_normalizer import from_bytes

from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.ui.widgets import TagEditor
from cairn.utils.fmt_tools import format_size, format_path
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


def _is_text_file(path: Path) -> bool:
    """判断文件是否为可显示的文本文件。"""
    try:
        # 读取前 8KB 进行检查
        with open(path, "rb") as f:
            chunk = f.read(8192)

        # 简单过滤：如果包含 NULL 字节，通常视为二进制文件
        if b"\x00" in chunk:
            return False

        # 进阶：使用 charset-normalizer 验证是否为文本
        # 如果置信度太低，也可以认为是二进制
        res = from_bytes(chunk).best()
        if res and res.chaos < 0.5:  # chaos 是混乱度，越低越像文本
            return True

        return False
    except OSError:
        return False


def _read_text_preview(path: Path, max_chars: int = 4000) -> str | None:
    """
    读取文本文件前 N 个字符作为预览。自动识别编码。
    """
    if not _is_text_file(path):
        return None

    try:
        # 只读取前 64KB 用于识别编码，避免大文件读取过慢
        raw_data = path.read_bytes()[:64 * 1024]

        # 使用 charset-normalizer 检测编码
        result = from_bytes(raw_data).best()

        if result and result.encoding:
            encoding = result.encoding
            # 使用检测到的编码读取全文件
            text = path.read_text(encoding=encoding)
        else:
            # 如果检测失败，尝试用 utf-8 兜底
            text = path.read_text(encoding="utf-8", errors="replace")

        # 截断逻辑
        if len(text) > max_chars:
            return text[:max_chars] + "\n\n... (已截断)"
        return text

    except Exception as e:
        logger.debug(f"内容预览读取失败：{e}")
        return None


def _to_qdatetime(dt: datetime | None) -> QDateTime:
    """将 Python datetime 转为 QDateTime。"""
    if dt is None:
        return QDateTime.currentDateTime()
    return QDateTime(
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute, dt.second,
    )


def _from_qdatetime(qdt: QDateTime) -> datetime:
    """将 QDateTime 转为 Python datetime。"""
    d = qdt.date()
    t = qdt.time()
    return datetime(
        d.year(), d.month(), d.day(),
        t.hour(), t.minute(), t.second(),
    )


def _section(title: str) -> QLabel:
    """分节标题样式。"""
    lbl = QLabel(title)
    lbl.setStyleSheet(
        "font-size: 11px; font-weight: bold; "
        "color: #888; padding-top: 8px; padding-bottom: 2px;"
    )
    return lbl


def _divider() -> QFrame:
    """水平分割线。"""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #333;")
    return line


class _ReadOnlyField(QLineEdit):
    """只读但可选中复制的输入框。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        """初始化只读字段。"""
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setStyleSheet(
            "background: #1a1a1a; color: #888; "
            "border: 1px solid #333; border-radius: 4px; padding: 4px 8px;"
        )


class _EditField(QLineEdit):
    """可编辑输入框。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        """初始化可编辑字段。"""
        super().__init__(text, parent)
        self.setStyleSheet(
            "background: #2b2b2b; color: #e0e0e0; "
            "border: 1px solid #555; border-radius: 4px; padding: 4px 8px;"
        )


class _MetadataField(QLineEdit):
    """metadata 键值展示，等宽字体。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setStyleSheet(
            "background: #1a1a1a; color: #aaa; "
            "border: 1px solid #333; border-radius: 4px; padding: 4px 8px; "
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 12px;"
        )


class FileDetailDialog(QDialog):
    """
    文件详情与编辑窗口。

    只读字段：文件名、扩展名、大小、哈希、引用数、存储路径
    可编辑字段：原始路径、修改时间、索引时间、标签、注释、摘要
    """

    def __init__(self, dto: FileDTO, parent: QWidget | None = None) -> None:
        """初始化详情窗口。"""
        super().__init__(parent)
        self._dto = dto
        self.setWindowTitle(f"详情  —  {dto.filename}")
        self.setMinimumSize(520, 640)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._setup_ui()
        self._apply_theme()

    @staticmethod
    def _parse_features(features_raw: str | None) -> dict:
        """将 features 字段的 JSON 字符串解析为 dict，失败返回空 dict。"""
        if not features_raw:
            return {}
        try:
            return json.loads(features_raw)
        except json.JSONDecodeError:
            return {}

    def _setup_ui(self) -> None:
        """构建完整详情界面。"""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 16)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 8, 20, 8)
        content_layout.setSpacing(4)

        content_layout.addWidget(_section("基本信息"))
        content_layout.addWidget(_divider())
        content_layout.addLayout(self._build_readonly_section())

        content_layout.addWidget(_section("路径"))
        content_layout.addWidget(_divider())
        content_layout.addLayout(self._build_path_section())

        content_layout.addWidget(_section("时间"))
        content_layout.addWidget(_divider())
        content_layout.addLayout(self._build_time_section())

        content_layout.addWidget(_section("标签"))
        content_layout.addWidget(_divider())
        self._tag_editor = TagEditor(self._dto.tags)
        content_layout.addWidget(self._tag_editor)

        content_layout.addWidget(_section("注释"))
        content_layout.addWidget(_divider())
        self._comment_edit = QTextEdit()
        self._comment_edit.setPlainText(self._dto.comment or "")
        self._comment_edit.setFixedHeight(80)
        self._comment_edit.setStyleSheet(
            "background: #2b2b2b; color: #e0e0e0; "
            "border: 1px solid #555; border-radius: 4px; padding: 4px;"
        )
        content_layout.addWidget(self._comment_edit)

        content_layout.addWidget(_section("摘要"))
        content_layout.addWidget(_divider())
        self._summary_edit = QTextEdit()
        self._summary_edit.setPlainText(self._dto.summary or "")
        self._summary_edit.setFixedHeight(100)
        self._summary_edit.setStyleSheet(
            "background: #2b2b2b; color: #e0e0e0; "
            "border: 1px solid #555; border-radius: 4px; padding: 4px;"
        )
        content_layout.addWidget(self._summary_edit)

        metadata = self._parse_features(self._dto.features)
        if metadata:
            content_layout.addWidget(_section("元数据 (Metadata)"))
            content_layout.addWidget(_divider())
            content_layout.addLayout(self._build_metadata_section(metadata))

        # ── 新增：文本内容预览（读原文件，仅文本文件） ──
        preview_text = self._load_file_preview()
        if preview_text is not None:
            content_layout.addWidget(_section("文件内容预览（只读）"))
            content_layout.addWidget(_divider())
            preview = QTextEdit()
            preview.setPlainText(preview_text)
            preview.setReadOnly(True)
            preview.setFixedHeight(180)
            preview.setStyleSheet(
                "background: #1a1a1a; color: #666; "
                "border: 1px solid #333; border-radius: 4px; padding: 4px; "
                "font-family: 'Consolas', 'Courier New', monospace; font-size: 11px;"
            )
            content_layout.addWidget(preview)

        content_layout.addStretch()
        scroll.setWidget(content)
        root_layout.addWidget(scroll)
        root_layout.addWidget(self._build_footer())

        content_layout.addStretch()
        scroll.setWidget(content)
        root_layout.addWidget(scroll)
        root_layout.addWidget(self._build_footer())

    def _load_file_preview(self) -> str | None:
        """
        从物理存储路径读取文件内容预览。
        仅文本文件返回内容，二进制文件返回 None。
        """
        # 优先用 store path（哈希存储路径）
        store_path = None
        if self._dto.file_hash:
            store_path = IndexManager().get_store_path(self._dto.file_hash)
        # 回退到记录的 path
        file_path = store_path or Path(self._dto.path)

        if not file_path.exists():
            return None

        return _read_text_preview(file_path)

    def _build_metadata_section(self, metadata: dict) -> QFormLayout:
        """构建 metadata 键值对展示区。"""
        form = QFormLayout()
        form.setSpacing(4)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        for key, value in metadata.items():
            # 跳过 summary（已在上面的摘要区展示）
            if key == "summary":
                continue
            # 格式化显示值
            if isinstance(value, list):
                display = ", ".join(str(v) for v in value)
            elif isinstance(value, dict):
                display = json.dumps(value, ensure_ascii=False, indent=2)
                # 多行 dict 用 QTextEdit
                val_widget = QTextEdit()
                val_widget.setPlainText(display)
                val_widget.setReadOnly(True)
                val_widget.setFixedHeight(min(24 * display.count("\n") + 40, 120))
                val_widget.setStyleSheet(
                    "background: #1a1a1a; color: #aaa; "
                    "border: 1px solid #333; border-radius: 4px; padding: 4px; "
                    "font-family: 'Consolas', 'Courier New', monospace; font-size: 11px;"
                )
                form.addRow(f"{key}", val_widget)
                continue
            elif isinstance(value, bool):
                display = "✓" if value else "✗"
            else:
                display = str(value)

            form.addRow(f"{key}", _MetadataField(display))

        return form

    def _build_header(self) -> QWidget:
        """构建顶部文件名标题栏。"""
        header = QWidget()
        header.setStyleSheet("background: #1e1e1e;")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(2)

        name_lbl = QLabel(self._dto.filename)
        name_lbl.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #e0e0e0;"
        )
        name_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(name_lbl)

        sub = (
            f"📁 文件夹  ·  {format_size(self._dto.size)}"
            if self._dto.is_folder
            else f"{self._dto.ext.upper() or '未知'}  ·  {format_size(self._dto.size)}"
        )
        layout.addWidget(
            QLabel(sub)
        )
        return header

    def _build_readonly_section(self) -> QFormLayout:
        """构建只读信息区。"""
        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 哈希 + 复制按钮
        hash_widget = QWidget()
        hash_layout = QHBoxLayout(hash_widget)
        hash_layout.setContentsMargins(0, 0, 0, 0)
        hash_layout.setSpacing(4)
        hash_val = _ReadOnlyField(self._dto.file_hash or "无")
        copy_btn = QPushButton("复制")
        copy_btn.setFixedWidth(48)
        copy_btn.setStyleSheet(
            "background: #333; color: #aaa; border: none; "
            "border-radius: 4px; padding: 4px; font-size: 11px;"
        )
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self._dto.file_hash or ""
            )
        )
        hash_layout.addWidget(hash_val)
        hash_layout.addWidget(copy_btn)

        store_path = ""
        if self._dto.file_hash:
            p = IndexManager().get_store_path(self._dto.file_hash)
            store_path = str(p) if p else "不存在"

        form.addRow("哈希", hash_widget)
        form.addRow("引用数", _ReadOnlyField(str(IndexManager().get_ref_count(self._dto.file_hash))))
        form.addRow("扩展名", _ReadOnlyField(self._dto.ext or "无"))
        form.addRow("大小", _ReadOnlyField(format_size(self._dto.size)))
        form.addRow("存储路径", _ReadOnlyField(store_path))
        form.addRow("类型", _ReadOnlyField("文件夹" if self._dto.is_folder else "文件"))

        return form

    def _build_path_section(self) -> QFormLayout:
        """构建路径编辑区。"""
        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._origin_path_edit = _EditField(self._dto.origin_path or "")
        self._origin_path_edit.setPlaceholderText("原始路径（仅作记录，不影响物理文件）")
        form.addRow("原始路径", self._origin_path_edit)

        return form

    def _build_time_section(self) -> QFormLayout:
        """构建时间编辑区。"""
        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        dt_style = (
            "background: #2b2b2b; color: #e0e0e0; "
            "border: 1px solid #555; border-radius: 4px; padding: 2px 6px;"
        )

        def make_dt_editor(dt: datetime | None) -> QDateTimeEdit:
            """创建日期时间编辑器。"""
            editor = QDateTimeEdit()
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            editor.setStyleSheet(dt_style)
            editor.setDateTime(_to_qdatetime(dt))
            return editor

        def make_now_btn(editor: QDateTimeEdit) -> QPushButton:
            """创建重置为当前时间的按钮。"""
            btn = QPushButton("现在")
            btn.setFixedWidth(44)
            btn.setStyleSheet(
                "background: #333; color: #aaa; border: none; "
                "border-radius: 4px; padding: 4px; font-size: 11px;"
            )
            btn.clicked.connect(
                lambda: editor.setDateTime(QDateTime.currentDateTime())
            )
            return btn

        def dt_row(editor: QDateTimeEdit, btn: QPushButton) -> QWidget:
            """将编辑器和按钮组合成一行。"""
            w = QWidget()
            layout = QHBoxLayout(w)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            layout.addWidget(editor)
            layout.addWidget(btn)
            return w

        self._modified_at_edit = make_dt_editor(self._dto.modified_at)
        self._indexed_at_edit = make_dt_editor(self._dto.indexed_at)

        form.addRow(
            "修改时间",
            dt_row(self._modified_at_edit, make_now_btn(self._modified_at_edit)),
        )
        form.addRow(
            "索引时间",
            dt_row(self._indexed_at_edit, make_now_btn(self._indexed_at_edit)),
        )
        return form

    def _build_footer(self) -> QWidget:
        """构建底部保存/取消按钮栏。"""
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 8, 20, 0)
        layout.setSpacing(8)
        layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(
            "background: #333; color: #ccc; border: none; "
            "border-radius: 6px; padding: 7px 20px;"
        )
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.setStyleSheet(
            "background: #2d5a8e; color: white; border: none; "
            "border-radius: 6px; padding: 7px 20px; font-weight: bold;"
        )
        save_btn.clicked.connect(self._save)

        layout.addWidget(cancel_btn)
        layout.addWidget(save_btn)
        return footer

    def _save(self) -> None:
        """保存所有可编辑字段到数据库。"""
        idx = IndexManager()
        tags = self._tag_editor.get_tags()
        comment = self._comment_edit.toPlainText().strip()
        summary = self._summary_edit.toPlainText().strip()
        origin_path = self._origin_path_edit.text().strip() or None
        modified_at = _from_qdatetime(self._modified_at_edit.dateTime())
        indexed_at = _from_qdatetime(self._indexed_at_edit.dateTime())

        idx.update_tags(self._dto.id, tags)
        idx.update_comment(self._dto.id, comment)
        idx.update_file_meta(
            file_id=self._dto.id,
            summary=summary,
            origin_path=format_path(origin_path),
            modified_at=modified_at,
            indexed_at=indexed_at,
        )

        self._dto.tags = tags
        self._dto.comment = comment
        self._dto.summary = summary
        self._dto.origin_path = origin_path
        self._dto.modified_at = modified_at
        self._dto.indexed_at = indexed_at

        logger.info(f"详情已保存：{self._dto.filename}")
        self.accept()

    def _apply_theme(self) -> None:
        """应用深色主题样式。"""
        self.setStyleSheet("""
            QDialog   { background: #121212; color: #e0e0e0; }
            QLabel    { color: #e0e0e0; font-size: 13px; }
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: #1e1e1e; width: 6px; border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #444; border-radius: 3px;
            }
        """)
