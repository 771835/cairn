# coding=utf-8
import re
from datetime import datetime
from typing import Final

from cairn.plugins.api import BaseOperator
from cairn.plugins.registry import OperatorRegistry
from cairn.utils.logger import get_logger

logger = get_logger(__name__)

# typeof 支持的文件类型族
_TYPE_GROUPS: Final[dict[str, set[str]]] = {
    "image": {
        "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico",
        "avif", "heif", "heic", "svg", "psd", "ai", "eps", "raw", "cr2",
        "nef", "orf", "rw2", "3mf"
    },
    "video": {
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "3gp", "ts", "mxf", "vob", "f4v"
    },
    "audio": {
        "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "aiff", "ape", "voc", "ac3"
    },
    "document": {
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "rtf",
        "epub", "mobi", "azw3", "tex", "cls", "sty", "ins", "dtx", "latexdoc"
    },
    "text": {
        "json", "xml", "yaml", "yml", "toml", "ini", "conf", "cfg", "env", "rc", "log", "markdown"
    },
    "code": {
        "py", "js", "ts", "jsx", "tsx", "vue", "svelte", "java", "cpp", "c", "h", "go", "rs", "rb", "php", "sh",
        "o", "a", "so", "dll", "exe", "jar", "war", "class", "m", "jl", "r", "f", "f90",  # 包含编译产物
        "sln", "csproj", "xcodeproj", "gyp", "dockerfile", "makefile", "podspec"
    },
    "web": {
        "html", "htm", "css", "woff", "woff2", "ttf", "eot", "webmanifest", "webp", "swf"
    },
    "archive": {
        "zip", "tar", "gz", "bz2", "xz", "7z", "rar", "zipx", "cab", "egg", "whl", "iso", "img", "dmg", "nrg"
    },
    "data": {
        "db", "db3", "sqlite", "sqlite3", "sql", "mdb", "accdb", "dbf", "parquet", "feather"
    },
    "code_packaged": {  # Python wheel/jar
        "whl", "egg"
    },
    "system": {
        "desktop", "link", "url", "bak", "tmp", "pid", "lock", "pdb"
    },

    # 3D 建模与工程 CAD (建筑设计、游戏资产)
    "3d_model": {
        "obj", "stl", "fbx", "gltf", "glb", "3ds", "dae", "blend", "ase", "ma", "mb",  # 3Ds Max, Maya, Blender
        "step", "stp", "igs", "sat", "sldprt", "sldasm", "catpart", "catproduct"  # Parametric CAD (SolidWorks, CATIA)
    },

    # 证书与密钥
    "certificate_secure": {
        "pem", "crt", "cer", "key", "pub", "asc", "p12", "pfx", "der", "chain", "csr"
    },

    # 音乐制作
    "music_composition": {
        "mid", "midi", "kar", "abc", "musicxml", "mscx", "mxl", "tsx"  # MusicXML, MuseScore
    },

    # 移动端应用包
    "mobile_pkg": {
        "apk", "aab", "ipa", "aab"  # Android APK, Android App Bundle, iOS IPA
    },

    # 数据库结构定义 (DDL)
    "database_schema": {
        "sql", "ddl", "dbx", "h2", "schema"  # 从 Data 中提取出的纯结构文件
    }
}


class StartsWithOperator(BaseOperator):
    """
    (filepath startswith "E:/知识库")
    字符串前缀匹配，忽略大小写。
    区别于 `in`：`in` 只检查子串存在，不关心位置。
    """
    name = "startswith"
    dsl_keyword = "startswith"

    def evaluate(self, actual, args: list) -> bool:
        return str(actual).lower().startswith(args[0].lower())


class EndsWithOperator(BaseOperator):
    """
    (filename endswith ".bak")
    字符串后缀匹配，忽略大小写。
    比 `~` 更明确，不需要写 `\\.bak$`。
    """
    name = "endswith"
    dsl_keyword = "endswith"

    def evaluate(self, actual, args: list) -> bool:
        return str(actual).lower().endswith(args[0].lower())


class MatchesOperator(BaseOperator):
    """
    (filename matches "^\\d{8}_")
    完整正则匹配（fullmatch），区别于 `~`（search）。
    `~` 只要在字符串任意位置找到模式即命中，
    `matches` 要求整个字段值符合模式。
    """
    name = "matches"
    dsl_keyword = "matches"

    def evaluate(self, actual, args: list) -> bool:
        try:
            return bool(re.fullmatch(args[0], str(actual), re.IGNORECASE))
        except re.error as e:
            logger.warning(f"matches 正则错误：{args[0]} — {e}")
            return False


class BeforeOperator(BaseOperator):
    """
    (modified before "2024-01-01")
    文件修改时间早于指定日期。
    支持格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS
    需要 FileContext 包含 modified 字段（datetime）。
    """
    name = "before"
    dsl_keyword = "before"

    def evaluate(self, actual, args: list) -> bool:
        try:
            actual_dt = self._to_dt(actual)
            expected_dt = self._to_dt(args[0])
            return actual_dt < expected_dt
        except (ValueError, TypeError) as e:
            logger.warning(f"before 时间解析失败：{e}")
            return False

    @staticmethod
    def _to_dt(v) -> datetime:
        if isinstance(v, datetime):
            return v
        s = str(v)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        raise ValueError(f"无法解析时间：{v}")


class AfterOperator(BaseOperator):
    """
    (modified after "2024-06-01")
    文件修改时间晚于指定日期，逻辑同 before。
    """
    name = "after"
    dsl_keyword = "after"

    def evaluate(self, actual, args: list) -> bool:
        try:
            actual_dt = BeforeOperator._to_dt(actual)
            expected_dt = BeforeOperator._to_dt(args[0])
            return actual_dt > expected_dt
        except (ValueError, TypeError) as e:
            logger.warning(f"after 时间解析失败：{e}")
            return False


class TypeOfOperator(BaseOperator):
    """
    (ext typeof "image")
    按文件类型族筛选，避免列举所有扩展名。
    支持类型族：image / video / audio / document /
                text / code / archive / data
    等价于把一堆 ext= 条件合并成一个语义标签。
    """
    name = "typeof"
    dsl_keyword = "typeof"

    def evaluate(self, actual, args: list) -> bool:
        group = _TYPE_GROUPS.get(str(args[0]).lower())
        if group is None:
            logger.warning(
                f"typeof 未知类型族：'{args[0]}'，"
                f"可用值：{list(_TYPE_GROUPS.keys())}"
            )
            return False
        return str(actual).lower().lstrip(".") in group


class SizeBetweenOperator(BaseOperator):
    """
    (size sizebetween (1mb, 10mb))
    文件大小范围判断（含两端）。
    expected 格式："<min>,<max>"，单位可带 kb/mb/gb。
    比 `size > 1mb, size < 10mb` 两条规则更紧凑。
    """
    name = "sizebetween"
    dsl_keyword = "sizebetween"

    def evaluate(self, actual, args: list) -> bool:
        if len(args) < 2:
            logger.warning(f"sizebetween 需要两个参数，收到：{args}")
            return False
        try:
            low = float(args[0])  # 已经是 str，不需要再 str()
            high = float(args[1])
            return low <= float(actual) <= high
        except (ValueError, TypeError) as e:
            logger.warning(f"sizebetween 解析失败：{e}")
            return False


# ── 注册 ──────────────────────────────────────────────────────

def register_builtin_operators():
    for op in (
            StartsWithOperator(),
            EndsWithOperator(),
            MatchesOperator(),
            BeforeOperator(),
            AfterOperator(),
            TypeOfOperator(),
            SizeBetweenOperator(),
    ):
        OperatorRegistry.register(op)
    logger.debug("内置扩展操作符已注册")
