"""Markdown (Jinja2) と構成図 SVG (Graphviz) の生成。"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_SHAPES = {
    "user": ("ellipse", "#fdf2e9"),
    "service": ("box", "#eaf2fb"),
    "container": ("box3d", "#eaf2fb"),
    "job": ("component", "#eef7ee"),
    "storage": ("cylinder", "#f4f1fa"),
    "external": ("box", "#f5f5f5"),
    "device": ("box", "#fff8e1"),
    "library": ("note", "#f5f5f5"),
}
_FONT = "Noto Sans CJK JP"


@dataclass(frozen=True)
class IndexEntry:
    name: str
    summary: str
    updated: str
    merged: str
    public: bool
    archived: bool


@dataclass(frozen=True)
class RepoPage:
    name: str
    level: str
    summary: str
    features: list[str]
    tech_stack: list[str]
    has_diagram: bool
    updated: str
    merged: str
    html_url: str | None
    public: bool
    archived: bool


def md_cell(value: str) -> str:
    """表のセルに入れられるようにする (改行・パイプ・HTML を無害化)。"""
    text = " ".join(str(value or "").split())
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def md_text(value: str) -> str:
    return " ".join(str(value or "").split()).replace("<", "&lt;").replace(">", "&gt;")


def _dot_str(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def build_dot(analysis: dict) -> str:
    lines = [
        "digraph G {",
        f'  graph [rankdir=LR, bgcolor="white", pad=0.3, nodesep=0.5, ranksep=0.7, fontname={_dot_str(_FONT)}];',
        f'  node [style="filled,rounded", color="#5b6b7a", fontname={_dot_str(_FONT)}, fontsize=12];',
        f'  edge [color="#5b6b7a", fontname={_dot_str(_FONT)}, fontsize=10];',
    ]
    for c in analysis.get("components", []):
        shape, fill = _SHAPES.get(c["kind"], _SHAPES["service"])
        lines.append(f'  {c["id"]} [label={_dot_str(c["label"])}, shape={shape}, fillcolor="{fill}"];')
    for r in analysis.get("relations", []):
        lines.append(f'  {r["source"]} -> {r["target"]} [label={_dot_str(r["label"])}];')
    lines.append("}")
    return "\n".join(lines)


class Renderer:
    def __init__(self, templates_dir: Path, dot_binary: str = "dot"):
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._env.filters["cell"] = md_cell
        self._env.filters["text"] = md_text
        self._dot = shutil.which(dot_binary)

    def index(self, owner: str, entries: list[IndexEntry], generated_at: datetime) -> str:
        return self._env.get_template("index.md.j2").render(
            owner=owner,
            entries=entries, generated_at=generated_at.strftime("%Y-%m-%d %H:%M"), count=len(entries)
        )

    def repo_page(self, page: RepoPage) -> str:
        return self._env.get_template("repo.md.j2").render(page=page)

    def diagram_svg(self, analysis: dict) -> str | None:
        if not analysis.get("components") or self._dot is None:
            return None
        proc = subprocess.run(
            [self._dot, "-Tsvg"], input=build_dot(analysis), capture_output=True, text=True, timeout=60
        )
        if proc.returncode != 0:
            raise RuntimeError("Graphviz で構成図を描画できませんでした")
        return proc.stdout
