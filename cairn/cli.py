# coding=utf-8
"""
Cairn CLI — 知识库命令行工具

用法：python -m cairn.cli <命令> [选项]
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select, col

from cairn.core.index.manager import IndexManager
from cairn.core.index.models import FileDTO
from cairn.core.index.search import SearchQuery, SearchResult


# ── 格式化工具 ────────────────────────────────────────────────

def _fmt_size(size: int) -> str:
    """字节数格式化。"""
    for unit, t in [("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)]:
        if size >= t:
            return f"{size / t:.1f}{unit}"
    return f"{size}B"


def _fmt_date(dt: datetime | None, fmt: str = "%Y-%m-%d") -> str:
    """日期格式化，None 返回 ?。"""
    return dt.strftime(fmt) if dt else "?"


def _parse_size(s: str) -> int:
    """解析大小字符串，如 1mb / 500kb / 2gb。"""
    s = s.lower().strip()
    units = {
        "pb": 1024 ** 5, "tb": 1024 ** 4, "t": 1024 ** 4,
        "gb": 1024 ** 3, "g": 1024 ** 3, "mb": 1024 ** 2,
        "m": 1024 ** 2, "kb": 1024, "k": 1024, "b": 1,
    }
    for u, m in sorted(units.items(), key=lambda x: -len(x[0])):
        if s.endswith(u):
            try:
                return int(float(s[:-len(u)]) * m)
            except ValueError:
                break
    try:
        return int(s)
    except ValueError:
        print(f"[ERROR] 无法解析大小：{s}")
        sys.exit(1)


def _parse_date(s: str) -> datetime:
    """解析日期字符串，支持 YYYY-MM-DD 和 YYYY-MM-DD HH:MM。"""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    print(f"[ERROR] 无法解析日期：{s}（格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM）")
    sys.exit(1)


# ── 输出格式 ──────────────────────────────────────────────────

def _print_results(
        results: list[SearchResult],
        show_snippet: bool = True,
        show_summary: bool = False,
) -> None:
    """打印搜索结果列表。"""
    if not results:
        print("无结果")
        return

    term_width = shutil.get_terminal_size((80, 20)).columns

    for r in results:
        f = r.file
        folder_mark = "📁 " if f.is_folder else ""
        tags = "  " + " ".join(f"#{t}" for t in f.tags) if f.tags else ""
        size_str = _fmt_size(f.size)
        mtime = _fmt_date(f.modified_at)

        # 主行
        meta = f"  {size_str}  {mtime}{tags}"
        print(f"{folder_mark}{f.filename}{meta}")

        # 路径
        print(f"  \033[90m{f.path}\033[0m")

        # 摘要
        if show_summary and f.summary:
            print(f"  \033[90m{f.summary[:100]}\033[0m")

        # 片段
        if show_snippet and r.snippet:
            clean = r.snippet.replace("<b>", "\033[1m").replace("</b>", "\033[0m")
            print(f"  {clean[:term_width - 4]}")

        print()


def _print_files(files: list[FileDTO]) -> None:
    """打印文件列表（用于 recent / tag 等命令）。"""
    if not files:
        print("无结果")
        return
    for f in files:
        folder_mark = "📁 " if f.is_folder else ""
        tags = "  " + " ".join(f"#{t}" for t in f.tags) if f.tags else ""
        itime = _fmt_date(f.indexed_at, "%Y-%m-%d %H:%M")
        print(f"{itime}  {folder_mark}{f.filename}  {_fmt_size(f.size)}{tags}")
        print(f"  \033[90m{f.path}\033[0m")
        print()


# ── 子命令处理函数 ────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> None:
    """全文检索。"""
    idx = IndexManager()
    results = idx.search(SearchQuery(
        text=args.text or "",
        tags=args.tag or [],
        ext=args.ext or [],
        modified_after=_parse_date(args.after) if args.after else None,
        modified_before=_parse_date(args.before) if args.before else None,
        size_min=_parse_size(args.size_min) if args.size_min else None,
        size_max=_parse_size(args.size_max) if args.size_max else None,
        is_folder=True if args.folder else None,
        limit=args.limit,
        offset=args.offset,
    ))
    print(f"共 {len(results)} 个结果\n")
    _print_results(
        results,
        show_snippet=not args.no_snippet,
        show_summary=args.summary,
    )


def cmd_recent(args: argparse.Namespace) -> None:
    """最近索引的文件。"""
    idx = IndexManager()
    files = idx.get_recent(limit=args.limit)
    print(f"最近 {len(files)} 个文件\n")
    _print_files(files)


def cmd_tags(args: argparse.Namespace) -> None:
    """列出所有标签。"""
    idx = IndexManager()
    tags = idx.get_all_tags_and_display_name()
    if not tags:
        print("暂无标签")
        return

    if args.sort == "name":
        tags = sorted(tags, key=lambda x: x[0])

    print(f"共 {len(tags)} 个标签\n")

    for name, display_name, count in tags:
        bar = "█" * min(count // max(1, max(c for _, _, c in tags) // 20), 20)
        print(f"  #{f'{display_name}({name})':<24} {count:>6}  \033[34m{bar}\033[0m")


def cmd_tag_files(args: argparse.Namespace) -> None:
    """列出指定标签下的所有文件。"""
    idx = IndexManager()
    files = idx.get_by_tag(args.name)

    # 获取标签的显示名称
    with Session(idx.engine) as session:
        from cairn.core.index.models import Tag
        tag = session.exec(select(Tag).where(col(Tag.name) == args.name)).first()
        display_name = tag.display_name if tag else args.name  # noqa

    print(f"标签 #{display_name} 下共 {len(files)} 个文件\n")
    _print_files(files)


def cmd_suggest(args: argparse.Namespace) -> None:
    """输入补全建议。"""
    idx = IndexManager()
    for s in idx.suggest(args.prefix):
        print(f"  {s}")


def cmd_info(args: argparse.Namespace) -> None:
    """查看单个文件详情。"""
    idx = IndexManager()
    results = idx.search(SearchQuery(text=args.keyword, limit=1))
    if not results:
        print(f"未找到：{args.keyword}")
        return

    f = results[0].file
    print(f"文件名     {f.filename}")
    print(f"原始路径   {f.origin_path or '无'}")
    print(f"存储路径   {f.path}")
    print(f"扩展名     {f.ext or '无'}")
    print(f"大小       {_fmt_size(f.size)}")
    print(f"修改时间   {_fmt_date(f.modified_at, '%Y-%m-%d %H:%M')}")
    print(f"索引时间   {_fmt_date(f.indexed_at, '%Y-%m-%d %H:%M')}")
    print(f"哈希       {f.file_hash or '无'}")
    print(f"标签       {' '.join('#' + t for t in f.tags) or '无'}")
    print(f"注释       {f.comment or '无'}")
    if f.summary:
        print(f"摘要       {f.summary[:200]}")


def cmd_stats(_args: argparse.Namespace) -> None:
    """知识库统计概览。"""
    from sqlmodel import Session, select, func, col, case
    from cairn.core.index.models import File, Tag

    idx = IndexManager()
    with Session(idx.engine) as session:

        overview = session.exec(
            select(
                func.sum(case((col(File.is_folder) == False, 1), else_=0)),
                func.sum(case((col(File.is_folder) == True, 1), else_=0)),
                func.coalesce(func.sum(File.size), 0),
            )
        ).one()
        n_files = int(overview[0] or 0)  # noqa
        n_folders = int(overview[1] or 0)  # noqa
        n_size = int(overview[2] or 0)  # noqa

        n_tags = int(session.exec(select(func.count(Tag.id))).one() or 0)  # noqa

        ext_rows = session.exec(
            select(File.ext, func.count(File.id))
            .where(col(File.is_folder) == False)
            .where(col(File.ext) != "")
            .group_by(col(File.ext))
            .order_by(func.count(File.id).desc())
            .limit(5)
        ).all()

        recent: File | None = session.exec(
            select(File).order_by(col(File.indexed_at).desc()).limit(1)
        ).first()

    print("── 知识库统计 " + "─" * 30)
    print(f"  文件总数   {n_files:,} 个")
    print(f"  文件夹数   {n_folders:,} 个")
    print(f"  占用空间   {_fmt_size(n_size)}")
    print(f"  标签总数   {n_tags} 个")

    if ext_rows:
        print("\n  扩展名分布（前 5）")
        max_c = max(int(r[1]) for r in ext_rows) or 1  # noqa
        for ext, count in ext_rows:
            bar = "█" * int(20 * int(count) / max_c)  # noqa
            print(f"    .{str(ext):<10} {int(count):>6}  \033[34m{bar}\033[0m")  # noqa

    if recent is not None:
        itime = _fmt_date(recent.indexed_at, "%Y-%m-%d %H:%M")
        print(f"\n  最近索引   {recent.filename}  ({itime})")


def cmd_restore(args: argparse.Namespace) -> None:
    """将文件还原到原始位置或指定路径。"""
    idx = IndexManager()
    results = idx.search(SearchQuery(text=args.keyword, limit=1))
    if not results:
        print(f"未找到：{args.keyword}")
        return

    f = results[0].file
    dest = Path(args.dest) if args.dest else (
        Path(f.origin_path) if f.origin_path else None
    )
    if dest is None:
        print(f"[ERROR] {f.filename} 无原始路径，请用 --dest 指定目标路径")
        return

    # 同名自动重命名
    if dest.exists() and not args.overwrite:
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while dest.exists():
            dest = dest.parent / f"{stem}_{i}{suffix}"
            i += 1

    ok, msg = idx.restore_file(f.id, target_path=dest)
    if ok:
        print(f"[OK] 已还原：{f.filename} → {msg}")
    else:
        print(f"[FAIL] {msg}")


def cmd_tag_edit(args: argparse.Namespace) -> None:
    """编辑文件标签。"""
    idx = IndexManager()
    results = idx.search(SearchQuery(text=args.keyword, limit=1))
    if not results:
        print(f"未找到：{args.keyword}")
        return

    f = results[0].file
    new_tags = [t.strip().lower() for t in args.tags.split(",") if t.strip()]

    if args.add:
        new_tags = list({*f.tags, *new_tags})
    elif args.remove:
        new_tags = [t for t in f.tags if t not in new_tags]

    idx.update_tags(f.id, new_tags)

    # 显示更新后的标签（使用显示名称）
    tag_names = [t for t in new_tags]
    with Session(idx.engine) as session:
        from cairn.core.index.models import Tag
        tags_info = session.exec(
            select(col(Tag.name), col(Tag.display_name))
            .where(col(Tag.name).in_(tag_names))
        ).all()

    display_names = [
        info[1] or info[0] for info in tags_info
    ]

    print(f"[OK] {f.filename} 标签已更新：{' '.join('#' + t for t in display_names)}")


def cmd_tag_rename(args: argparse.Namespace) -> None:
    """重命名标签的显示名称。"""
    idx = IndexManager()
    success = idx.update_tag_display_name(args.name, args.display_name)
    if success:
        print(f"[OK] 标签 #{args.name} 的显示名称已更新为：{args.display_name}")
    else:
        print(f"[ERROR] 未找到标签：#{args.name}")


def cmd_comment(args: argparse.Namespace) -> None:
    """编辑文件注释。"""
    idx = IndexManager()
    results = idx.search(SearchQuery(text=args.keyword, limit=1))
    if not results:
        print(f"未找到：{args.keyword}")
        return

    f = results[0].file
    idx.update_comment(f.id, args.text)
    print(f"[OK] {f.filename} 注释已更新")


def cmd_delete(args: argparse.Namespace) -> None:
    """从索引或知识库删除文件。"""
    idx = IndexManager()
    results = idx.search(SearchQuery(text=args.keyword, limit=1))
    if not results:
        print(f"未找到：{args.keyword}")
        return

    f = results[0].file
    print(f"将删除：{f.filename}  ({f.path})")

    if not args.yes:
        confirm = input("确认？[y/N] ").strip().lower()
        if confirm != "y":
            print("已取消")
            return

    if args.store:
        idx.delete_from_store(f.id)
        print(f"[OK] 已从知识库彻底删除：{f.filename}")
    else:
        idx.delete(f.id)
        print(f"[OK] 已从索引删除：{f.filename}")


def cmd_clean(args: argparse.Namespace) -> None:
    """扫描并清理孤立物理文件。"""
    idx = IndexManager()
    print("扫描中…")
    orphans, total_size = idx.scan_orphaned_files()

    for p in orphans:
        print(f"  {p}")

    if not orphans:
        print("✅ 知识库整洁，没有孤立文件。")
        return

    print(f"发现 {len(orphans)} 个孤立文件，共 {_fmt_size(total_size)}\n")

    if args.list:
        for p in orphans:
            print(f"  {p}")
        print()

    if args.dry_run:
        print("[DRY RUN] 不会删除任何文件")
        return

    if not args.yes:
        confirm = input("确认删除？[y/N] ").strip().lower()
        if confirm != "y":
            print("已取消")
            return

    deleted, freed = idx.clean_orphaned_files(orphans)
    print(f"✅ 已删除 {deleted} 个文件，释放 {_fmt_size(freed)}")


# ── 参数解析器构建 ────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """构建完整的 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="cairn",
        description="Cairn 知识库命令行工具",
    )
    sub = parser.add_subparsers(dest="command", metavar="<命令>")

    # ── search ────────────────────────────────────────────────
    p_search = sub.add_parser("search", help="全文检索")
    p_search.add_argument("text", nargs="?", default="", help="关键词")
    p_search.add_argument("--tag", action="append", help="按标签过滤（可多次）")
    p_search.add_argument("--ext", action="append", help="按扩展名过滤（可多次）")
    p_search.add_argument("--after", metavar="DATE", help="修改时间晚于（YYYY-MM-DD）")
    p_search.add_argument("--before", metavar="DATE", help="修改时间早于（YYYY-MM-DD）")
    p_search.add_argument("--size-min", metavar="SIZE", help="最小大小（如 1mb）")
    p_search.add_argument("--size-max", metavar="SIZE", help="最大大小（如 500kb）")
    p_search.add_argument("--folder", action="store_true", help="只显示文件夹")
    p_search.add_argument("--limit", type=int, default=20, help="结果数量（默认 20）")
    p_search.add_argument("--offset", type=int, default=0, help="分页偏移")
    p_search.add_argument("--no-snippet", action="store_true", help="不显示匹配片段")
    p_search.add_argument("--summary", action="store_true", help="显示摘要")
    p_search.set_defaults(func=cmd_search)

    # ── recent ────────────────────────────────────────────────
    p_recent = sub.add_parser("recent", help="最近索引的文件")
    p_recent.add_argument("limit", nargs="?", type=int, default=10, help="数量（默认 10）")
    p_recent.set_defaults(func=cmd_recent)

    # ── tags ──────────────────────────────────────────────────
    p_tags = sub.add_parser("tags", help="列出所有标签")
    p_tags.add_argument("--sort", choices=["count", "name"], default="count", help="排序方式")
    p_tags.set_defaults(func=cmd_tags)

    # ── tag-files ─────────────────────────────────────────────
    p_tf = sub.add_parser("tag-files", help="列出指定标签下的文件")
    p_tf.add_argument("name", help="标签名（不含 #）")
    p_tf.set_defaults(func=cmd_tag_files)

    # ── suggest ───────────────────────────────────────────────
    p_sug = sub.add_parser("suggest", help="输入补全建议")
    p_sug.add_argument("prefix", nargs="?", default="", help="前缀")
    p_sug.set_defaults(func=cmd_suggest)

    # ── info ──────────────────────────────────────────────────
    p_info = sub.add_parser("info", help="查看文件详情")
    p_info.add_argument("keyword", help="文件名关键词")
    p_info.set_defaults(func=cmd_info)

    # ── stats ─────────────────────────────────────────────────
    p_stats = sub.add_parser("stats", help="知识库统计概览")
    p_stats.set_defaults(func=cmd_stats)

    # ── restore ───────────────────────────────────────────────
    p_restore = sub.add_parser("restore", help="还原文件到原始位置")
    p_restore.add_argument("keyword", help="文件名关键词")
    p_restore.add_argument("--dest", metavar="PATH", help="指定目标路径")
    p_restore.add_argument("--overwrite", action="store_true", help="目标已存在时覆盖")
    p_restore.set_defaults(func=cmd_restore)

    # ── tag-edit ──────────────────────────────────────────────
    p_te = sub.add_parser("tag-edit", help="编辑文件标签")
    p_te.add_argument("keyword", help="文件名关键词")
    p_te.add_argument("tags", help="标签（逗号分隔）")
    p_te.add_argument("--add", action="store_true", help="追加标签（不覆盖）")
    p_te.add_argument("--remove", action="store_true", help="移除指定标签")
    p_te.set_defaults(func=cmd_tag_edit)

    # ── tag-rename ─────────────────────────────────────────────
    p_tr = sub.add_parser("tag-rename", help="重命名标签的显示名称")
    p_tr.add_argument("name", help="标签名（不含 #）")
    p_tr.add_argument("display_name", help="新的显示名称")
    p_tr.set_defaults(func=cmd_tag_rename)

    # ── comment ───────────────────────────────────────────────
    p_comment = sub.add_parser("comment", help="编辑文件注释")
    p_comment.add_argument("keyword", help="文件名关键词")
    p_comment.add_argument("text", help="注释内容")
    p_comment.set_defaults(func=cmd_comment)

    # ── delete ────────────────────────────────────────────────
    p_del = sub.add_parser("delete", help="删除文件")
    p_del.add_argument("keyword", help="文件名关键词")
    p_del.add_argument("--store", action="store_true", help="同时删除物理文件")
    p_del.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    p_del.set_defaults(func=cmd_delete)

    # ── clean ─────────────────────────────────────────────────
    p_clean = sub.add_parser("clean", help="清理孤立物理文件")
    p_clean.add_argument("--dry-run", action="store_true", help="只扫描，不删除")
    p_clean.add_argument("--list", action="store_true", help="列出孤立文件路径")
    p_clean.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    p_clean.set_defaults(func=cmd_clean)

    return parser


# ── 入口 ──────────────────────────────────────────────────────

def main() -> None:
    """CLI 主入口。"""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n已中断")
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
