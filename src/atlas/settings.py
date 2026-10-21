"""環境変数 (.env) から設定を読み込む。値はすべて .env に集約し、コードには持たない。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

LEVELS = ("full", "summary", "hidden")


class SettingsError(Exception):
    pass


def _csv(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(",") if v.strip())


def _bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    github_owner: str
    github_api_url: str
    github_token: str
    atlas_repo: str
    atlas_ssh_url: str
    atlas_branch: str
    git_author_name: str
    git_author_email: str
    ollama_url: str
    ollama_model: str
    ollama_timeout_sec: int
    ollama_num_ctx: int
    ollama_disable_think: bool
    slack_webhook_url: str
    default_level: str
    internal_domains: tuple[str, ...]
    deny_terms: tuple[str, ...]
    extra_exclude_globs: tuple[str, ...]
    max_input_chars: int
    max_tarball_bytes: int
    min_listing_ratio: float
    tz: str
    run_deadline_sec: int
    min_llm_sec: int
    dry_run: bool
    data_dir: Path
    app_dir: Path
    repos_config_path: Path
    deploy_key_path: Path
    known_hosts_path: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "state.sqlite3"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "atlas"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def migrations_dir(self) -> Path:
        return self.app_dir / "migrations"

    @property
    def templates_dir(self) -> Path:
        return self.app_dir / "templates"

    @property
    def prompts_dir(self) -> Path:
        return self.app_dir / "prompts"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env

        def req(key: str) -> str:
            value = env.get(key, "").strip()
            if not value:
                raise SettingsError(f"{key} が .env に設定されていません")
            return value

        def opt(key: str, default: str = "") -> str:
            return env.get(key, default).strip() or default

        default_level = opt("DEFAULT_LEVEL", "summary")
        if default_level not in LEVELS:
            raise SettingsError(f"DEFAULT_LEVEL は {LEVELS} のいずれか: {default_level}")

        return cls(
            github_owner=req("GITHUB_OWNER"),
            github_api_url=opt("GITHUB_API_URL", "https://api.github.com").rstrip("/"),
            github_token=req("GITHUB_TOKEN"),
            atlas_repo=req("ATLAS_REPO"),
            atlas_ssh_url=req("ATLAS_SSH_URL"),
            atlas_branch=opt("ATLAS_BRANCH", "main"),
            git_author_name=req("GIT_AUTHOR_NAME"),
            git_author_email=req("GIT_AUTHOR_EMAIL"),
            ollama_url=req("OLLAMA_URL").rstrip("/"),
            ollama_model=req("OLLAMA_MODEL"),
            ollama_timeout_sec=int(opt("OLLAMA_TIMEOUT_SEC", "240")),
            ollama_num_ctx=int(opt("OLLAMA_NUM_CTX", "16384")),
            ollama_disable_think=_bool(opt("OLLAMA_DISABLE_THINK", "true")),
            slack_webhook_url=opt("SLACK_WEBHOOK_URL"),
            default_level=default_level,
            internal_domains=_csv(opt("INTERNAL_DOMAINS")),
            deny_terms=_csv(opt("DENY_TERMS")),
            extra_exclude_globs=_csv(opt("EXTRA_EXCLUDE_GLOBS")),
            max_input_chars=int(opt("MAX_INPUT_CHARS", "30000")),
            max_tarball_bytes=int(opt("MAX_TARBALL_MB", "200")) * 1024 * 1024,
            min_listing_ratio=float(opt("MIN_LISTING_RATIO", "0.5")),
            tz=opt("TZ", "Asia/Tokyo"),
            run_deadline_sec=int(opt("RUN_DEADLINE_SEC", "1080")),
            min_llm_sec=int(opt("MIN_LLM_SEC", "300")),
            dry_run=_bool(opt("DRY_RUN", "false")),
            data_dir=Path(opt("DATA_DIR", "/data")),
            app_dir=Path(opt("APP_DIR", "/app")),
            repos_config_path=Path(opt("REPOS_CONFIG_PATH", "/config/repos.yaml")),
            deploy_key_path=Path(opt("DEPLOY_KEY_PATH", "/run/secrets/deploy_key")),
            known_hosts_path=Path(opt("KNOWN_HOSTS_PATH", "/run/secrets/known_hosts")),
        )
