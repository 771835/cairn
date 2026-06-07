# coding=utf-8
import os
import re
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
            return f"{size / t:.2f} {unit}"
    return f"{size} B"


def format_path(path_str: str | None):
    if path_str is None:
        return "\\"
    # 去除开头结尾空白
    path_str = path_str.strip()

    # 如果为空，返回 "\"
    if not path_str:
        return "\\"

    # 检查是否为绝对路径（例如 C:\... 或 D:\...）
    # 使用正则表达式检查是否以字母开头后面跟冒号
    if re.match(r'^[A-Za-z]:', path_str):
        return path_str

    # 如果不以反斜杠开头，则添加一个反斜杠
    if not path_str.startswith("\\"):
        path_str = "\\" + path_str

    return path_str


def normalize_to_platform(path_str):
    """
    平台规范化：
    1. 根据系统统一使用 \\ 或 /
    2. 循环处理 ./ 和 .. 直到路径干净
    """
    # 1. 统一斜杠为当前系统的标准斜杠
    # Windows 使用 \，Unix 使用 /
    if os.name == 'nt':
        path_str = path_str.replace('/', '\\')
    else:
        path_str = path_str.replace('\\', '/')

    # 2. 循环处理相对路径直到干净
    # os.path.normpath 会自动处理 ./ (当前目录) 和 ../ (上级目录)
    # 例如: c:\a\..\b -> c:\b
    while True:
        # 尝试规范化
        new_path = os.path.normpath(path_str)

        # 如果规范化后没有变化，说明已经是最简形式，跳出循环
        if new_path == path_str:
            break

        path_str = new_path

    return os.path.abspath(path_str)
