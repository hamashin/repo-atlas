"""1 回分の更新処理。"""

from __future__ import annotations

import logging
import tempfile
import time
import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import GENERATOR_VERSION
from .collector import SourceCollector
from .github import GitHubClient, MergeInfo, RepoMeta
from .llm import LLMError, OllamaClient
from .notify import SlackNotifier
from .publisher import INDEX_FILE, AtlasWorkspace
from .render import IndexEntry, Renderer, RepoPage
from .sanitizer import Finding, GitleaksScanner, PathFilter, Sanitizer
from .settings import LEVELS, Settings, SettingsError
from .store import RepoState, StateStore

DIAGRAM_FILE = "architecture.svg"
PAGE_FILE = "README.md"


class BlockedError(Exception):
    """機密情報の疑いがあり公開を見送った。"""

    def __init__(self, findings: list[Finding]):
        self.findings = findings
        super().__init__(", ".join(sorted({f.kind for f in findings})))


@dataclass
class RunReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    analyzed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    pushed: bool = False

    @property
    def has_backlog(self) -> bool:
        return bool(self.deferred)

    @property
    def retryable_failure(self) -> bool:
        return bool(self.errors)

    def needs_notice(self) -> bool:
        # エラー・公開見送りは都度通知。持ち越しが残る途中の実行では、更新の通知を最後の実行まで控える
        if self.blocked or self.errors or self.notes:
            return True
        return self.pushed and not self.has_backlog

    def message(self, dry_run: bool) -> str:
        head = "repo-atlas: 更新しました" if self.pushed else "repo-atlas: 実行結果"
        if dry_run:
            head += " (DRY_RUN: push していません)"
        lines = [head]
        for label, items in (("追加", self.added), ("更新", self.updated), ("削除", self.removed), ("続きの実行に持ち越し", self.deferred)):
            if items:
                lines.append(f"• {label} {len(items)} 件: {', '.join(items)}")
        for name, kinds in self.blocked:
            lines.append(f"• :warning: 機密情報の疑いで公開見送り: {name} ({kinds})")
        for name, msg in self.errors:
            lines.append(f"• :x: エラー: {name}: {msg}")
        lines.extend(f"• {n}" for n in self.notes)
        if self.errors:
            lines.append("失敗があるため、30 分後に 1 回だけ再実行します (再実行でも失敗した場合は翌日の定期実行で再挑戦)。")
        return "\n".join(lines)


def load_levels(path: Path, default: str) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    levels = {}
    for name, level in (data.get("repos") or {}).items():
        if level not in LEVELS:
            raise SettingsError(f"repos.yaml の公開レベルが不正です: {name}: {level}")
        levels[str(name)] = level
    return levels


class Budget:
    """1 回の実行の持ち時間。コンテナのタイムアウトより短い RUN_DEADLINE_SEC で区切る。"""

    def __init__(self, deadline_sec: int):
        self._deadline = time.monotonic() + deadline_sec

    def remaining(self) -> float:
        return self._deadline - time.monotonic()


class Pipeline:
    def __init__(self, settings: Settings):
        self.s = settings
        self._log = logging.getLogger("atlas.pipeline")
        self._tz = ZoneInfo(settings.tz)
        self.sanitizer = Sanitizer(settings.internal_domains, settings.deny_terms)
        self.store = StateStore(settings.db_path, settings.migrations_dir)
        self.github = GitHubClient(settings.github_api_url, settings.github_token)
        self.llm = OllamaClient(
            settings.ollama_url, settings.ollama_model, settings.ollama_timeout_sec,
            settings.ollama_num_ctx, settings.ollama_disable_think, settings.prompts_dir,
        )
        self.collector = SourceCollector(PathFilter(settings.extra_exclude_globs), self.sanitizer, settings.max_input_chars)
        self.renderer = Renderer(settings.templates_dir)
        self.gitleaks = GitleaksScanner()
        self.workspace = AtlasWorkspace(
            settings.workspace_dir, settings.atlas_ssh_url, settings.atlas_branch, settings.deploy_key_path,
            settings.known_hosts_path, settings.git_author_name, settings.git_author_email,
        )
        self.notifier = SlackNotifier(settings.slack_webhook_url)

    # ---- 補助 ----
    def _date(self, value: datetime) -> str:
        return value.astimezone(self._tz).strftime("%Y-%m-%d")

    def _scan(self, text: str, location: str) -> None:
        findings = self.sanitizer.scan(text, location)
        if findings:
            raise BlockedError(findings)

    def _merge_line(
        self, repo: RepoMeta, merge: MergeInfo | None, prev: RepoState | None, budget: Budget
    ) -> tuple[str | None, str]:
        if merge is None:
            return None, "なし"
        if prev and prev.last_merged_key == merge.key and prev.last_merged_line:
            return merge.key, prev.last_merged_line
        title = self.sanitizer.mask(merge.title)
        line = ""
        summarized = False
        if budget.remaining() >= self.s.min_llm_sec:
            try:
                line = self.llm.summarize_merge(
                    repo.name, title, self.sanitizer.mask(merge.body), timeout=budget.remaining()
                )
                summarized = bool(line)
            except LLMError:
                line = ""
        if not line or self.sanitizer.scan(line, "merge"):
            line, summarized = title, False
        if self.sanitizer.scan(line, "merge"):
            line = "(非公開の内容)"
        # タイトルで代用した場合はキーを保存せず、時間のある実行で要約し直す
        return (merge.key if summarized else None), f"{self._date(merge.merged_at)} {line}"

    def _analyze(self, repo: RepoMeta, head_sha: str, budget: Budget) -> dict:
        self.s.tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.s.tmp_dir) as tmp:
            tarball = Path(tmp) / "src.tar.gz"
            self.github.download_tarball(repo, head_sha, tarball, self.s.max_tarball_bytes)
            source = self.collector.collect(tarball, Path(tmp))
        prompt = source.as_prompt()
        self._log.info("%s: Ollama で解析中 (入力 %d 文字、上限 %d 秒)", repo.name, len(prompt), budget.remaining())
        return self.llm.analyze(repo.name, self.sanitizer.mask(repo.description), prompt, timeout=budget.remaining())

    # ---- リポジトリ 1 件 ----
    def _process(self, repo: RepoMeta, level: str, budget: Budget, report: RunReport) -> IndexEntry:
        prev = self.store.get(repo.name)
        head = self.github.head_sha(repo)
        if repo.full_name.lower() == self.s.atlas_repo.lower():
            # 自分自身は bot の push で毎回 HEAD が変わるため、生成物以外の最終コミットで判定する
            head = self.workspace.last_code_commit() or head
        analysis = prev.analysis if prev else None
        analyzed_sha = prev.head_sha if prev else None
        version = prev.generator_version if prev else "0"
        stale = analysis is None or analyzed_sha != head or version != GENERATOR_VERSION

        if stale and head is not None:
            # 1 回の実行で最低 1 件は必ず解析する (遅くても止まらずに進める)
            if budget.remaining() >= self.s.min_llm_sec or not report.analyzed:
                report.analyzed.append(repo.name)
                started = time.monotonic()
                try:
                    analysis = self._analyze(repo, head, budget)
                    analyzed_sha, version = head, GENERATOR_VERSION
                    self.store.record_attempt(repo.name, ok=True)
                    self._log.info("%s: 解析完了 (%d 秒)", repo.name, time.monotonic() - started)
                except LLMError as exc:
                    self.store.record_attempt(repo.name, ok=False)
                    report.errors.append((repo.name, str(exc)))
                    self._log.warning("%s: 解析失敗 (%s)", repo.name, exc)
            else:
                report.deferred.append(repo.name)
                self._log.info("%s: 残り時間が少ないため続きの実行に持ち越し", repo.name)
        else:
            self._log.info("%s: 変更なし", repo.name)
        saved_analysis = analysis
        if analysis is None:
            fallback = self.sanitizer.mask(repo.description) or ("(コミットなし)" if head is None else "(解析待ち)")
            analysis = {"summary": fallback, "features": [], "tech_stack": [], "components": [], "relations": []}

        merge_key, merge_line = self._merge_line(repo, self.github.last_merged(repo, head), prev, budget)

        page = RepoPage(
            name=repo.name,
            level=level,
            summary=analysis["summary"],
            features=analysis.get("features", []),
            tech_stack=analysis.get("tech_stack", []),
            has_diagram=False,
            updated=self._date(repo.pushed_at),
            merged=merge_line,
            html_url=None if repo.private else repo.html_url,
            public=not repo.private,
            archived=repo.archived,
        )
        svg = self.renderer.diagram_svg(analysis) if level == "full" else None
        if svg:
            page = replace(page, has_diagram=True)
        markdown = self.renderer.repo_page(page)

        # 公開前の検査。1 件でも検出したら書き込まない (前回の公開内容が残る)
        self._scan(markdown, f"{repo.name}/{PAGE_FILE}")
        if svg:
            self._scan(svg, f"{repo.name}/{DIAGRAM_FILE}")

        rel_dir = f"repos/{repo.name}"
        is_new = not (self.workspace.path / rel_dir / PAGE_FILE).exists()
        self.workspace.write(f"{rel_dir}/{PAGE_FILE}", markdown)
        if svg:
            self.workspace.write(f"{rel_dir}/{DIAGRAM_FILE}", svg)
        else:
            self.workspace.remove_file(f"{rel_dir}/{DIAGRAM_FILE}")

        self.store.save(
            RepoState(
                name=repo.name,
                head_sha=analyzed_sha,
                level=level,
                generator_version=version,
                analysis=saved_analysis,
                last_merged_key=merge_key,
                last_merged_line=merge_line,
            )
        )
        if is_new:
            report.added.append(repo.name)
        return IndexEntry(
            name=repo.name, summary=analysis["summary"], updated=page.updated, merged=merge_line,
            public=page.public, archived=repo.archived,
        )

    def _cached_entry(self, repo: RepoMeta) -> IndexEntry | None:
        prev = self.store.get(repo.name)
        if prev is None or prev.analysis is None:
            return None
        return IndexEntry(
            name=repo.name, summary=prev.analysis["summary"], updated=self._date(repo.pushed_at),
            merged=prev.last_merged_line or "なし", public=not repo.private, archived=repo.archived,
        )

    def _gitleaks_published(self) -> list[Finding]:
        """公開対象 (README.md と repos/) のコピーだけを gitleaks で検査する。"""
        self.s.tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.s.tmp_dir) as tmp:
            dest = Path(tmp)
            shutil.copy2(self.workspace.path / INDEX_FILE, dest / INDEX_FILE)
            if (self.workspace.path / "repos").exists():
                shutil.copytree(self.workspace.path / "repos", dest / "repos")
            return self.gitleaks.scan_dir(dest)

    # ---- 全体 ----
    def run(self) -> RunReport:
        budget = Budget(self.s.run_deadline_sec)
        report = RunReport()
        self.store.migrate()
        run_id = self.store.start_run()
        try:
            self._run(report, budget)
            status = "error" if report.errors else "ok"
        except Exception as exc:
            self.store.finish_run(run_id, "fatal", type(exc).__name__)
            raise
        self.store.finish_run(run_id, status, report.message(self.s.dry_run))
        if report.needs_notice():
            self.notifier.send(report.message(self.s.dry_run))
        return report

    def _run(self, report: RunReport, budget: Budget) -> None:
        levels = load_levels(self.s.repos_config_path, self.s.default_level)
        repos = self.github.list_repos(self.s.github_owner)
        self.workspace.sync()

        visible = sorted(
            (r for r in repos if levels.get(r.name, self.s.default_level) != "hidden"),
            key=lambda r: r.pushed_at,
            reverse=True,
        )
        visible_names = {r.name for r in visible}
        before = self.workspace.listed_names()

        # 解析に失敗し続けているリポジトリは後回しにして、他の処理を止めない
        attempts = self.store.attempts()
        order = sorted(visible, key=lambda r: attempts.get(r.name, (0, ""))[0])
        self._log.info("対象 %d 件 (非表示 %d 件)", len(visible), len(repos) - len(visible))

        entries = []
        for i, repo in enumerate(order, 1):
            level = levels.get(repo.name, self.s.default_level)
            self._log.info("[%d/%d] %s (%s)", i, len(order), repo.name, level)
            try:
                entries.append(self._process(repo, level, budget, report))
            except BlockedError as exc:
                self._log.warning("公開見送り: %s (%s)", repo.name, exc)
                report.blocked.append((repo.name, str(exc)))
                cached = self._cached_entry(repo)
                if cached and not self.sanitizer.scan(cached.summary + cached.merged, repo.name):
                    entries.append(cached)
            except Exception as exc:  # 1 件の失敗で全体を止めない
                self._log.exception("処理失敗: %s", repo.name)
                report.errors.append((repo.name, type(exc).__name__))
                cached = self._cached_entry(repo)
                if cached:
                    entries.append(cached)

        # 一覧から消えたリポジトリ (削除・改名・hidden 化) のページを削除する
        existing_names = {r.name for r in repos}
        known = self.store.names()
        listing_ok = len(repos) > 0 and len(repos) >= self.s.min_listing_ratio * len(known)
        for name in sorted(before - visible_names):
            if name not in existing_names and not listing_ok:
                report.notes.append(f"リポジトリ一覧の件数が少ないため {name} の削除を見送りました")
                continue
            self.workspace.remove_repo_dir(name)
            report.removed.append(name)
            if name not in existing_names:
                self.store.delete(name)

        rank = {r.name: i for i, r in enumerate(visible)}
        entries.sort(key=lambda e: rank[e.name])
        index = self.renderer.index(self.s.github_owner, entries, datetime.now(self._tz))
        self._scan(index, INDEX_FILE)
        self.workspace.write(INDEX_FILE, index)

        leaks = self._gitleaks_published()
        if leaks:
            report.blocked.append(("公開物全体", ", ".join(sorted({f.kind for f in leaks}))))
            report.notes.append("gitleaks が検出したため push を見送りました")
            return

        changed = self.workspace.changed_paths()
        changed_repos = {p.split("/")[1] for p in changed if p.startswith("repos/")}
        report.updated = sorted(changed_repos - set(report.added) - set(report.removed))
        today = datetime.now(self._tz).strftime("%Y-%m-%d")
        message = (
            f"docs(atlas): {today} 自動更新 "
            f"(追加 {len(report.added)} / 更新 {len(report.updated)} / 削除 {len(report.removed)})"
        )
        report.pushed = self.workspace.commit_and_push(message, self.s.dry_run)
        if not report.pushed:
            self._log.info("公開物の変更なし")
        elif self.s.dry_run:
            self._log.info("公開物の変更あり (DRY_RUN のため push せず)")
        else:
            self._log.info("main に push しました")
