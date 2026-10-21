from datetime import datetime
from pathlib import Path

from atlas.llm import normalize_analysis
from atlas.render import IndexEntry, Renderer, RepoPage, build_dot, md_cell
from atlas.store import RepoState, StateStore

ROOT = Path(__file__).resolve().parents[1]


def test_normalize_analysis_cleans_ids_and_relations():
    raw = {
        "summary": "  概要\n です ",
        "features": ["a", "", "b"],
        "tech_stack": ["Python"],
        "components": [
            {"id": "Web Server", "label": "Web", "kind": "service"},
            {"id": "db", "label": "DB", "kind": "unknown"},
            {"id": "db", "label": "dup", "kind": "storage"},
        ],
        "relations": [
            {"source": "web server", "target": "db", "label": "保存"},
            {"source": "web_server", "target": "ghost", "label": "x"},
        ],
    }
    out = normalize_analysis(raw)
    assert out["summary"] == "概要 です"
    assert out["features"] == ["a", "b"]
    assert [c["id"] for c in out["components"]] == ["web_server", "db"]
    assert out["components"][1]["kind"] == "service"
    assert out["relations"] == [{"source": "web_server", "target": "db", "label": "保存"}]


def test_build_dot_escapes_labels():
    dot = build_dot({"components": [{"id": "a", "label": 'x"y', "kind": "user"}], "relations": []})
    assert 'label="x\\"y"' in dot


def test_md_cell_escapes():
    assert md_cell("a|b\nc<script>") == "a\\|b c&lt;script&gt;"


def test_render_pages():
    r = Renderer(ROOT / "templates")
    index = r.index(
        "owner",
        [IndexEntry("demo", "説明|です", "2026-10-21", "2026-10-20 機能追加", public=False, archived=True)],
        datetime(2026, 10, 21, 8, 0),
    )
    assert "| [demo](repos/demo/) 🔒 🗄️ | 説明\\|です | 2026-10-21 | 2026-10-20 機能追加 |" in index
    page = RepoPage("demo", "summary", "概要", ["f1"], ["Python"], False, "2026-10-21", "なし", None, False, False)
    md = r.repo_page(page)
    assert "## 概要" in md and "主な機能" not in md and "GitHub:" not in md
    full = RepoPage("demo", "full", "概要", ["f1"], ["Python"], True, "2026-10-21", "なし",
                    "https://github.com/o/demo", True, False)
    md = r.repo_page(full)
    assert "- f1" in md and "architecture.svg" in md and "https://github.com/o/demo" in md


def test_store_migrate_and_roundtrip(tmp_path):
    store = StateStore(tmp_path / "s.db", ROOT / "migrations")
    assert store.migrate() == ["0001_init", "0002_attempts"]
    assert store.migrate() == []
    store.save(RepoState("demo", "abc", "full", "1", {"summary": "x"}, "pr:1", "line"))
    got = store.get("demo")
    assert got.analysis == {"summary": "x"} and got.last_merged_key == "pr:1"
    store.delete("demo")
    assert store.get("demo") is None


def test_store_attempts(tmp_path):
    store = StateStore(tmp_path / "s.db", ROOT / "migrations")
    store.migrate()
    store.record_attempt("demo", ok=False)
    store.record_attempt("demo", ok=False)
    assert store.attempts()["demo"][0] == 2
    store.record_attempt("demo", ok=True)
    assert store.attempts()["demo"][0] == 0
