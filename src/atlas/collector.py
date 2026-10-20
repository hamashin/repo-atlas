"""tarball を展開し、LLM に渡すソースを優先度順・上限付きで集める。

除外対象のファイルは読み込まず、読み込んだ内容とファイル名はすべてマスクしてから返す。
"""

from __future__ import annotations

import fnmatch
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .sanitizer import PathFilter, Sanitizer

# 優先度の高い順。一致しないファイルは最後に浅い階層・小さい順で拾う。
_PRIORITY_GLOBS = (
    ("README*", "readme*"),
    ("docs/*.md", "doc/*.md", "*.md"),
    (
        "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "package.json", "go.mod",
        "Cargo.toml", "Gemfile", "pom.xml", "build.gradle*", "composer.json", "*.csproj",
    ),
    (
        "Containerfile", "Dockerfile", "*compose*.y*ml", "*.container", "*.timer", "*.service",
        "install.sh", "install.ps1", "Makefile", "*.tf", "ansible.cfg", "playbook*.y*ml",
    ),
)
_SOURCE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java", ".kt", ".swift", ".c", ".h",
    ".cpp", ".cs", ".php", ".sh", ".ps1", ".lua", ".yaml", ".yml", ".toml", ".ini", ".conf", ".sql",
    ".html", ".css", ".vue", ".svelte", ".ino",
}
_SKIP_DIRS = {"node_modules", "vendor", "dist", "build", ".venv", "venv", "__pycache__", "target", ".next"}
_MAX_FILE_BYTES = 200 * 1024
_TREE_LIMIT = 300


@dataclass
class CollectedSource:
    tree: list[str] = field(default_factory=list)
    documents: list[tuple[str, str]] = field(default_factory=list)
    truncated: bool = False

    def as_prompt(self) -> str:
        parts = ["## ファイル構成", *self.tree]
        for path, text in self.documents:
            parts.append(f"\n## ファイル: {path}\n{text}")
        if self.truncated:
            parts.append("\n(入力上限のため一部のファイルは省略)")
        return "\n".join(parts)


def _priority(rel: str) -> tuple[int, int, int]:
    path = PurePosixPath(rel)
    for rank, globs in enumerate(_PRIORITY_GLOBS):
        if any(fnmatch.fnmatch(path.name, g) or fnmatch.fnmatch(rel, g) for g in globs):
            return (rank, len(path.parts), 0)
    return (len(_PRIORITY_GLOBS), len(path.parts), 0)


def _read_text(path: Path) -> str | None:
    if path.stat().st_size > _MAX_FILE_BYTES:
        return None
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class SourceCollector:
    def __init__(self, path_filter: PathFilter, sanitizer: Sanitizer, max_chars: int):
        self._filter = path_filter
        self._sanitizer = sanitizer
        self._max_chars = max_chars

    def collect(self, tarball: Path, work_dir: Path) -> CollectedSource:
        with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
            root = Path(tmp)
            with tarfile.open(tarball, "r:gz") as tf:
                # data フィルタでパストラバーサル・デバイスファイル等を拒否する
                tf.extractall(root, filter="data")
            tops = [p for p in root.iterdir() if p.is_dir()]
            base = tops[0] if len(tops) == 1 else root
            return self._collect_dir(base)

    def _collect_dir(self, base: Path) -> CollectedSource:
        files = []
        for path in base.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if any(part in _SKIP_DIRS for part in PurePosixPath(rel).parts):
                continue
            if self._filter.is_excluded(rel):
                continue
            files.append(rel)

        result = CollectedSource()
        result.tree = [self._sanitizer.mask(f) for f in sorted(files)[:_TREE_LIMIT]]
        if len(files) > _TREE_LIMIT:
            result.tree.append(f"... ほか {len(files) - _TREE_LIMIT} ファイル")

        budget = self._max_chars - sum(len(t) + 1 for t in result.tree)
        per_file = max(2000, self._max_chars // 4)
        for rel in sorted(files, key=_priority):
            rank = _priority(rel)[0]
            if rank == len(_PRIORITY_GLOBS) and PurePosixPath(rel).suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            text = _read_text(base / rel)
            if not text or not text.strip():
                continue
            text = self._sanitizer.mask(text[:per_file])
            if len(text) + 50 > budget:
                result.truncated = True
                if budget < 2000:
                    break
                text = text[: budget - 50]
            result.documents.append((self._sanitizer.mask(rel), text))
            budget -= len(text) + 50
        return result
