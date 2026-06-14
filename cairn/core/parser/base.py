# coding=utf-8
from attrs import define, field
from pathlib import Path


@define(slots=True)
class ParseResult:
    """解析结果，规则引擎的唯一输入数据结构"""
    raw_path: Path
    metadata: dict = field(factory=dict)
    tags: list[str] = field(factory=list)
    links: list[str] = field(factory=list)
    file_hash: str = ""

    @property
    def filename(self) -> str:
        origin = self.metadata.get("origin_path") or str(self.raw_path)
        return Path(origin).name if origin else self.raw_path.name

    @property
    def ext(self) -> str:
        origin = self.metadata.get("origin_path") or str(self.raw_path)
        return Path(origin).suffix.lower().lstrip(".")

    @property
    def size(self) -> int:
        return self.raw_path.stat().st_size if self.raw_path.exists() else 0


