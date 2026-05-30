#!/usr/bin/env python3
# coding=utf-8
"""
cairn_restore.py — Cairn 知识库文件还原脚本
 
用法：
    python cairn_restore.py --db <数据库路径> --store <存储根目录> [选项]
 
示例：
    python cairn_restore.py --db data/cairn.db --store data/.store
    python cairn_restore.py --db data/cairn.db --store data/.store --dry-run
    python cairn_restore.py --db data/cairn.db --store data/.store --no-origin F:/备份
"""
 
import argparse
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
 
 
# ── 数据结构 ──────────────────────────────────────────────────
 
@dataclass
class FileRecord:
    """数据库文件记录。"""
    id:          int
    path:        str        # 哈希存储路径
    origin_path: str | None # 原始路径
    filename:    str
    is_folder:   bool
    file_hash:   str | None
 
 
# ── 数据库读取 ────────────────────────────────────────────────
 
def load_records(db_path: Path) -> list[FileRecord]:
    """从数据库读取所有文件记录。"""
    if not db_path.exists():
        print(f"[ERROR] 数据库不存在：{db_path}")
        sys.exit(1)
 
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("""
            SELECT id, path, origin_path, filename, is_folder, file_hash
            FROM files
            ORDER BY id
        """)
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"[ERROR] 数据库查询失败：{e}")
        sys.exit(1)
    finally:
        conn.close()
 
    return [
        FileRecord(
            id          = row[0],
            path        = row[1],
            origin_path = row[2],
            filename    = row[3],
            is_folder   = bool(row[4]),
            file_hash   = row[5],
        )
        for row in rows
    ]
 
 
# ── 存储路径解析 ──────────────────────────────────────────────
 
def find_store_file(
    record:     FileRecord,
    store_root: Path,
) -> Path | None:
    """
    定位记录对应的物理文件。
    优先用 record.path（绝对路径），
    回退到 store_root / hash[:2] / hash 的哈希目录结构。
    """
    # 优先：直接用数据库里记录的 path
    direct = Path(record.path)
    if direct.exists():
        return direct
 
    # 回退：用 file_hash 在 store_root 下找
    if record.file_hash:
        hashed = store_root / record.file_hash[:2] / record.file_hash
        if hashed.exists():
            return hashed
 
    # 再回退：在 store_root 下递归搜索同哈希文件名
    if record.file_hash:
        for candidate in store_root.rglob(record.file_hash):
            if candidate.is_file():
                return candidate
 
    return None
 
 
# ── 目标路径确定 ──────────────────────────────────────────────
 
def resolve_dest(
    record:    FileRecord,
    no_origin: Path | None,
) -> Path | None:
    """
    确定文件还原目标路径。
 
    有 origin_path → 还原到原始位置
    无 origin_path 且指定了 --no-origin → 还原到该目录下
    无 origin_path 且未指定 → 跳过
    """
    if record.origin_path:
        return Path(record.origin_path)
 
    if no_origin is not None:
        return no_origin / record.filename
 
    return None
 
 
def safe_dest(dest: Path) -> Path:
    """
    若目标路径已存在，自动重命名避免覆盖。
    example.txt → example_1.txt → example_2.txt ...
    """
    if not dest.exists():
        return dest
    stem   = dest.stem
    suffix = dest.suffix
    i      = 1
    while True:
        candidate = dest.parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1
 
 
# ── 还原执行 ──────────────────────────────────────────────────
 
@dataclass
class RestoreResult:
    """还原结果统计。"""
    success:      int = 0
    skipped_no_origin:  int = 0
    skipped_no_store:   int = 0
    skipped_folder:     int = 0
    failed:       int = 0
 
 
def restore_all(
    records:    list[FileRecord],
    store_root: Path,
    no_origin:  Path | None,
    dry_run:    bool,
    verbose:    bool,
) -> RestoreResult:
    """执行全量还原，返回统计结果。"""
    result = RestoreResult()
 
    for rec in records:
 
        # 跳过文件夹聚合条目（子文件会单独还原）
        if rec.is_folder:
            result.skipped_folder += 1
            if verbose:
                print(f"[SKIP] 文件夹条目：{rec.filename}")
            continue
 
        # 找物理文件
        store_file = find_store_file(rec, store_root)
        if store_file is None:
            result.skipped_no_store += 1
            print(f"[MISS] 物理文件不存在：{rec.filename}  (id={rec.id})")
            continue
 
        # 确定目标路径
        dest = resolve_dest(rec, no_origin)
        if dest is None:
            result.skipped_no_origin += 1
            if verbose:
                print(f"[SKIP] 无原始路径：{rec.filename}  (id={rec.id})")
            continue
 
        dest = safe_dest(dest)
 
        if dry_run:
            print(f"[DRY ] {store_file}  →  {dest}")
            result.success += 1
            continue
 
        # 执行还原
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(store_file), str(dest))
            result.success += 1
            if verbose:
                print(f"[OK  ] {rec.filename}  →  {dest}")
        except Exception as e:
            result.failed += 1
            print(f"[FAIL] {rec.filename}：{e}")
 
    return result
 
 
# ── 入口 ──────────────────────────────────────────────────────
 
def main() -> None:
    """脚本主入口，解析参数并执行还原。"""
    parser = argparse.ArgumentParser(
        description="Cairn 知识库文件还原工具",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--db",
        required=True,
        metavar="PATH",
        help="数据库文件路径（cairn.db）",
    )
    parser.add_argument(
        "--store",
        required=True,
        metavar="PATH",
        help="哈希存储根目录（.store）",
    )
    parser.add_argument(
        "--no-origin",
        metavar="PATH",
        default=None,
        help="无原始路径的文件统一还原到此目录（不指定则跳过）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印操作，不实际复制文件",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="打印每个文件的详细操作",
    )
 
    args = parser.parse_args()
 
    db_path    = Path(args.db).resolve()
    store_root = Path(args.store).resolve()
    no_origin  = Path(args.no_origin).resolve() if args.no_origin else None
 
    if not store_root.exists():
        print(f"[ERROR] 存储目录不存在：{store_root}")
        sys.exit(1)
 
    print(f"数据库：{db_path}")
    print(f"存储目录：{store_root}")
    if no_origin:
        print(f"无原始路径回退目录：{no_origin}")
    if args.dry_run:
        print("[DRY RUN 模式，不会写入任何文件]")
    print()
 
    records = load_records(db_path)
    print(f"共读取 {len(records)} 条记录\n")
 
    result = restore_all(
        records    = records,
        store_root = store_root,
        no_origin  = no_origin,
        dry_run    = args.dry_run,
        verbose    = args.verbose,
    )
 
    print()
    print("── 还原结果 " + "─" * 30)
    print(f"  成功还原：{result.success} 个")
    print(f"  物理文件缺失：{result.skipped_no_store} 个")
    print(f"  无原始路径跳过：{result.skipped_no_origin} 个")
    print(f"  文件夹条目跳过：{result.skipped_folder} 个")
    print(f"  失败：{result.failed} 个")
 
 
if __name__ == "__main__":
    main()