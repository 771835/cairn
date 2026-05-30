# coding=utf-8
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select, text, col

from cairn.core.config import DB_PATH
from cairn.core.index.models import File, Tag, FileTagLink, FileDTO
from cairn.core.index.search import SearchEngine, SearchQuery, SearchResult
from cairn.core.parser.base import ParseResult
from cairn.utils.logger import get_logger

logger = get_logger(__name__)

_FTS5_STATEMENTS = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
        filename,
        content,
        summary,
        features,
        content='files',
        content_rowid='id'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
        INSERT INTO files_fts(rowid, filename, content, summary, features)
        VALUES (new.id, new.filename, new.content, new.summary, new.features);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
        INSERT INTO files_fts(files_fts, rowid, filename, content, summary, features)
        VALUES ('delete', old.id, old.filename, old.content, old.summary, old.features);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
        INSERT INTO files_fts(files_fts, rowid, filename, content, summary, features)
        VALUES ('delete', old.id, old.filename, old.content, old.summary, old.features);
        INSERT INTO files_fts(rowid, filename, content, summary, features)
        VALUES (new.id, new.filename, new.content, new.summary, new.features);
    END
    """,
]


class IndexManager:
    """索引管理器，单例。普通 CRUD 通过 SQLModel，FTS5 保留最小化 SQL。"""

    _instance: "IndexManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "IndexManager":
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
            assert cls._instance is not None
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        self._engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={
                "check_same_thread": False,
                "timeout": 30  # 等锁最多 30 秒，超时抛异常而不是永久卡死
            },
            echo=False,
        )

        with self._engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))  # 将 SQLite 的日志模式设置为 WAL
            conn.execute(text("PRAGMA foreign_keys=ON"))  # 开启 SQLite 的 外键约束
            conn.commit()

        SQLModel.metadata.create_all(self._engine)
        self._migrate()
        self._init_fts()

        self._search_engine = SearchEngine(self._engine)

        self._initialized = True
        logger.info(f"IndexManager 初始化完成：{DB_PATH}")

    def _init_fts(self) -> None:
        """初始化 FTS5 虚拟表和触发器"""
        with self._engine.connect() as conn:
            for stmt in _FTS5_STATEMENTS:
                conn.execute(text(stmt.strip()))
            conn.commit()

    @property
    def engine(self):
        """暴露数据库引擎，供外部只读访问。"""
        return self._engine

    # ── 写入 ──────────────────────────────────────────────────

    def index_file(
            self,
            result: ParseResult,
            folder_id: int | None = None,
            original_path: Path | None = None,
    ) -> int:
        """写入或更新单个文件索引，返回 file_id。"""
        summary = (result.content or "")[:300]
        features = json.dumps(result.metadata, ensure_ascii=False)
        mtime = self._get_mtime(original_path or result.raw_path)

        # filename 和 origin_path 优先用原始值
        origin = original_path or result.raw_path
        display_name = origin.name  # 始终是原始文件名

        with Session(self._engine) as session:
            file = session.exec(
                select(File).where(File.path == str(result.raw_path))
            ).first()

            if file is None:
                file = File(
                    path=str(result.raw_path.resolve()),  # 哈希路径（物理位置）
                    origin_path=str(origin.resolve()),  # 原始路径（来源记录）
                    filename=display_name,  # 原始文件名（显示用）
                    ext=result.ext,
                    size=result.size,
                    content=result.content,
                    summary=summary,
                    features=features,
                    modified_at=mtime,
                    file_hash=result.file_hash,
                    folder_id=folder_id,
                )
            else:
                file.filename = display_name
                file.origin_path = str(origin)
                file.ext = result.ext
                file.size = result.size
                file.content = result.content
                file.summary = summary
                file.features = features
                file.modified_at = mtime
                file.file_hash = result.file_hash
                file.indexed_at = datetime.now()
                file.folder_id = folder_id

            session.add(file)
            session.commit()
            session.refresh(file)
            self._sync_tags(session, file.id, result.tags)
            logger.debug(f"已索引：{display_name} (id={file.id})")
            return file.id

    def index_folder(
            self,
            folder_path: Path,
            child_results: list[ParseResult],
    ) -> int:
        """整体索引文件夹，返回 folder_id。"""
        aggregated = "\n\n".join(
            f"[{r.filename}]\n{(r.content or '')[:500]}"
            for r in child_results
            if r.content
        )
        summary = f"文件夹：{folder_path.name}，共 {len(child_results)} 个文件"
        all_tags = list({tag for r in child_results for tag in r.tags})
        features = json.dumps({
            "type": "folder",
            "file_count": len(child_results),
            "extensions": list({r.ext for r in child_results}),
            "children": [r.filename for r in child_results],
        }, ensure_ascii=False)

        with Session(self._engine) as session:
            folder = session.exec(
                select(File).where(File.path == str(folder_path))
            ).first()

            if folder is None:
                folder = File(
                    path=str(folder_path),
                    filename=folder_path.name,
                    content=aggregated,
                    summary=summary,
                    features=features,
                    modified_at=self._get_mtime(folder_path),
                    is_folder=True,
                )
            else:
                folder.content = aggregated
                folder.summary = summary
                folder.features = features
                folder.indexed_at = datetime.now()

            session.add(folder)
            session.commit()
            session.refresh(folder)
            self._sync_tags(session, folder.id, all_tags)
            folder_id = folder.id

        for result in child_results:
            self.index_file(result, folder_id=folder_id)

        logger.info(
            f"已整体索引文件夹：{folder_path.name}"
            f"（{len(child_results)} 个子文件）"
        )
        return folder_id

    def index_folder_entry(
            self,
            folder_path: Path,
            child_ids: list[int],
            child_results: list[ParseResult],
    ) -> int:
        """
        建立文件夹聚合索引条目。
        子文件已单独入库，此处只记录文件夹元信息和子文件关联。
        """
        summary = f"文件夹：{folder_path.name}，共 {len(child_ids)} 个文件"
        all_tags = list({tag for r in child_results for tag in r.tags})
        features = json.dumps({
            "type": "folder",
            "file_count": len(child_ids),
            "child_ids": child_ids,  # 聚合子文件 id
            "extensions": list({r.ext for r in child_results}),
            "children": [r.filename for r in child_results],
        }, ensure_ascii=False)

        with Session(self._engine) as session:
            folder = session.exec(
                select(File).where(File.path == str(folder_path))
            ).first()

            if folder is None:
                folder = File(
                    path=str(folder_path),
                    origin_path=str(folder_path),
                    filename=folder_path.name,
                    summary=summary,
                    features=features,
                    modified_at=self._get_mtime(folder_path),
                    is_folder=True,
                )
            else:
                folder.summary = summary
                folder.features = features
                folder.indexed_at = datetime.now()

            session.add(folder)
            session.commit()
            session.refresh(folder)

            # 子文件的 folder_id 指向此条目
            for child_id in child_ids:
                child = session.get(File, child_id)
                if child:
                    child.folder_id = folder.id
                    session.add(child)
            session.commit()

            self._sync_tags(session, folder.id, all_tags)
            return folder.id

    # ── 检索 ──────────────────────────────────────────────────

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """统一搜索入口"""
        return self._search_engine.search(query)

    def suggest(self, prefix: str) -> list[str]:
        """输入补全"""
        return self._search_engine.suggest(prefix)

    def search_in_folder(self, folder_path: Path, query: str) -> list[File]:
        """在指定文件夹内检索。"""
        with Session(self._engine) as session:
            folder = session.exec(
                select(File).where(File.path == str(folder_path))
            ).first()
            if folder is None:
                return []

            fts_rows = session.connection().execute(text("""
                SELECT rowid FROM files_fts
                WHERE files_fts MATCH :q
                ORDER BY bm25(files_fts)
            """), {"q": query}).fetchall()

            matched_ids = [row[0] for row in fts_rows]
            if not matched_ids:
                return []

            folder_id = folder.id
            return list(session.exec(
                select(File).where(
                    col(File.id).in_(matched_ids),
                    (File.folder_id == folder_id) | (File.id == folder_id)
                )
            ).all())

    def get_recent(self, limit: int = 20) -> list[FileDTO]:
        with Session(self._engine) as session:
            files = session.exec(
                select(File)
                .order_by(col(File.indexed_at).desc())
                .limit(limit)
            ).all()
            return [FileDTO.from_orm(f) for f in files]  # Session 内转换

    def get_by_tag(self, tag_name: str) -> list[FileDTO]:
        """按标签获取文件，一次 JOIN 查完所有标签，避免 N+1。"""
        with Session(self._engine) as session:
            tag = session.exec(
                select(Tag).where(Tag.name == tag_name)
            ).first()
            if tag is None:
                return []

            # 一次查出所有文件
            files = session.exec(
                select(File)
                .where(
                    col(File.id).in_(
                        select(FileTagLink.file_id).where(
                            FileTagLink.tag_id == tag.id
                        )
                    )
                )
                .order_by(col(File.indexed_at).desc())
            ).all()

            if not files:
                return []

            # 一次查出所有相关标签，避免逐个懒加载
            file_ids = [f.id for f in files]
            tag_rows = session.exec(
                select(FileTagLink.file_id, Tag.name)
                .join(Tag, FileTagLink.tag_id == Tag.id)
                .where(col(FileTagLink.file_id).in_(file_ids))
            ).all()

            # 构建 file_id → [tag_name] 映射
            tag_map: dict[int, list[str]] = {}
            for file_id, tname in tag_rows:
                tag_map.setdefault(file_id, []).append(tname)

            return [
                FileDTO(
                    id=f.id,
                    path=f.origin_path or f.path,
                    origin_path=f.origin_path,
                    filename=f.filename,
                    ext=f.ext,
                    size=f.size,
                    content=f.content,
                    summary=f.summary,
                    features=f.features,
                    comment=f.comment,
                    indexed_at=f.indexed_at,
                    modified_at=f.modified_at,
                    file_hash=f.file_hash,
                    is_folder=f.is_folder,
                    folder_id=f.folder_id,
                    tags=tag_map.get(f.id, []),
                )
                for f in files
            ]

    def get_all_tags(self) -> list[tuple[str, int]]:
        """返回 [(tag_name, count), ...] 按使用频率排序。"""
        with Session(self._engine) as session:
            rows = session.connection().execute(text("""
                SELECT t.name, COUNT(ft.file_id) AS cnt
                FROM tags t
                JOIN file_tags ft ON t.id = ft.tag_id
                GROUP BY t.name
                ORDER BY cnt DESC
            """)).fetchall()
            return [(row[0], row[1]) for row in rows]

    # ── 内部工具 ──────────────────────────────────────────────

    @staticmethod
    def _sync_tags(session: Session, file_id: int, tags: list[str]) -> None:
        """全量替换文件标签。"""
        old_links = session.exec(
            select(FileTagLink).where(FileTagLink.file_id == file_id)
        ).all()
        for link in old_links:
            session.delete(link)
        session.commit()

        for name in {t.strip().lower() for t in tags if t.strip()}:
            tag = session.exec(
                select(Tag).where(Tag.name == name)
            ).first()
            if tag is None:
                tag = Tag(name=name)
                session.add(tag)
                session.commit()
                session.refresh(tag)

            session.add(FileTagLink(file_id=file_id, tag_id=tag.id))

        session.commit()

    @staticmethod
    def _get_mtime(path: Path) -> datetime:
        """获取文件修改时间，失败时返回当前时间。"""
        try:
            return datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return datetime.now()

    def get_store_path(self, file_hash: str | None) -> Path | None:
        """根据哈希值取回物理存储路径"""
        if not file_hash:
            return None
        from cairn.core.store import FileStore
        return FileStore().get_path(file_hash)

    def update_comment(self, file_id: int, comment: str) -> None:
        """更新文件注释"""
        with Session(self._engine) as session:
            file = session.get(File, file_id)
            if file:
                file.comment = comment
                file.indexed_at = datetime.now()
                session.add(file)
                session.commit()

    def update_tags(self, file_id: int, tags: list[str]) -> None:
        """全量替换文件标签"""
        with Session(self._engine) as session:
            self._sync_tags(session, file_id, tags)

    def update_file_meta(
            self,
            file_id: int,
            summary: str | None = None,
            origin_path: str | None = None,
            modified_at: datetime | None = None,
            indexed_at: datetime | None = None,
    ) -> None:
        """批量更新文件元信息。"""
        with Session(self._engine) as session:
            file = session.get(File, file_id)
            if not file:
                return
            if summary is not None: file.summary = summary
            if origin_path is not None: file.origin_path = origin_path
            if modified_at is not None: file.modified_at = modified_at
            if indexed_at is not None: file.indexed_at = indexed_at
            session.add(file)
            session.commit()

    def delete_from_index(
            self,
            file_id: int,
            dev_mode: bool = False,
    ) -> None:
        """
        从索引删除。

        正常模式：ref_count - 1，归零时删物理文件。
        开发者模式：只删数据库记录，物理文件无论如何保留。
        """
        with Session(self._engine) as session:
            file = session.get(File, file_id)
            if not file:
                return

            store_path = Path(file.path)
            file_hash = file.file_hash

            if dev_mode:
                # 开发者模式：只删记录
                session.delete(file)
                session.commit()
                logger.info(f"[DEV] 已从索引删除：{file.filename}，物理文件保留")
                return

            # 正常模式：引用计数
            file.ref_count -= 1
            if file.ref_count > 0:
                session.add(file)
                session.commit()
                logger.info(
                    f"已减少引用：{file.filename}，"
                    f"剩余引用数={file.ref_count}"
                )
                return

            # 引用归零，删记录
            session.delete(file)
            session.commit()

        # 检查同哈希是否还有其他记录
        if file_hash:
            with Session(self._engine) as session:
                same_hash = session.exec(
                    select(File).where(File.file_hash == file_hash)
                ).first()
                if same_hash is None and store_path.exists():
                    store_path.unlink(missing_ok=True)
                    try:
                        store_path.parent.rmdir()
                    except OSError:
                        pass
                    logger.info(f"已删除物理文件：{file_hash[:12]}...")

    def delete_from_store(
            self,
            file_id: int,
            dev_mode: bool = False,
    ) -> None:
        """
        从知识库彻底删除。

        正常模式：删记录，同哈希无其他引用时才删物理文件。
        开发者模式：强制删记录和物理文件，不检查引用。
        """
        with Session(self._engine) as session:
            file = session.get(File, file_id)
            if not file:
                return
            store_path = Path(file.path)
            file_hash = file.file_hash
            session.delete(file)
            session.commit()

        if dev_mode:
            if store_path.exists():
                store_path.unlink(missing_ok=True)
                logger.info(f"[DEV] 强制删除物理文件：{file_hash}")
            return

        # 正常模式：检查同哈希引用
        if file_hash:
            with Session(self._engine) as session:
                same_hash = session.exec(
                    select(File).where(File.file_hash == file_hash)
                ).first()
                if same_hash is None and store_path.exists():
                    store_path.unlink(missing_ok=True)
                    try:
                        store_path.parent.rmdir()
                    except OSError:
                        pass
                    logger.info(f"已删除物理文件：{file_hash[:12]}...")

    def get_folder_tree(self) -> dict:
        """
        按 origin_path 重建虚拟目录树。
        返回结构：
        {
            "name": "root",
            "path": "",
            "children": {
                "E:/文档": {
                    "name": "文档",
                    "path": "E:/文档",
                    "children": {...},
                    "files": [FileDTO, ...]
                }
            },
            "files": []
        }
        """
        with Session(self._engine) as session:
            files = session.exec(select(File)).all()
            dtos = [FileDTO.from_orm(f) for f in files]

        root: dict = {"name": "root", "path": "", "children": {}, "files": []}

        for dto in dtos:
            origin = dto.origin_path or dto.path
            parent = str(Path(origin).parent)

            # 逐级建树
            parts = Path(parent).parts
            node = root
            for part in parts:
                key = str(Path(*parts[:parts.index(part) + 1]))
                if key not in node["children"]:
                    node["children"][key] = {
                        "name": part,
                        "path": key,
                        "children": {},
                        "files": [],
                    }
                node = node["children"][key]

            node["files"].append(dto)

        return root

    def get_by_indexed_date(self) -> dict[str, list[FileDTO]]:
        """
        按索引时间分组，返回：
        {"今天": [...], "本周": [...], "本月": [...], "更早": [...]}
        """
        from datetime import date, timedelta
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        with Session(self._engine) as session:
            files = session.exec(
                select(File).order_by(col(File.indexed_at).desc())
            ).all()
            dtos = [FileDTO.from_orm(f) for f in files]

        groups: dict[str, list[FileDTO]] = {
            "今天": [], "本周": [], "本月": [], "更早": []
        }
        for dto in dtos:
            if not dto.indexed_at:
                groups["更早"].append(dto)
                continue
            d = dto.indexed_at.date()
            if d == today:
                groups["今天"].append(dto)
            elif d >= week_start:
                groups["本周"].append(dto)
            elif d >= month_start:
                groups["本月"].append(dto)
            else:
                groups["更早"].append(dto)

        return groups

    def _migrate(self) -> None:
        """检查并补全缺失的列，向前兼容旧数据库。"""
        migrations = [
            ("files", "comment", "TEXT NOT NULL DEFAULT ''"),
            ("files", "ref_count", "INTEGER NOT NULL DEFAULT 1"),
        ]

        with self._engine.connect() as conn:
            for table, column, definition in migrations:
                # 查询现有列
                existing = {
                    row[1]
                    for row in conn.execute(
                        text(f"PRAGMA table_info({table})")
                    ).fetchall()
                }
                if column not in existing:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    ))
                    logger.info(f"数据库迁移：{table}.{column} 已添加")
            conn.commit()

    def restore_file(
            self,
            file_id: int,
            target_path: Path | None = None,
    ) -> tuple[bool, str]:
        """
        将文件从哈希存储还原到目标路径。

        target_path 为 None 时尝试还原到 origin_path。
        还原成功后从索引删除（ref_count 逻辑）。

        返回 (成功, 消息)。
        """
        with Session(self._engine) as session:
            file = session.get(File, file_id)
            if not file:
                return False, "索引记录不存在"
            dto = FileDTO.from_orm(file)

        store_path = self.get_store_path(dto.file_hash)
        if not store_path or not store_path.exists():
            return False, "物理文件不存在，无法还原"

        # 确定目标路径
        dest = target_path or (
            Path(dto.origin_path) if dto.origin_path else None
        )
        if dest is None:
            return False, "无原始路径，请使用另存为"

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)

            # 目标已存在时自动重命名
            if dest.exists():
                stem = dest.stem
                suffix = dest.suffix
                i = 1
                while dest.exists():
                    dest = dest.parent / f"{stem}_还原{i}{suffix}"
                    i += 1

            shutil.copy2(str(store_path), str(dest))
            logger.info(f"已还原：{dto.filename} → {dest}")

        except Exception as e:
            return False, f"还原失败：{e}"

        # 还原成功，从索引删除
        self.delete_from_index(file_id)
        return True, str(dest)

    def scan_orphaned_files(self) -> tuple[list[Path], int]:
        """扫描无引用的孤立物理文件。"""
        from cairn.core.config import config
        store_root = config.store_root

        with Session(self._engine) as session:

            # 统一用 resolve() 规范化路径，消除斜杠和大小写差异
            known_paths = {
                Path(row).resolve()
                for row in session.exec(select(File.path)).all()
                if row  # 过滤空路径
            }

        orphans: list[Path] = []
        total_size: int = 0

        for f in store_root.rglob("*"):
            if not f.is_file():
                continue
            if f.resolve() not in known_paths:
                orphans.append(f)
                try:
                    total_size += f.stat().st_size
                except OSError:
                    pass

        logger.info(
            f"扫描完成：发现 {len(orphans)} 个孤立文件，"
            f"共 {total_size / 1024 / 1024:.1f} MB"
        )
        return orphans, total_size

    @staticmethod
    def clean_orphaned_files(orphans: list[Path]) -> tuple[int, int]:
        """
        删除孤立文件。
        返回 (已删除数量, 已释放字节数)。
        """
        deleted = 0
        freed = 0
        for f in orphans:
            try:
                size = f.stat().st_size
                f.unlink()
                try:
                    f.parent.rmdir()
                except OSError:
                    pass
                deleted += 1
                freed += size
            except OSError as e:
                logger.warning(f"删除失败：{f} — {e}")
        logger.info(
            f"存储整理完成：删除 {deleted} 个文件，"
            f"释放 {freed / 1024 / 1024:.1f} MB"
        )
        return deleted, freed
