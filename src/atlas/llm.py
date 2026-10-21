"""Ollama による要約。出力は JSON schema で構造を固定する。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests

_KINDS = ["user", "service", "container", "job", "storage", "external", "device", "library"]

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "features": {"type": "array", "items": {"type": "string"}},
        "tech_stack": {"type": "array", "items": {"type": "string"}},
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "kind": {"type": "string", "enum": _KINDS},
                },
                "required": ["id", "label", "kind"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["source", "target", "label"],
            },
        },
    },
    "required": ["summary", "features", "tech_stack", "components", "relations"],
}

MERGE_SCHEMA = {
    "type": "object",
    "properties": {"line": {"type": "string"}},
    "required": ["line"],
}

_ID_RE = re.compile(r"[^a-z0-9_]")


class LLMError(Exception):
    pass


def _clip(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def normalize_analysis(raw: dict) -> dict:
    """LLM 出力の型・件数・長さを整える。図に使う ID は英小文字・数字・_ のみにする。"""
    components = []
    seen = set()
    for c in raw.get("components") or []:
        if not isinstance(c, dict):
            continue
        cid = _ID_RE.sub("_", str(c.get("id", "")).lower())[:32].strip("_")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        kind = c.get("kind") if c.get("kind") in _KINDS else "service"
        components.append({"id": cid, "label": _clip(c.get("label") or cid, 40), "kind": kind})
        if len(components) >= 16:
            break
    relations = []
    for r in raw.get("relations") or []:
        if not isinstance(r, dict):
            continue
        src = _ID_RE.sub("_", str(r.get("source", "")).lower())[:32].strip("_")
        dst = _ID_RE.sub("_", str(r.get("target", "")).lower())[:32].strip("_")
        if src in seen and dst in seen and src != dst:
            relations.append({"source": src, "target": dst, "label": _clip(r.get("label"), 30)})
        if len(relations) >= 24:
            break
    return {
        "summary": _clip(raw.get("summary"), 200),
        "features": [_clip(f, 100) for f in (raw.get("features") or []) if str(f).strip()][:8],
        "tech_stack": [_clip(t, 40) for t in (raw.get("tech_stack") or []) if str(t).strip()][:12],
        "components": components,
        "relations": relations,
    }


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int, num_ctx: int, disable_think: bool, prompts_dir: Path):
        self._url = f"{base_url}/api/chat"
        self._model = model
        self._timeout = timeout
        self._num_ctx = num_ctx
        self._disable_think = disable_think
        self._prompts_dir = prompts_dir

    def _prompt(self, name: str) -> str:
        return (self._prompts_dir / name).read_text(encoding="utf-8")

    def _chat(self, system: str, user: str, schema: dict, timeout: float | None) -> dict:
        payload = {
            "model": self._model,
            "stream": False,
            "format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.2, "num_ctx": self._num_ctx},
        }
        if self._disable_think:
            payload["think"] = False
        # stream=False の応答は完了まで 1 バイトも返らないため、読み取りタイムアウト = 処理全体の上限になる
        read_timeout = min(timeout or self._timeout, self._timeout)
        try:
            resp = requests.post(self._url, json=payload, timeout=(10, read_timeout))
        except requests.Timeout as exc:
            raise LLMError(f"Ollama の応答が {int(read_timeout)} 秒以内に返りませんでした") from exc
        except requests.RequestException as exc:
            raise LLMError(f"Ollama に接続できません: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise LLMError(f"Ollama がエラーを返しました ({resp.status_code})")
        try:
            return json.loads(resp.json()["message"]["content"])
        except (KeyError, ValueError) as exc:
            raise LLMError(f"Ollama の出力を JSON として解釈できません: {type(exc).__name__}") from exc

    def analyze(self, repo_name: str, description: str, source_text: str, timeout: float | None = None) -> dict:
        user = (
            f"# リポジトリ名\n{repo_name}\n\n# GitHub 上の説明\n{description or '(なし)'}\n\n"
            f"# ソース (機密情報はマスク済み)\n{source_text}"
        )
        return normalize_analysis(self._chat(self._prompt("analyze.txt"), user, ANALYSIS_SCHEMA, timeout))

    def summarize_merge(self, repo_name: str, title: str, body: str, timeout: float | None = None) -> str:
        user = f"# リポジトリ名\n{repo_name}\n\n# タイトル\n{title}\n\n# 本文\n{body or '(なし)'}"
        return _clip(self._chat(self._prompt("merge_line.txt"), user, MERGE_SCHEMA, timeout).get("line"), 80)

    def ping(self) -> list[str]:
        resp = requests.get(self._url.replace("/api/chat", "/api/tags"), timeout=10)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
