#!/usr/bin/env bash
# repo-atlas.service の ExecStopPost から呼ばれる実行後フック。
#   - 未解析分が残った (終了コード 75)      → CATCHUP_DELAY_SEC 後に続きを実行
#   - 一部失敗でアプリが通知済み (終了コード 3) → RETRY_DELAY_SEC 後に 1 回だけ再実行
#   - それ以外の失敗・タイムアウト            → Slack に通知し、RETRY_DELAY_SEC 後に 1 回だけ再実行
#   - 正常終了                              → 再実行フラグを消す
set -u

ENV_FILE="${1:?usage: notify-failure.sh <env-file>}"
UNIT="repo-atlas.service"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/repo-atlas"
RETRY_FLAG="$STATE_DIR/retry-scheduled"
result="${SERVICE_RESULT:-success}"
status="${EXIT_STATUS:-}"

env_value() {
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-
}

schedule() {
  systemd-run --user --quiet --collect --on-active="$1" --timer-property=AccuracySec=1s \
    /usr/bin/systemctl --user start --no-block "$UNIT"
}

notify() {
  local url payload
  url="$(env_value SLACK_WEBHOOK_URL)"
  [ -z "$url" ] && return 0
  payload="$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$1")"
  curl -fsS -m 10 -H 'Content-Type: application/json' -d "$payload" "$url" >/dev/null || true
}

mkdir -p "$STATE_DIR"
timeout_sec="$(env_value RUN_TIMEOUT_SEC)"
retry_sec="$(env_value RETRY_DELAY_SEC)"
catchup_sec="$(env_value CATCHUP_DELAY_SEC)"

if [ "$result" = "success" ]; then
  if [ "$status" = "75" ]; then
    schedule "${catchup_sec:-60}"
  else
    rm -f "$RETRY_FLAG"
  fi
  exit 0
fi

if [ ! -e "$RETRY_FLAG" ]; then
  touch "$RETRY_FLAG"
  schedule "${retry_sec:-1800}"
  next="$(( ${retry_sec:-1800} / 60 )) 分後に 1 回だけ再実行します。"
else
  rm -f "$RETRY_FLAG"
  next="再実行も失敗しました。翌日の定期実行まで待ちます。journalctl --user -u repo-atlas を確認してください。"
fi

# アプリが通知済みの一部失敗は、再実行の予約だけ行う
[ "$result" = "exit-code" ] && [ "$status" = "3" ] && exit 0

case "$result" in
  timeout) reason="$(( ${timeout_sec:-1200} / 60 )) 分のタイムアウトで停止しました" ;;
  exit-code) reason="異常終了しました (終了コード ${status})" ;;
  signal|core-dump) reason="シグナルで停止しました (${status})" ;;
  oom-kill) reason="メモリ不足で停止しました" ;;
  *) reason="失敗しました (${result})" ;;
esac
notify ":rotating_light: repo-atlas が${reason}。${next}"
