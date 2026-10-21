#!/usr/bin/env bash
# repo-atlas のインストール / 更新 (rootless podman + systemd --user)
#
#   ./install.sh            インストールまたは更新 (イメージ再構築・マイグレーション・タイマー有効化)
#   ./install.sh --check    接続確認のみ (GitHub / Ollama / Deploy key)
#   ./install.sh --run-now  インストール後にすぐ 1 回実行する
#
# 既存の .env / repos.yaml / deploy_key は上書きしない。.env に不足キーがあれば末尾に追記する。
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${REPO_ATLAS_CONFIG_DIR:-$HOME/.config/repo-atlas}"
ENV_FILE="$CONFIG_DIR/.env"
QUADLET_DIR="$HOME/.config/containers/systemd"
UNIT_DIR="$HOME/.config/systemd/user"
HOOK_DIR="$HOME/.local/libexec/repo-atlas"

MODE="install"
case "${1:-}" in
  --check) MODE="check" ;;
  --run-now) MODE="run-now" ;;
  "") ;;
  *) echo "不明なオプション: $1" >&2; exit 2 ;;
esac

log() { printf '\033[1;34m[repo-atlas]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[repo-atlas]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[repo-atlas]\033[0m %s\n' "$*" >&2; exit 1; }

env_value() {
  # .env を source せずに値だけ取り出す
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

podman_run_args() {
  local data_dir="$1"
  printf '%s\n' --rm --env-file "$ENV_FILE" \
    -v "$data_dir:/data:Z" \
    -v "$CONFIG_DIR/repos.yaml:/config/repos.yaml:ro,Z" \
    -v "$CONFIG_DIR/deploy_key:/run/secrets/deploy_key:ro,Z" \
    -v "$CONFIG_DIR/github_known_hosts:/run/secrets/known_hosts:ro,Z"
}

# ---- 1. 前提 ----
for cmd in podman systemctl systemd-run ssh-keygen curl python3 grep sed; do
  command -v "$cmd" >/dev/null 2>&1 || die "$cmd が見つかりません"
done
[ "$(id -u)" -ne 0 ] || die "root ではなく実行ユーザーで実行してください (rootless podman)"

# ---- 2. 設定ディレクトリと .env ----
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
if [ ! -f "$ENV_FILE" ]; then
  install -m 600 "$SRC_DIR/.env.sample" "$ENV_FILE"
  warn ".env を作成しました。GITHUB_TOKEN などを設定してから再実行してください: $ENV_FILE"
  NEED_EDIT=1
else
  added=()
  while IFS= read -r line; do
    [[ "$line" =~ ^([A-Z0-9_]+)= ]] || continue
    key="${BASH_REMATCH[1]}"
    if ! grep -qE "^${key}=" "$ENV_FILE"; then
      echo "$line" >> "$ENV_FILE"
      added+=("$key")
    fi
  done < "$SRC_DIR/.env.sample"
  [ ${#added[@]} -eq 0 ] || warn ".env に不足キーを追記しました (値を確認してください): ${added[*]}"
fi
chmod 600 "$ENV_FILE"

for key in GITHUB_TOKEN OLLAMA_URL OLLAMA_MODEL; do
  [ -n "$(env_value "$key")" ] || { warn "$key が未設定です"; NEED_EDIT=1; }
done
[ -n "$(env_value SLACK_WEBHOOK_URL)" ] || warn "SLACK_WEBHOOK_URL が未設定です (通知されません)"

# ---- 3. repos.yaml / deploy key / known_hosts ----
if [ ! -f "$CONFIG_DIR/repos.yaml" ]; then
  install -m 600 "$SRC_DIR/config/repos.yaml.sample" "$CONFIG_DIR/repos.yaml"
  warn "repos.yaml を作成しました。公開レベルを確認してください: $CONFIG_DIR/repos.yaml"
fi
chmod 600 "$CONFIG_DIR/repos.yaml"

if [ ! -f "$CONFIG_DIR/deploy_key" ]; then
  ssh-keygen -q -t ed25519 -N "" -C "repo-atlas-deploy" -f "$CONFIG_DIR/deploy_key"
  warn "Deploy key を作成しました。公開鍵を repo-atlas リポジトリに書き込み権限付きで登録してください:"
  warn "  gh repo deploy-key add $CONFIG_DIR/deploy_key.pub --repo $(env_value ATLAS_REPO) --allow-write --title repo-atlas-bot"
  NEED_EDIT=1
fi
chmod 600 "$CONFIG_DIR/deploy_key"
install -m 644 "$SRC_DIR/deploy/github_known_hosts" "$CONFIG_DIR/github_known_hosts"

if [ "${NEED_EDIT:-0}" = "1" ]; then
  die "設定が揃っていません。上記を対応してから ./install.sh を再実行してください。"
fi

# ---- 4. 値の取得 ----
HOST_DATA_DIR="$(env_value HOST_DATA_DIR)"
HOST_DATA_DIR="${HOST_DATA_DIR:-$HOME/.local/share/repo-atlas}"
IMAGE_NAME="$(env_value IMAGE_NAME)"
SCHEDULE_ONCALENDAR="$(env_value SCHEDULE_ONCALENDAR)"
RUN_TIMEOUT_SEC="$(env_value RUN_TIMEOUT_SEC)"
GITLEAKS_VERSION="$(env_value GITLEAKS_VERSION)"
GITLEAKS_SHA256="$(env_value GITLEAKS_SHA256)"
for v in IMAGE_NAME SCHEDULE_ONCALENDAR RUN_TIMEOUT_SEC GITLEAKS_VERSION GITLEAKS_SHA256; do
  [ -n "${!v}" ] || die "$v が .env に設定されていません"
done
mkdir -p "$HOST_DATA_DIR"
chmod 700 "$HOST_DATA_DIR"

mapfile -t RUN_ARGS < <(podman_run_args "$HOST_DATA_DIR")

if [ "$MODE" = "check" ]; then
  podman run "${RUN_ARGS[@]}" "$IMAGE_NAME" check
  exit $?
fi

# ---- 5. イメージ構築 ----
log "コンテナイメージを構築します: $IMAGE_NAME"
podman build -q -t "$IMAGE_NAME" -f "$SRC_DIR/deploy/Containerfile" \
  --build-arg "GITLEAKS_VERSION=$GITLEAKS_VERSION" --build-arg "GITLEAKS_SHA256=$GITLEAKS_SHA256" \
  "$SRC_DIR" >/dev/null

log "テストを実行します"
podman run --rm --entrypoint sh "$IMAGE_NAME" -c \
  "pip install -q --no-cache-dir -r requirements-dev.txt >/dev/null && python -m pytest -q tests"

# ---- 6. マイグレーション ----
log "マイグレーションを適用します"
podman run "${RUN_ARGS[@]}" "$IMAGE_NAME" migrate

# ---- 7. systemd ユニット ----
mkdir -p "$QUADLET_DIR" "$UNIT_DIR" "$HOOK_DIR"
install -m 755 "$SRC_DIR/deploy/notify-failure.sh" "$HOOK_DIR/notify-failure.sh"

render() {
  sed -e "s|@IMAGE_NAME@|$IMAGE_NAME|g" \
      -e "s|@ENV_FILE@|$ENV_FILE|g" \
      -e "s|@HOST_DATA_DIR@|$HOST_DATA_DIR|g" \
      -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" \
      -e "s|@RUN_TIMEOUT_SEC@|$RUN_TIMEOUT_SEC|g" \
      -e "s|@SCHEDULE_ONCALENDAR@|$SCHEDULE_ONCALENDAR|g" \
      -e "s|@HOOK@|$HOOK_DIR/notify-failure.sh|g" \
      "$1"
}
render "$SRC_DIR/deploy/repo-atlas.container.in" > "$QUADLET_DIR/repo-atlas.container"
render "$SRC_DIR/deploy/repo-atlas.timer.in" > "$UNIT_DIR/repo-atlas.timer"

systemctl --user daemon-reload
systemctl --user enable --now repo-atlas.timer >/dev/null
systemctl --user reset-failed repo-atlas.service 2>/dev/null || true

if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  warn "linger が無効です。再起動後もタイマーを動かすには: sudo loginctl enable-linger $USER"
fi

log "接続を確認します"
podman run "${RUN_ARGS[@]}" "$IMAGE_NAME" check || warn "接続確認に失敗しました。上のログを確認してください"

log "完了しました。次回実行: $(systemctl --user list-timers repo-atlas.timer --no-legend | awk '{print $1, $2, $3}')"

if [ "$MODE" = "run-now" ]; then
  log "今すぐ 1 回実行します (journalctl --user -u repo-atlas -f で確認)"
  systemctl --user start --no-block repo-atlas.service
fi
