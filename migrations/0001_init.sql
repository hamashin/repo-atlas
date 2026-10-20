-- 各リポジトリの処理状態 (生成済み内容のキャッシュ)
CREATE TABLE IF NOT EXISTS repos (
    name              TEXT PRIMARY KEY,
    head_sha          TEXT,
    level             TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    analysis_json     TEXT,
    last_merged_key   TEXT,
    last_merged_line  TEXT,
    updated_at        TEXT NOT NULL
);

-- 実行履歴
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,
    detail      TEXT
);
