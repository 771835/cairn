# coding=utf-8
import re
from pathlib import Path
from cairn.core.parser.base import ParseResult
from cairn.plugins.api import ParserPlugin
from cairn.plugins.registry import ParserRegistry
from cairn.utils.logger import get_logger

logger = get_logger(__name__)

# 可全文索引的文本类扩展名
_TEXT_EXTENSIONS = {
    # 纯文本
    ".txt", ".log", ".csv", ".tsv",
    # 配置 / 标记语言
    ".json", ".jsonl", ".xml", ".yaml", ".yml", ".toml",
    ".ini", ".conf", ".cfg", ".env", ".rc",
    # 编程语言
    ".py", ".pyw", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".kt", ".kts", ".scala",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx",
    ".go", ".rs", ".rb", ".php", ".pl", ".pm",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".lua", ".r", ".R", ".jl", ".m", ".mm",
    ".sql", ".graphql", ".proto",
    # Web
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".vue", ".svelte",
    # 构建脚本
    ".dockerfile", ".makefile", ".cmake",
    ".gradle", ".properties",
    # 其他
    ".diff", ".patch", ".rsync",
    ".nix", ".dhall",
}

# 编程语言 → 标签映射
_LANG_TAG_MAP = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".ts": "typescript", ".jsx": "react", ".tsx": "react",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".lua": "lua", ".r": "r", ".R": "r", ".jl": "julia",
    ".sql": "sql", ".html": "html", ".css": "css",
    ".vue": "vue", ".svelte": "svelte",
    ".scala": "scala", ".m": "objectivec",
}


class TextParserPlugin(ParserPlugin):
    name = "text_parser"
    supported_extensions = sorted(_TEXT_EXTENSIONS)

    # 常见 import/include 模式
    _IMPORT_RE = re.compile(
        r"(?:import|from|require|include|#include|use)\s+"
        r"[\"'<]([^\"'>]+)[\"'>]",
        re.MULTILINE,
    )

    # URL 模式
    _URL_RE = re.compile(
        r"https?://[^\s<>\")\]]+", re.IGNORECASE
    )

    def parse(self, file_path: Path) -> ParseResult:
        try:
            # 尝试 UTF-8，回退到 latin-1 保证不崩
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="latin-1")
        except OSError as e:
            logger.warning(f"文本文件读取失败：{file_path.name} — {e}")
            return ParseResult(raw_path=file_path)

        metadata = {}
        tags = []
        links = []

        # ── 语言标签 ──
        ext = file_path.suffix.lower()
        lang = _LANG_TAG_MAP.get(ext)
        if lang:
            tags.append(lang)
            metadata["language"] = lang

        # ── 行数 / 字数 ──
        line_count = text.count("\n") + 1
        metadata["line_count"] = line_count
        metadata["word_count"] = len(text.split())

        # ── 检测 shebang ──
        if text.startswith("#!"):
            shebang = text.splitlines()[0].strip()
            metadata["shebang"] = shebang

        # ── 提取 import 引用（作为 links） ──
        imports = self._IMPORT_RE.findall(text)
        if imports:
            links.extend(imports[:50])  # 限制数量
            metadata["import_count"] = len(imports)

        # ── 提取 URL ──
        urls = self._URL_RE.findall(text)
        if urls:
            links.extend(urls[:20])
            metadata["url_count"] = len(urls)

        # ── 特殊格式处理 ──
        content = self._special_content(text, ext, metadata)

        # 截断超大文件内容（FTS5 不需要百万字全文）
        MAX_CONTENT = 200_000
        if len(content) > MAX_CONTENT:
            metadata["content_truncated"] = True

        return ParseResult(
            raw_path=file_path,
            metadata=metadata,
            tags=tags,
            links=links,
        )

    def _special_content(self, text: str, ext: str, metadata: dict) -> str:
        """对特定格式做轻度结构提取"""
        if ext == ".json":
            try:
                import json
                data = json.loads(text)
                if isinstance(data, dict):
                    metadata["json_top_keys"] = list(data.keys())[:20]
                    if "name" in data:
                        metadata["name"] = str(data["name"])
                    if "version" in data:
                        metadata["version"] = str(data["version"])
            except json.JSONDecodeError:
                pass

        elif ext in (".yaml", ".yml"):
            # 简易提取顶级键名
            keys = re.findall(r"^(\w[\w-]*)\s*:", text, re.MULTILINE)
            if keys:
                metadata["yaml_top_keys"] = keys[:20]

        elif ext == ".toml":
            keys = re.findall(r"^\[([^\]]+)\]", text, re.MULTILINE)
            if keys:
                metadata["toml_sections"] = keys[:20]

        elif ext == ".csv":
            lines = text.splitlines()
            if lines:
                metadata["csv_header"] = lines[0][:200]
                metadata["csv_row_count"] = max(0, len(lines) - 1)

        elif ext == ".html":
            # 提取 <title>
            title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
            if title_match:
                metadata["title"] = title_match.group(1).strip()
            # 提取 meta description
            desc_match = re.search(
                r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
                text, re.IGNORECASE
            )
            if desc_match:
                metadata["description"] = desc_match.group(1)
            # 剥离 HTML 标签作为内容
            text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
            text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)

        return text.strip()


class MoreParsersPlugin:
    def __init__(self):
        pass

    def validate(self):
        return True, None

    def initialize(self):
        return

    def load(self):
        # 注册解析器
        ParserRegistry.register(TextParserPlugin())

