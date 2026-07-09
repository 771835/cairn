# coding=utf-8

from datetime import datetime

from attrs import define, field
from sqlmodel import Session, select, col, text

from cairn.core.index.models import File, Tag, FileTagLink, FileDTO
from cairn.utils.logger import get_logger

logger = get_logger(__name__)


@define(slots=True)
class SearchQuery:
    """
    结构化搜索请求。
    所有字段均为可选，组合使用。

    示例：
        SearchQuery(text="强化学习", tags=["python"], ext=["py"])
        SearchQuery(text="README", is_folder=False, modified_after=datetime(2024,1,1))
        SearchQuery(size_min=1024*1024)   # 大于 1MB
    """
    text: str = ""  # 全文检索关键词
    tags: list[str] = field(factory=list)
    ext: list[str] = field(factory=list)
    filename: str = ""  # 文件名模糊匹配
    path_prefix: str = ""  # 路径前缀过滤
    is_folder: bool | None = None  # None=全部，True=只要文件夹
    size_min: int | None = None  # 最小字节数
    size_max: int | None = None  # 最大字节数
    modified_after: datetime | None = None
    modified_before: datetime | None = None
    limit: int = 20
    offset: int = 0  # 分页


@define(slots=True)
class SearchResult:
    """单条搜索结果"""
    file: FileDTO
    snippet: str = ""  # FTS5 高亮摘要片段
    score: float = 0.0  # BM25 相关度分数（越小越相关）


class SearchEngine:
    """
    独立搜索引擎，与 IndexManager 解耦。
    职责：把 SearchQuery 翻译成高效的 SQL，返回 SearchResult 列表。
    """

    def __init__(self, engine):
        self._engine = engine

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """
        主搜索入口。
        流程：
        1. 若有全文关键词 → FTS5 取候选 ID + filename LIKE 兜底，取并集
        2. 用 SQLModel 做结构化过滤
        3. 组装 SearchResult 返回
        """
        with Session(self._engine) as session:

            # ── Step 1：FTS5 全文检索 + filename LIKE 并集 ─────────
            if query.text:
                fts_data = self._fts_search(
                    session, query.text, query.limit + query.offset
                )

                # filename LIKE 兜底，捞出 FTS5 分词没命中的短词
                like_files = session.exec(
                    select(File).where(
                        col(File.filename).contains(query.text)
                    ).limit(query.limit)
                ).all()
                like_ids = {f.id for f in like_files}

                # 两者取并集
                all_ids = list(set(fts_data.keys()) | like_ids)

                if not all_ids:
                    return []

                candidate_ids = all_ids
            else:
                fts_data = {}
                candidate_ids = None

            # ── Step 2：结构化过滤 ─────────────────────────────────
            stmt = select(File)

            if candidate_ids is not None:
                stmt = stmt.where(col(File.id).in_(candidate_ids))

            if query.filename:
                stmt = stmt.where(col(File.filename).contains(query.filename))

            if query.path_prefix:
                stmt = stmt.where(col(File.path).startswith(query.path_prefix))

            if query.ext:
                stmt = stmt.where(col(File.ext).in_(query.ext))

            if query.is_folder is not None:
                stmt = stmt.where(File.is_folder == query.is_folder)

            if query.size_min is not None:
                stmt = stmt.where(col(File.size) >= query.size_min)

            if query.size_max is not None:
                stmt = stmt.where(col(File.size) <= query.size_max)

            if query.modified_after:
                stmt = stmt.where(col(File.modified_at) >= query.modified_after)

            if query.modified_before:
                stmt = stmt.where(col(File.modified_at) <= query.modified_before)

            if query.tags:
                tag_ids = self._resolve_tag_ids(session, query.tags)
                if not tag_ids:
                    return []
                for tag_id in tag_ids:
                    stmt = stmt.where(
                        col(File.id).in_(
                            select(FileTagLink.file_id).where(
                                FileTagLink.tag_id == tag_id
                            )
                        )
                    )

            files = session.exec(
                stmt.offset(query.offset).limit(query.limit)
            ).all()

            # ── Step 3：组装结果 ───────────────────────────────────
            results = self._batch_to_dto(session, files, fts_data)

            if query.text:
                # FTS5 命中的按相关度排前面，LIKE 兜底的排后面（score=0.0）
                results.sort(key=lambda r: (r.score == 0.0, r.score))
            else:
                results.sort(
                    key=lambda r: r.file.indexed_at or datetime.min,
                    reverse=True,
                )

            return results

    def suggest(self, prefix: str, limit: int = 8) -> list[str]:
        """
        输入补全：根据前缀模糊匹配文件名和标签。
        用于搜索框实时提示。
        """
        with Session(self._engine) as session:
            files = session.exec(
                select(File.filename)
                .where(col(File.filename).contains(prefix))
                .limit(limit // 2)
            ).all()

            tags = session.exec(
                select(Tag.name)
                .where(col(Tag.name).startswith(prefix))
                .limit(limit // 2)
            ).all()

            suggestions = [f for f in files] + [f"#{t}" for t in tags]
            return suggestions[:limit]

    # ── 内部工具 ──────────────────────────────────────────────

    @staticmethod
    def _fts_search(
            session: Session,
            query_text: str,
            limit: int,
    ) -> dict[int, tuple[str, float]]:
        """
        FTS5 全文检索。
        返回 {file_id: (snippet, bm25_score)}。
        bm25 分数为负数，越接近 0 越相关。
        """
        # 清理查询词，防止 FTS5 语法错误
        clean = query_text.replace('"', '').strip()
        if not clean:
            return {}

        fts_query = " ".join(
            f'"{token}"*' if not token.endswith("*") else token
            for token in clean.split()
        )

        try:
            rows = session.connection().execute(text("""
                SELECT
                    rowid,
                    snippet(files_fts, 1, '<b>', '</b>', '…', 24),
                    bm25(files_fts)
                FROM files_fts
                WHERE files_fts MATCH :q
                ORDER BY bm25(files_fts)
                LIMIT :lim
            """), {"q": fts_query, "lim": limit}).fetchall()

        except Exception as e:
            logger.warning(f"FTS5 检索出错：{e}，降级为模糊匹配")
            # 降级：用 LIKE 模糊匹配
            rows = session.connection().execute(text("""
                SELECT id, summary, 0
                FROM files
                WHERE filename LIKE :q OR content LIKE :q OR summary LIKE :q
                LIMIT :lim
            """), {"q": f"%{clean}%", "lim": limit}).fetchall()

        return {
            row[0]: (row[1] or "", float(row[2]))
            for row in rows
        }

    @staticmethod
    def _resolve_tag_ids(session: Session, tag_names: list[str]) -> list[int]:
        """把标签名列表转换为 tag_id 列表，不存在的标签直接忽略"""
        tags = session.exec(
            select(Tag).where(col(Tag.name).in_(tag_names))
        ).all()
        return [t.id for t in tags]

    @staticmethod
    def _batch_to_dto(
            session: Session,
            files: list[File],
            fts_data: dict[int, tuple[str, float]],
    ) -> list[SearchResult]:
        """
        批量转换 File → FileDTO，一次查完所有标签。
        避免逐个 from_orm 触发 N+1 懒加载。
        """
        if not files:
            return []

        file_ids = [f.id for f in files]
        tag_rows = session.exec(
            select(FileTagLink.file_id, Tag.name)
            .join(Tag, col(FileTagLink.tag_id) == Tag.id)
            .where(col(FileTagLink.file_id).in_(file_ids))
        ).all()

        tag_map: dict[int, list[str]] = {}
        for file_id, tname in tag_rows:
            tag_map.setdefault(file_id, []).append(tname)

        results = []
        for f in files:
            dto = FileDTO(
                id=f.id,
                path=f.origin_path or f.path,
                origin_path=f.origin_path,
                filename=f.filename,
                ext=f.ext,
                size=f.size,
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
            snippet, score = fts_data.get(f.id, ("", 0.0))
            results.append(SearchResult(file=dto, snippet=snippet, score=score))

        return results
