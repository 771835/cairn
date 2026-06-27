# coding=utf-8
from attrs import define, field
from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field, Relationship


class FileTagLink(SQLModel, table=True):
    """文件-标签多对多关联表"""
    __tablename__ = "file_tags"

    file_id: int = Field(foreign_key="files.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True)


class Tag(SQLModel, table=True):
    __tablename__ = "tags"

    id: int = Field(default=None, primary_key=True)  # SQLModel 自动处理 AUTOINCREMENT
    name: str = Field(unique=True, index=True)
    display_name: Optional[str] = Field(default=None)
    files: list["File"] = Relationship(
        back_populates="tags", link_model=FileTagLink
    )


class HashFile(SQLModel, table=True):
    __tablename__ = "hash_files"
    file_hash: Optional[str] = Field(default=None, primary_key=True)
    ref_count: int = Field(default=1)


class File(SQLModel, table=True):
    """文件索引主表"""
    __tablename__ = "files"
    __table_args__ = (
        # 同一个来源路径不能重复索引，否则fts5会炸
        UniqueConstraint("origin_path", name="uq_files_origin_path"),
    )

    id: int = Field(default=None, primary_key=True)
    path: str = Field(index=True)
    origin_path: Optional[str] = None
    filename: str = Field(index=True)
    ext: str = ""
    size: int = 0
    summary: Optional[str] = None
    features: Optional[str] = None
    comment: str = ""  # 用户注释
    indexed_at: datetime = Field(default_factory=datetime.now)
    modified_at: Optional[datetime] = None
    file_hash: Optional[str] = None
    is_folder: bool = False
    folder_id: Optional[int] = Field(default=None, foreign_key="files.id")
    tags: list[Tag] = Relationship(
        back_populates="files", link_model=FileTagLink
    )


@define(slots=True)
class FileDTO:
    """File 的纯数据传输对象，Session 关闭后安全传递。"""
    id: int
    path: str
    origin_path: str | None
    filename: str
    ext: str
    size: int
    summary: str | None
    features: str | None
    comment: str
    indexed_at: datetime | None
    modified_at: datetime | None
    file_hash: str | None
    is_folder: bool
    folder_id: int | None
    tags: list[str] = field(factory=list)

    @classmethod
    def from_orm(cls, file: File) -> "FileDTO":
        """在 Session 内调用，将 ORM 对象转为 DTO"""
        return cls(
            id=file.id,
            path=file.origin_path or file.path,
            origin_path=file.origin_path,
            filename=file.filename,
            ext=file.ext,
            size=file.size,
            summary=file.summary,
            features=file.features,
            comment=file.comment,
            indexed_at=file.indexed_at,
            modified_at=file.modified_at,
            file_hash=file.file_hash,
            is_folder=file.is_folder,
            folder_id=file.folder_id,
            tags=[t.name for t in file.tags],
        )
