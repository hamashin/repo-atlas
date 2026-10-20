"""SQLite による処理状態の保存とマイグレーション。"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_VERSION_RE = re.compile(r"\d{4}_[a-z0-9_]+")

@dataclass
class RepoState:
    name: str
    head_sha: str | None
    level: str
    generator_version: str
    analysis: dict | None
    last_merged_key: str | None
    last_merged_line: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateStore:
    def __init__(self, db_path: Path, migrations_dir: Path):
        self._migrations_dir = migrations_dir
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def migrate(self) -> list[str]:
        """未適用の migrations/*.sql を名前順に適用し、適用したバージョンを返す。"""
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {r["version"] for r in self._conn.execute("SELECT version FROM schema_migrations")}
        done = []
        for path in sorted(self._migrations_dir.glob("*.sql")):
            version = path.stem
            if version in applied:
                continue
            if not _VERSION_RE.fullmatch(version):
                raise ValueError(f"マイグレーション名が不正です: {path.name}")
            # executescript は自前でトランザクションを張れないため、スクリプト内で BEGIN/COMMIT する
            self._conn.executescript(
                "BEGIN;\n"
                + path.read_text(encoding="utf-8")
                + f"\nINSERT INTO schema_migrations (version, applied_at) VALUES ('{version}', '{_now()}');\n"
                + "COMMIT;"
            )
            done.append(version)
        return done

    def get(self, name: str) -> RepoState | None:
        row = self._conn.execute("SELECT * FROM repos WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return RepoState(
            name=row["name"],
            head_sha=row["head_sha"],
            level=row["level"],
            generator_version=row["generator_version"],
            analysis=json.loads(row["analysis_json"]) if row["analysis_json"] else None,
            last_merged_key=row["last_merged_key"],
            last_merged_line=row["last_merged_line"],
        )

    def names(self) -> set[str]:
        return {r["name"] for r in self._conn.execute("SELECT name FROM repos")}

    def save(self, state: RepoState) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO repos (name, head_sha, level, generator_version, analysis_json,"
                " last_merged_key, last_merged_line, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET head_sha=excluded.head_sha, level=excluded.level,"
                " generator_version=excluded.generator_version, analysis_json=excluded.analysis_json,"
                " last_merged_key=excluded.last_merged_key, last_merged_line=excluded.last_merged_line,"
                " updated_at=excluded.updated_at",
                (
                    state.name,
                    state.head_sha,
                    state.level,
                    state.generator_version,
                    json.dumps(state.analysis, ensure_ascii=False) if state.analysis else None,
                    state.last_merged_key,
                    state.last_merged_line,
                    _now(),
                ),
            )

    def delete(self, name: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM repos WHERE name = ?", (name,))

    def start_run(self) -> int:
        with self._conn:
            cur = self._conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, detail: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE runs SET finished_at = ?, status = ?, detail = ? WHERE id = ?",
                (_now(), status, detail, run_id),
            )
