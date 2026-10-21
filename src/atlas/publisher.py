"""公開リポジトリの作業コピーを管理し、生成物だけを main に push する。

bot が変更してよいのは README.md と repos/ 以下のみ。それ以外の変更が混じっていたら中止する。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath

INDEX_FILE = "README.md"
REPOS_DIR = "repos"


class PublishError(Exception):
    pass


def is_allowed_path(rel: str) -> bool:
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts:
        return False
    return rel == INDEX_FILE or (len(path.parts) >= 3 and path.parts[0] == REPOS_DIR)


class AtlasWorkspace:
    def __init__(
        self,
        path: Path,
        ssh_url: str,
        branch: str,
        deploy_key: Path,
        known_hosts: Path,
        author_name: str,
        author_email: str,
    ):
        self.path = path
        self._ssh_url = ssh_url
        self._branch = branch
        self._env = {
            **os.environ,
            "GIT_SSH_COMMAND": (
                f"ssh -i {deploy_key} -o IdentitiesOnly=yes -o UserKnownHostsFile={known_hosts}"
                " -o StrictHostKeyChecking=yes -o BatchMode=yes"
            ),
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
            "GIT_TERMINAL_PROMPT": "0",
        }

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=cwd or self.path, env=self._env, capture_output=True, text=True, timeout=300
        )
        if proc.returncode != 0:
            raise PublishError(f"git {args[0]} に失敗しました: {proc.stderr.strip()[-500:]}")
        return proc.stdout

    def sync(self) -> None:
        """リモートの main と完全に一致させる (前回の未 push 分は捨てる)。"""
        if not (self.path / ".git").exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--branch", self._branch, self._ssh_url, str(self.path), cwd=self.path.parent)
        self._git("fetch", "origin", self._branch)
        self._git("checkout", "-B", self._branch, f"origin/{self._branch}")
        self._git("reset", "--hard", f"origin/{self._branch}")
        self._git("clean", "-fdx", "--", INDEX_FILE, REPOS_DIR)

    def last_code_commit(self) -> str | None:
        """生成物 (README.md と repos/) 以外が最後に変わったコミット。"""
        out = self._git(
            "log", "-1", "--format=%H", "--", ".", f":(exclude){INDEX_FILE}", f":(exclude){REPOS_DIR}"
        ).strip()
        return out or None

    def check_remote(self) -> None:
        self._git("ls-remote", "--heads", self._ssh_url, self._branch, cwd=Path("/"))

    def repo_dir(self, name: str) -> Path:
        if not name or "/" in name or name in (".", ".."):
            raise PublishError(f"不正なリポジトリ名です: {name}")
        return self.path / REPOS_DIR / name

    def listed_names(self) -> set[str]:
        root = self.path / REPOS_DIR
        return {p.name for p in root.iterdir() if p.is_dir()} if root.exists() else set()

    def write(self, rel: str, content: str) -> None:
        if not is_allowed_path(rel):
            raise PublishError(f"書き込みが許可されていないパスです: {rel}")
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def remove_file(self, rel: str) -> None:
        if not is_allowed_path(rel):
            raise PublishError(f"削除が許可されていないパスです: {rel}")
        (self.path / rel).unlink(missing_ok=True)

    def remove_repo_dir(self, name: str) -> None:
        target = self.repo_dir(name).resolve()
        if target.parent != (self.path / REPOS_DIR).resolve():
            raise PublishError(f"削除対象が repos/ の外です: {name}")
        shutil.rmtree(target)

    def changed_paths(self) -> list[str]:
        out = self._git("status", "--porcelain", "-z", "--untracked-files=all")
        items = out.split("\0")
        paths = []
        i = 0
        while i < len(items):
            item = items[i]
            i += 1
            if not item:
                continue
            paths.append(item[3:])
            if item[0] in "RC":
                # リネーム・コピーは直後に元のパスが続く
                paths.append(items[i])
                i += 1
        return paths

    def commit_and_push(self, message: str, dry_run: bool) -> bool:
        changed = self.changed_paths()
        if not changed:
            return False
        bad = [p for p in changed if not is_allowed_path(p)]
        if bad:
            raise PublishError(f"許可外のパスに変更があります: {', '.join(bad[:5])}")
        self._git("add", "-A", "--", INDEX_FILE, REPOS_DIR)
        staged = [p for p in self._git("diff", "--cached", "--name-only", "-z").split("\0") if p]
        if any(not is_allowed_path(p) for p in staged):
            raise PublishError("許可外のパスがステージされています")
        if dry_run:
            self._git("reset", "-q")
            return True
        self._git("commit", "-q", "-m", message)
        try:
            self._git("push", "-q", "origin", f"HEAD:{self._branch}")
        except PublishError:
            # 処理中に PR がマージされた等で main が進んだ場合は、一度だけ載せ直して再送する
            self._git("fetch", "origin", self._branch)
            self._git("rebase", f"origin/{self._branch}")
            self._git("push", "-q", "origin", f"HEAD:{self._branch}")
        return True
