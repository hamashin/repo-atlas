"""Slack Incoming Webhook への通知。"""

from __future__ import annotations

import logging

import requests


class SlackNotifier:
    def __init__(self, webhook_url: str):
        self._url = webhook_url
        self._log = logging.getLogger("atlas.notify")

    def send(self, text: str) -> None:
        if not self._url:
            self._log.info("SLACK_WEBHOOK_URL 未設定のため通知を省略: %s", text)
            return
        try:
            resp = requests.post(self._url, json={"text": text}, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as exc:
            self._log.error("Slack 通知に失敗しました: %s", type(exc).__name__)
