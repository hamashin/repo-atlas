"""python -m atlas [run|migrate|check]

終了コード:
  0 正常 (公開見送り・持ち越しがあっても通知済みなら 0)
  1 致命的エラー (systemd 側で通知・再実行)
  3 一部失敗。通知はアプリ側で済んでいる (systemd 側では再実行のみ)
"""

from __future__ import annotations

import argparse
import logging
import sys

from .settings import Settings, SettingsError

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_REPORTED_FAILURE = 3


def _cmd_migrate(settings: Settings) -> int:
    from .store import StateStore

    store = StateStore(settings.db_path, settings.migrations_dir)
    applied = store.migrate()
    store.close()
    logging.info("マイグレーション適用: %s", ", ".join(applied) or "なし")
    return EXIT_OK


def _cmd_check(settings: Settings) -> int:
    from .github import GitHubClient
    from .llm import OllamaClient
    from .publisher import AtlasWorkspace

    ok = True
    try:
        repos = GitHubClient(settings.github_api_url, settings.github_token).list_repos(settings.github_owner)
        logging.info("GitHub: %d リポジトリを取得できました", len(repos))
    except Exception as exc:
        ok = False
        logging.error("GitHub: 失敗 (%s)", exc)
    try:
        models = OllamaClient(
            settings.ollama_url, settings.ollama_model, 10, settings.ollama_num_ctx,
            settings.ollama_disable_think, settings.prompts_dir,
        ).ping()
        if settings.ollama_model in models:
            logging.info("Ollama: モデル %s を確認しました", settings.ollama_model)
        else:
            ok = False
            logging.error("Ollama: モデル %s がありません", settings.ollama_model)
    except Exception as exc:
        ok = False
        logging.error("Ollama: 失敗 (%s)", type(exc).__name__)
    try:
        AtlasWorkspace(
            settings.workspace_dir, settings.atlas_ssh_url, settings.atlas_branch, settings.deploy_key_path,
            settings.known_hosts_path, settings.git_author_name, settings.git_author_email,
        ).check_remote()
        logging.info("Deploy key: 公開リポジトリに接続できました")
    except Exception as exc:
        ok = False
        logging.error("Deploy key: 失敗 (%s)", exc)
    return EXIT_OK if ok else EXIT_FATAL


def _cmd_run(settings: Settings) -> int:
    from .pipeline import Pipeline

    report = Pipeline(settings).run()
    logging.info(report.message(settings.dry_run))
    return EXIT_REPORTED_FAILURE if report.retryable_failure else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "migrate", "check"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        logging.error("%s", exc)
        return EXIT_FATAL
    handler = {"run": _cmd_run, "migrate": _cmd_migrate, "check": _cmd_check}[args.command]
    try:
        return handler(settings)
    except Exception:
        logging.exception("致命的なエラー")
        return EXIT_FATAL


if __name__ == "__main__":
    sys.exit(main())
