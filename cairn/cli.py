# coding=utf-8
import sys
from datetime import datetime

from cairn.core.index.manager import IndexManager
from cairn.core.index.search import SearchQuery, SearchResult


def _fmt_size(size: int) -> str:
    for unit, t in [("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)]:
        if size >= t:
            return f"{size / t:.1f}{unit}"
    return f"{size}B"


def _print_results(results: list[SearchResult]):
    if not results:
        print("无结果")
        return
    for r in results:
        f = r.file
        folder_mark = "[文件夹] " if f.is_folder else ""
        mtime = f.modified_at.strftime("%Y-%m-%d") if f.modified_at else "?"
        tags = " ".join(f"#{t}" for t in f.tags)
        print(f"{folder_mark}{f.filename}  {_fmt_size(f.size)}  {mtime}  {tags}")
        print(f"  {f.path}")
        if r.snippet:
            clean = r.snippet.replace("<b>", "").replace("</b>", "")
            print(f"  {clean[:80]}")
        print()


def main():
    args = sys.argv[1:]

    if not args:
        print("Cairn CLI")
        print()
        print("用法：")
        print("  cairn search <关键词>              全文检索")
        print("  cairn search --tag <标签>           按标签")
        print("  cairn search --ext <扩展名>         按扩展名")
        print("  cairn search --after 2024-01-01    时间过滤")
        print("  cairn search --before 2024-12-31")
        print("  cairn search --size-min 1mb")
        print("  cairn search --folder              只显示文件夹")
        print("  cairn recent                       最近索引")
        print("  cairn tags                         所有标签")
        print("  cairn suggest <前缀>               输入补全")
        return

    idx = IndexManager()
    cmd = args[0]

    if cmd == "search":
        rest = args[1:]
        text = ""
        tags = []
        exts = []
        after = None
        before = None
        size_min = None
        size_max = None
        folder_only = False

        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--tag" and i + 1 < len(rest):
                tags.append(rest[i + 1])
                i += 2
            elif a == "--ext" and i + 1 < len(rest):
                exts.append(rest[i + 1])
                i += 2
            elif a == "--after" and i + 1 < len(rest):
                after = datetime.strptime(rest[i + 1], "%Y-%m-%d")
                i += 2
            elif a == "--before" and i + 1 < len(rest):
                before = datetime.strptime(rest[i + 1], "%Y-%m-%d")
                i += 2
            elif a == "--size-min" and i + 1 < len(rest):
                size_min = _parse_size(rest[i + 1])
                i += 2
            elif a == "--size-max" and i + 1 < len(rest):
                size_max = _parse_size(rest[i + 1])
                i += 2
            elif a == "--folder":
                folder_only = True
                i += 1
            else:
                text += (" " if text else "") + a
                i += 1

        results = idx.search(SearchQuery(
            text=text,
            tags=tags,
            ext=exts,
            modified_after=after,
            modified_before=before,
            size_min=size_min,
            size_max=size_max,
            is_folder=True if folder_only else None,
            limit=20,
        ))
        _print_results(results)

    elif cmd == "recent":
        limit = int(args[1]) if len(args) > 1 else 10
        results = idx.get_recent(limit)
        for f in results:
            print(f"{f.indexed_at.strftime('%Y-%m-%d %H:%M')}  {f.filename}")
            print(f"  {f.path}")

    elif cmd == "tags":
        for name, count in idx.get_all_tags():
            print(f"  #{name}  ({count})")

    elif cmd == "suggest":
        prefix = args[1] if len(args) > 1 else ""
        for s in idx.suggest(prefix):
            print(f"  {s}")

    else:
        print(f"未知命令：{cmd}")


def _parse_size(s: str) -> int:
    s = s.lower()
    units = {
        "pb": 1024 ** 5, "tb": 1024 ** 4, "t": 1024 ** 4,
        "gb": 1024 ** 3, "g": 1024 ** 3, "mb": 1024 ** 2,
        "m": 1024 ** 2, "kb": 1024, "k": 1024, "b": 1
    }
    for u, m in units.items():
        if s.endswith(u):
            return int(float(s[:-len(u)]) * m)
    return int(s)


if __name__ == "__main__":
    main()
