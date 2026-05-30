# coding=utf-8
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from cairn.core.index.models import FileDTO

def format_detail(dto: "FileDTO", snippet: str = "") -> str:
    """格式化文件详情文本。"""
    mtime = dto.modified_at.strftime("%Y-%m-%d %H:%M") if dto.modified_at else "未知"
    size = format_size(dto.size)
    tags = " ".join(f"#{t}" for t in dto.tags)
    clean = snippet.replace("<b>", "").replace("</b>", "")[:80] if snippet else \
        (dto.comment or dto.summary or "")[:80]
    return f"{dto.path}\n修改：{mtime}  大小：{size}  {tags}\n{clean}"


def format_size(size: int) -> str:
    """字节数格式化。"""
    for unit, t in [("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)]:
        if size >= t:
            return f"{size / t:.1f} {unit}"
    return f"{size} B"

