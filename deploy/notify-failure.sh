#!/usr/bin/env bash
# repo-atlas.service の ExecStopPost から呼ばれ、失敗・タイムアウトを Slack に通知する。
# アプリが自分で通知済みの失敗 (終了コード 3) は通知しない。
set -u

ENV_FILE="${1:?usage: notify-failure.sh <env-file>}"
result="${SERVICE_RESULT:-success}"
status="${EXIT_STATUS:-}"

[ "$result" = "success" ] && exit 0
[ "$result" = "exit-code" ] && [ "$status" = "3" ] && exit 0

env_value() {
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-
}

url="$(env_value SLACK_WEBHOOK_URL)"
[ -z "$url" ] && exit 0

timeout_sec="$(env_value RUN_TIMEOUT_SEC)"
retry_sec="$(env_value RETRY_DELAY_SEC)"
restarts="$(systemctl --user show -p NRestarts --value repo-atlas.service 2>/dev/null || echo 0)"

case "$result" in
  timeout) reason="$(( ${timeout_sec:-1200} / 60 )) 分のタイムアウトで停止しました" ;;
  exit-code) reason="異常終了しました (終了コード ${status})" ;;
  signal|core-dump) reason="シグナルで停止しました (${status})" ;;
  oom-kill) reason="メモリ不足で停止しました" ;;
  *) reason="失敗しました (${result})" ;;
esac

if [ "${restarts:-0}" = "0" ]; then
  next="$(( ${retry_sec:-1800} / 60 )) 分後に 1 回だけ再実行します。"
else
  next="再実行も失敗しました。次回の定期実行まで待ちます。journalctl --user -u repo-atlas を確認してください。"
fi

text=":rotating_light: repo-atlas が${reason}。${next}"
payload="$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$text")"
curl -fsS -m 10 -H 'Content-Type: application/json' -d "$payload" "$url" >/dev/null || true
