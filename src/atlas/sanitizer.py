"""機密情報の除外・マスク・検出。

公開物に IP アドレス・MAC アドレス・内部ホスト名・認証情報などが混入しないよう、
1. LLM に渡す前の入力をマスクし (mask)
2. 生成物を検査して、1 件でも見つかれば公開を止める (scan)
の二段で防ぐ。
"""

from __future__ import annotations

import fnmatch
import ipaddress
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

# 設定で無効化できない除外対象 (秘密情報が入りうるファイル)
MANDATORY_EXCLUDE_GLOBS = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.kdbx",
    "*_rsa",
    "*_rsa.pub",
    "*_dsa",
    "*_ecdsa",
    "*_ed25519",
    "id_*",
    "*.tfstate",
    "*.tfstate.*",
    "*.tfvars",
    "credentials*",
    "secrets/*",
    "secret/*",
    ".git/*",
    "known_hosts",
    "authorized_keys",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
)


@dataclass(frozen=True)
class Finding:
    kind: str
    location: str


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern
    replace: Callable[[re.Match], str]


def _const(token: str) -> Callable[[re.Match], str]:
    return lambda _m: token


def _ipv6_or_keep(m: re.Match) -> str:
    try:
        ipaddress.IPv6Address(m.group(0))
    except ValueError:
        return m.group(0)
    return "[IP]"


_PLAIN_PATH_SEGMENT = re.compile(r"[a-z0-9_.-]{1,40}")


def _entropy_or_keep(m: re.Match) -> str:
    token = m.group(0)
    # 小文字のファイルパスは秘密ではない
    if "/" in token and all(_PLAIN_PATH_SEGMENT.fullmatch(s) for s in token.strip("/").split("/")):
        return token
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    if not (has_digit and has_alpha) or len(set(token)) < 12:
        return token
    return "[SECRET]"


def _secret_value(m: re.Match) -> str:
    return f"{m.group(1)}{m.group(2)}[SECRET]"


class Sanitizer:
    def __init__(self, internal_domains: tuple[str, ...] = (), deny_terms: tuple[str, ...] = ()):
        rules = [
            _Rule(
                "private_key",
                re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
                _const("[PRIVATE_KEY]"),
            ),
            _Rule("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), _const("[SECRET]")),
            _Rule("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), _const("[SECRET]")),
            _Rule("webhook_url", re.compile(r"https://hooks\.slack\.com/[^\s\"'<>)]+"), _const("[SECRET]")),
            _Rule("aws_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), _const("[SECRET]")),
            _Rule("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), _const("[SECRET]")),
            _Rule(
                "secret_assignment",
                re.compile(
                    r"(?i)\b((?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)\w*)"
                    r"(\s*[:=]\s*[\"']?)(?!\[|\$\{|\$\(|<|%|\{\{)([^\s\"'<>]{6,})"
                ),
                _secret_value,
            ),
            _Rule("url_credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"), _const("[URL_WITH_CREDENTIALS]")),
            _Rule("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), _const("[EMAIL]")),
            _Rule("mac_address", re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), _const("[MAC]")),
            _Rule(
                "ipv4",
                re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:/\d{1,2})?(?![\d.]*\d)"),
                _const("[IP]"),
            ),
            _Rule("ipv6", re.compile(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])"), _ipv6_or_keep),
            _Rule(
                "local_hostname",
                re.compile(r"(?i)\b(?:[a-z0-9-]+\.)+(?:local|lan|internal|intranet|home\.arpa|localdomain|corp)\b"),
                _const("[HOST]"),
            ),
            _Rule("high_entropy", re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/=_-])"), _entropy_or_keep),
        ]
        for domain in internal_domains:
            rules.append(
                _Rule(
                    "internal_domain",
                    re.compile(r"(?i)\b(?:[a-z0-9-]+\.)*" + re.escape(domain) + r"\b"),
                    _const("[HOST]"),
                )
            )
        for term in deny_terms:
            rules.append(
                _Rule("deny_term", re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"), _const("[REDACTED]"))
            )
        self._rules = tuple(rules)

    def mask(self, text: str) -> str:
        for rule in self._rules:
            text = rule.pattern.sub(rule.replace, text)
        return text

    def scan(self, text: str, location: str) -> list[Finding]:
        findings = []
        for rule in self._rules:
            for m in rule.pattern.finditer(text):
                if rule.replace(m) != m.group(0):
                    findings.append(Finding(rule.kind, location))
                    break
        return findings


class PathFilter:
    """LLM に渡すファイルを絞り込む。"""

    def __init__(self, extra_globs: tuple[str, ...] = ()):
        self._globs = MANDATORY_EXCLUDE_GLOBS + tuple(extra_globs)

    def is_excluded(self, rel_path: str) -> bool:
        path = PurePosixPath(rel_path)
        candidates = [path.name, str(path)]
        # 途中のディレクトリ名でも判定する (例: secrets/x/y.txt)
        parts = path.parts
        for i in range(len(parts) - 1):
            candidates.append("/".join(parts[i:]))
        lowered = [c.lower() for c in candidates]
        return any(fnmatch.fnmatchcase(c, g.lower()) for c in lowered for g in self._globs)


class GitleaksScanner:
    """gitleaks による追加検査。バイナリが無い環境では検査を省略せず失敗させる。"""

    def __init__(self, binary: str = "gitleaks", required: bool = True):
        self._binary = shutil.which(binary)
        self._required = required

    def scan_dir(self, path: Path) -> list[Finding]:
        if self._binary is None:
            if self._required:
                raise RuntimeError("gitleaks が見つかりません")
            return []
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            proc = subprocess.run(
                [
                    self._binary, "dir", str(path), "--no-banner", "--redact",
                    "--report-format", "json", "--report-path", str(report), "--exit-code", "2",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode not in (0, 2):
                raise RuntimeError(f"gitleaks の実行に失敗しました (exit {proc.returncode})")
            if proc.returncode == 0:
                return []
            data = json.loads(report.read_text(encoding="utf-8") or "[]")
        return [Finding(f"gitleaks:{d.get('RuleID', '?')}", str(d.get("File", "?"))) for d in data]
