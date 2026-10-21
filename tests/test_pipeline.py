import io
import subprocess
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from atlas.github import MergeInfo, RepoMeta
from atlas.llm import LLMError
from atlas.pipeline import Pipeline
from atlas.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


def _meta(name, days_ago, private=True):
    return RepoMeta(
        name=name, full_name=f"owner/{name}", description=f"{name} の説明 (192.0.2.1)", private=private,
        archived=False, html_url=f"https://github.com/owner/{name}", default_branch="main",
        pushed_at=NOW - timedelta(days=days_ago),
    )


class FakeGitHub:
    def __init__(self, repos):
        self.repos = repos
        self.heads = {r.name: f"sha-{r.name}-1" for r in repos}

    def list_repos(self, owner):
        return list(self.repos)

    def head_sha(self, repo):
        return self.heads[repo.name]

    def last_merged(self, repo, head):
        return MergeInfo(key=f"pr:{repo.name}", title="機能を追加", body="", merged_at=NOW, number=1)

    def download_tarball(self, repo, sha, dest, max_bytes):
        with tarfile.open(dest, "w:gz") as tf:
            data = f"# {repo.name}\n".encode()
            info = tarfile.TarInfo(f"x-{repo.name}/README.md")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


class FakeLLM:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.analyzed = []

    def analyze(self, name, description, source, timeout=None):
        self.analyzed.append(name)
        if name in self.fail:
            raise LLMError("応答なし")
        return {
            "summary": f"{name} は便利な道具です",
            "features": ["機能 A"],
            "tech_stack": ["Python"],
            "components": [{"id": "app", "label": "アプリ", "kind": "service"},
                           {"id": "db", "label": "DB", "kind": "storage"}],
            "relations": [{"source": "app", "target": "db", "label": "保存"}],
        }

    def summarize_merge(self, name, title, body, timeout=None):
        return "機能を追加"


class NoLeaks:
    def scan_dir(self, path):
        return []


class SilentNotifier:
    def __init__(self):
        self.messages = []

    def send(self, text):
        self.messages.append(text)


@pytest.fixture
def remote(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True)
    (seed / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(seed), "add", "."], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(seed),
                    "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "HEAD:main"], check=True)
    return remote


def _settings(tmp_path, remote, **over):
    (tmp_path / "repos.yaml").write_text("repos:\n  secret-repo: hidden\n  tool-a: full\n")
    env = {
        "GITHUB_OWNER": "owner", "GITHUB_TOKEN": "x", "ATLAS_REPO": "owner/repo-atlas",
        "ATLAS_SSH_URL": str(remote), "GIT_AUTHOR_NAME": "bot", "GIT_AUTHOR_EMAIL": "bot@example.com",
        "OLLAMA_URL": "http://ollama.invalid", "OLLAMA_MODEL": "m", "DATA_DIR": str(tmp_path / "data"),
        "APP_DIR": str(ROOT), "REPOS_CONFIG_PATH": str(tmp_path / "repos.yaml"),
        "DEPLOY_KEY_PATH": str(tmp_path / "none"), "KNOWN_HOSTS_PATH": str(tmp_path / "none"),
        "RUN_DEADLINE_SEC": "1000", "MIN_LLM_SEC": "10",
    }
    env.update(over)
    return Settings.from_env(env)


def _pipeline(settings, github, llm):
    p = Pipeline(settings)
    p.github, p.llm, p.gitleaks, p.notifier = github, llm, NoLeaks(), SilentNotifier()
    return p


def _remote_file(remote, path):
    return subprocess.run(["git", "--git-dir", str(remote), "show", f"main:{path}"],
                          capture_output=True, text=True).stdout


def test_full_run_publishes_and_hides(tmp_path, remote):
    repos = [_meta("tool-a", 1), _meta("tool-b", 2, private=False), _meta("secret-repo", 0)]
    gh, llm = FakeGitHub(repos), FakeLLM()
    report = _pipeline(_settings(tmp_path, remote), gh, llm).run()

    assert report.pushed and not report.has_backlog and not report.errors
    assert sorted(report.added) == ["tool-a", "tool-b"]
    assert "secret-repo" not in llm.analyzed
    index = _remote_file(remote, "README.md")
    assert "secret-repo" not in index
    assert index.index("tool-a") < index.index("tool-b")  # 最終更新日の新しい順
    assert "192.0.2.1" not in index
    assert "architecture.svg" in _remote_file(remote, "repos/tool-a/README.md")
    assert _remote_file(remote, "repos/tool-a/architecture.svg").lstrip().startswith("<?xml")
    page_b = _remote_file(remote, "repos/tool-b/README.md")
    assert "主な機能" not in page_b and "https://github.com/owner/tool-b" in page_b

    # 2 回目: 変化が無ければ LLM を呼ばず push もしない
    llm2 = FakeLLM()
    report2 = _pipeline(_settings(tmp_path, remote), gh, llm2).run()
    assert llm2.analyzed == [] and report2.pushed is False


def test_backlog_is_carried_over_with_minimum_progress(tmp_path, remote):
    repos = [_meta("r1", 1), _meta("r2", 2), _meta("r3", 3)]
    gh = FakeGitHub(repos)
    # 持ち時間ゼロでも 1 件は必ず解析する
    settings = _settings(tmp_path, remote, RUN_DEADLINE_SEC="0", MIN_LLM_SEC="300")
    llm = FakeLLM()
    report = _pipeline(settings, gh, llm).run()
    assert len(llm.analyzed) == 1 and report.has_backlog and len(report.deferred) == 2

    for _ in range(2):
        _pipeline(settings, gh, FakeLLM()).run()
    llm_last = FakeLLM()
    final = _pipeline(settings, gh, llm_last).run()
    assert llm_last.analyzed == [] and not final.has_backlog
    assert "(解析待ち)" not in _remote_file(remote, "README.md")


def test_failing_repo_is_moved_to_the_end(tmp_path, remote):
    repos = [_meta("bad", 1), _meta("good", 2)]
    gh = FakeGitHub(repos)
    settings = _settings(tmp_path, remote, RUN_DEADLINE_SEC="0", MIN_LLM_SEC="300")
    first = FakeLLM(fail={"bad"})
    report = _pipeline(settings, gh, first).run()
    assert first.analyzed == ["bad"] and report.errors
    second = FakeLLM(fail={"bad"})
    _pipeline(settings, gh, second).run()
    assert second.analyzed == ["good"]


def test_deleted_repo_page_is_removed(tmp_path, remote):
    gh = FakeGitHub([_meta("keep", 1), _meta("gone", 2)])
    _pipeline(_settings(tmp_path, remote), gh, FakeLLM()).run()
    assert _remote_file(remote, "repos/gone/README.md")
    gh.repos = [_meta("keep", 1)]
    report = _pipeline(_settings(tmp_path, remote), gh, FakeLLM()).run()
    assert report.removed == ["gone"]
    assert _remote_file(remote, "repos/gone/README.md") == ""


def test_dry_run_does_not_push(tmp_path, remote):
    gh = FakeGitHub([_meta("tool-a", 1)])
    report = _pipeline(_settings(tmp_path, remote, DRY_RUN="true"), gh, FakeLLM()).run()
    assert report.pushed
    assert _remote_file(remote, "README.md") == "init\n"
