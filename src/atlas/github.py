"""GitHub REST API クライアント (読み取り専用トークンで使う)。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests


@dataclass(frozen=True)
class RepoMeta:
    name: str
    full_name: str
    description: str
    private: bool
    archived: bool
    html_url: str
    default_branch: str
    pushed_at: datetime


@dataclass(frozen=True)
class MergeInfo:
    key: str
    title: str
    body: str
    merged_at: datetime
    number: int | None


class GitHubError(Exception):
    pass


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHubClient:
    def __init__(self, api_url: str, token: str, timeout: int = 30):
        self._api = api_url
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "repo-atlas",
            }
        )

    def _get(self, path: str, **params) -> requests.Response:
        resp = self._session.get(f"{self._api}{path}", params=params, timeout=self._timeout)
        if resp.status_code >= 400 and resp.status_code not in (404, 409):
            raise GitHubError(f"GET {path} が {resp.status_code} で失敗しました")
        return resp

    def list_repos(self, owner: str) -> list[RepoMeta]:
        """オーナーが所有するリポジトリ (fork を除く) をすべて返す。"""
        repos = []
        page = 1
        while True:
            resp = self._get("/user/repos", affiliation="owner", per_page=100, page=page, sort="pushed")
            if resp.status_code != 200:
                raise GitHubError(f"リポジトリ一覧の取得に失敗しました ({resp.status_code})")
            items = resp.json()
            for r in items:
                if r.get("fork") or r["owner"]["login"].lower() != owner.lower():
                    continue
                repos.append(
                    RepoMeta(
                        name=r["name"],
                        full_name=r["full_name"],
                        description=r.get("description") or "",
                        private=bool(r["private"]),
                        archived=bool(r.get("archived")),
                        html_url=r["html_url"],
                        default_branch=r.get("default_branch") or "main",
                        pushed_at=_parse_time(r.get("pushed_at") or r["updated_at"]),
                    )
                )
            if len(items) < 100:
                return repos
            page += 1

    def head_sha(self, repo: RepoMeta) -> str | None:
        """デフォルトブランチの HEAD。空リポジトリなら None。"""
        resp = self._get(f"/repos/{repo.full_name}/commits/{repo.default_branch}")
        if resp.status_code in (404, 409):
            return None
        return resp.json()["sha"]

    def last_merged(self, repo: RepoMeta, head_sha: str | None) -> MergeInfo | None:
        """最後にマージされた PR。PR が無ければ HEAD のコミットで代用する。"""
        resp = self._get(
            f"/repos/{repo.full_name}/pulls",
            state="closed", base=repo.default_branch, sort="updated", direction="desc", per_page=50,
        )
        merged = [p for p in (resp.json() if resp.status_code == 200 else []) if p.get("merged_at")]
        if merged:
            pr = max(merged, key=lambda p: p["merged_at"])
            return MergeInfo(
                key=f"pr:{pr['number']}",
                title=pr.get("title") or "",
                body=(pr.get("body") or "")[:4000],
                merged_at=_parse_time(pr["merged_at"]),
                number=int(pr["number"]),
            )
        if head_sha is None:
            return None
        resp = self._get(f"/repos/{repo.full_name}/commits/{head_sha}")
        if resp.status_code != 200:
            return None
        commit = resp.json()["commit"]
        message = commit.get("message") or ""
        title, _, body = message.partition("\n")
        return MergeInfo(
            key=f"commit:{head_sha}",
            title=title,
            body=body[:4000],
            merged_at=_parse_time(commit["committer"]["date"]),
            number=None,
        )

    def download_tarball(self, repo: RepoMeta, sha: str, dest: Path, max_bytes: int) -> None:
        resp = self._session.get(
            f"{self._api}/repos/{repo.full_name}/tarball/{sha}", stream=True, timeout=self._timeout
        )
        if resp.status_code != 200:
            raise GitHubError(f"tarball の取得に失敗しました ({resp.status_code})")
        size = 0
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                size += len(chunk)
                if size > max_bytes:
                    raise GitHubError("tarball が MAX_TARBALL_MB を超えました")
                fh.write(chunk)
