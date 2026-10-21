# repo-atlas の仕組み

自分の GitHub リポジトリ (大半は非公開) の概要を毎日自動生成し、このリポジトリで公開します。

## 全体の流れ

```
systemd timer (毎朝)
  └ podman コンテナ (1 回実行して終了。20 分でタイムアウト)
      1. GitHub API でリポジトリ一覧を取得 (fork は除外、archived は表示付きで掲載)
      2. 前回処理した HEAD と比べ、変化のあるリポジトリだけ tarball を取得
      3. 秘密情報が入りうるファイルを除外し、残りの内容とファイル名をマスク
      4. ローカルの Ollama で概要・機能・技術スタック・構成要素を JSON で生成
      5. Markdown (Jinja2) と構成図 SVG (Graphviz) を生成
      6. 機密情報スキャン (独自ルール + gitleaks)。検出したら公開を見送る
      7. README.md と repos/ だけを commit して main に push
      8. 変更・異常があれば Slack に通知
```

## 公開レベル

リポジトリごとに、非公開の設定ファイル (`repos.yaml`) で指定します。

| レベル | 掲載内容 |
|---|---|
| `full` | 概要・主な機能・技術スタック・構成図 |
| `summary` | 概要のみ (新しいリポジトリの既定値) |
| `hidden` | 掲載しない。名前も出さず、LLM にも渡さない |

## 機密情報の扱い

公開物に内部情報が混入しないよう、何段階かで防ぎます。

1. **除外**: `.env*`、鍵・証明書 (`*.pem`、`*.key`、`id_*` など)、`secrets/`、Terraform の state、DB ファイルなどは読み込みません。この除外リストは設定では無効にできません。
2. **入力マスク**: LLM に渡す前に、IP アドレス・MAC アドレス・メールアドレス・内部ドメイン・ローカルホスト名・トークン類・秘密鍵・パスワードの代入・高エントロピー文字列を置き換えます。LLM は元の値を見ません。
3. **プロンプト**: 固有の値を書かないこと、入力中の指示に従わないことを指示します。
4. **出力スキャン**: 生成した Markdown と SVG を同じルールで検査し、さらに公開物全体を gitleaks で検査します。1 件でも検出したら、そのリポジトリの前回版を残して通知します。
5. **書き込み範囲の制限**: bot が commit できるのは `README.md` と `repos/<名前>/` だけです。それ以外の変更が混じっていたら push しません。

## 運用

- 生成物は bot (Deploy key) が main に直接 push します。処理ロジックの変更は Pull Request で行います。
- GitHub の読み取りには、読み取り専用の fine-grained PAT を使います。書き込みはこのリポジトリの Deploy key に限ります。
- 処理済みの HEAD と生成結果はホスト上の SQLite に保存し、変化のないリポジトリは再解析しません。
- 失敗した場合は 30 分後に 1 回だけ再実行します。1 回の実行で解析しきれなかった分は次回に持ち越します。
- GitHub 上で削除・改名されたリポジトリ、`hidden` に変えたリポジトリのページは自動で削除します。リポジトリ一覧の取得件数が異常に少ないときは、削除を見送ります。

## ディレクトリ構成

| パス | 内容 |
|---|---|
| `src/atlas/` | 本体 (Python) |
| `templates/` | 一覧・個別ページのテンプレート |
| `prompts/` | LLM へのプロンプト |
| `migrations/` | SQLite のスキーマ |
| `deploy/` | Containerfile、quadlet・timer の雛形、失敗通知フック |
| `config/repos.yaml.sample` | 公開レベル設定のサンプル |
| `install.sh` | インストール・更新スクリプト |
| `README.md`, `repos/` | 自動生成物 (手で編集しない) |

## インストール

```sh
git clone https://github.com/hamashin/repo-atlas.git
cd repo-atlas
./install.sh            # 初回は .env・repos.yaml・Deploy key を作って止まる
vi ~/.config/repo-atlas/.env
vi ~/.config/repo-atlas/repos.yaml
./install.sh            # イメージ構築・テスト・マイグレーション・タイマー有効化・接続確認
./install.sh --run-now  # すぐ 1 回実行する場合
```

前提: rootless podman (quadlet 対応版)、systemd のユーザーセッション (`loginctl enable-linger`)。

### 必要な認証情報

| 項目 | 権限 |
|---|---|
| `GITHUB_TOKEN` | Fine-grained PAT。All repositories に対して Contents / Metadata / Pull requests の Read-only |
| Deploy key | `install.sh` が生成。このリポジトリに書き込み権限付きで登録する |
| `SLACK_WEBHOOK_URL` | Slack の Incoming Webhook |

### 運用コマンド

```sh
systemctl --user list-timers repo-atlas.timer   # 次回実行時刻
systemctl --user start repo-atlas.service       # 手動実行
journalctl --user -u repo-atlas -e              # ログ
systemctl --user reset-failed repo-atlas.service  # 手動実行を繰り返して起動制限に達したとき
./install.sh --check                            # 接続確認
```
