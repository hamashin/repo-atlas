-- LLM 解析の試行履歴。失敗が続くリポジトリを後回しにするために使う
CREATE TABLE IF NOT EXISTS attempts (
    name            TEXT PRIMARY KEY,
    last_attempt_at TEXT NOT NULL,
    failures        INTEGER NOT NULL DEFAULT 0
);
