# repo-atlas

hamashin の GitHub リポジトリ (大半は非公開) が、それぞれ何をしているかをまとめた目録です。
このページと `repos/` 以下のページは、本リポジトリの仕組みで **毎日 1 回自動生成** されています。

## このリポジトリの仕組み

- 毎朝、自宅サーバー上のコンテナが GitHub API で自分のリポジトリ一覧を取得します。新しいリポジトリは自動で追加し、削除されたリポジトリは自動で取り除きます。
- 前回から変更のあったリポジトリだけソースを取得し、**ローカルで動かしている LLM (Ollama)** で概要と構成を要約します。外部の AI サービスにソースは送りません。
- 構成図は、LLM が出力した構造データを Graphviz で描画したものです。
- 公開前に IP アドレス・MAC アドレス・内部ホスト名・認証情報などを除外・マスクし、生成物を再検査します。検出された場合は、そのリポジトリの更新を見送ります。
- 生成物は bot が main に直接 push します。処理ロジックの変更は Pull Request で行います。

詳しくは [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照してください。

## リポジトリ一覧

26 件 (最終生成: 2026-11-24 08:38 JST)

| リポジトリ | 概要 | 最終更新日 | 最後にマージされた改修 |
|---|---|---|---|
| [repo-atlas](repos/repo-atlas/) 🌐 | 非公開GitHubリポジトリのソースをローカルLLMで解析し、機密情報を除去した概要と構成図を毎日自動生成・公開する目録ツール。 | 2026-11-24 | 2026-10-21 再解析ループを修正し、AWS ARNとアカウントIDのマスク機能を追加 |
| [home-netmap](repos/home-netmap/) 🔒 | 自宅LANの機器構成と接続関係を自動収集し、可視化されたネットワーク図と詳細な機器一覧を生成するツールです。 | 2026-11-24 | 2026-11-24 netmapの構成変更検出機能を追加 |
| [claude-memory](repos/claude-memory/) 🔒 | Claude Code のプロジェクト別メモリーを毎日自動バックアップし、秘密情報の混入を検出・通知する仕組みを提供します。 | 2026-11-24 | 2026-11-24 メモリファイルを更新 |
| [homelab-siem](repos/homelab-siem/) 🔒 | 自宅ラボのログをWazuhで集約し、ローカルLLMで分析してSlackに通知するSIEM環境を構築・運用するためのリポジトリ。 | 2026-11-23 | 2026-11-15 suricata の IP と版のドキュメント情報を更新 |
| [homelab-energy](repos/homelab-energy/) 🔒 | スマートプラグとサーバーの電力データを収集し、Home Assistant経由でPrometheusに蓄積して電気代を可視化する。 | 2026-11-19 | 2026-11-19 ダッシュボードパネルの名称を統一し、再実行時の位置・サイズ・タイトルの保持機能を追加 |
| [homelab-vault](repos/homelab-vault/) 🔒 | 自宅環境のパスワード管理と、AIエージェントが秘密情報を見ずに利用するための仲介基盤を提供する。 | 2026-11-19 | 2026-11-19 secret-broker に .env のバックアップ・復元機能を追加 |
| [local-llm-stack](repos/local-llm-stack/) 🔒 | ローカルLLM環境で、メタ検索とチャットUIをコンテナ化して統合運用するためのセットアップツールです。 | 2026-11-19 | 2026-11-19 .gitignore に .env とログの除外設定を追加 |
| [stackchan-zundamon](repos/stackchan-zundamon/) 🔒 | PrometheusアラートやSlack投稿、気象・地震情報をM5Stack機器でVOICEVOX音声として読み上げるシステム。 | 2026-11-15 | 2026-11-15 voicevoxのヘルスチェックをbashの/dev/tcpに修正 |
| [auto-remediator](repos/auto-remediator/) 🔒 | Prometheusアラートを契機にローカルLLMで障害を自動調査し、Slack承認を経て復旧する仕組み。 | 2026-11-15 | 2026-11-15 tbot の停止を失敗とみなさないよう設定し、通知ロジックを修正 |
| [homelab-teleport](repos/homelab-teleport/) 🔒 | 自宅環境のSSH接続をTeleportの短命証明書認証に置き換え、固定鍵のリスクを低減する。 | 2026-11-11 | 2026-10-19 バージョンを20261019155240に更新 |
| [camrec](repos/camrec/) 🔒 | 監視カメラの映像をブラウザでリアルタイム表示し、指定カメラの録画データをNASへ自動保存するシステム。 | 2026-11-11 | 2026-06-22 RTSPリレーのハング防止にタイムアウトを追加 |
| [home-heartbeat](repos/home-heartbeat/) 🔒 | 自宅サーバの死活監視を、外部サービスへの定期送信のみで実現する。受信ポートを開けずにダウンを検知できる。 | 2026-10-20 | 2026-10-20 Healthchecks.io による push 型死活監視機能を追加 |
| [netmap](repos/netmap/) 🔒 | LAN内の機器情報をSSH・SNMP等で自動収集し、構成図と機器一覧を定期生成するツール。 | 2026-10-19 | 2026-10-19 tbot を 18.11.4 に更新 |
| [catchall-mail-notifier](repos/catchall-mail-notifier/) 🔒 | 独自ドメイン宛のメールを事前設定なしで受信し、Slack通知や管理者への転送を自動化するCloudflare Email Workerです。 | 2026-10-14 | 2026-10-14 catch-all 受信と Slack 通知を行う Worker を追加 |
| [ascon_at08](repos/ascon_at08/) 🔒 | ASCON AT-08 タブレットで Ubuntu を安定動作させるためのブートローダ置換と画面表示修正スクリプト集。 | 2026-10-12 | 2026-10-06 セットアップ手順の記録を追加 |
| [claude-diary-pages](repos/claude-diary-pages/) 🔒 | Claude Code による開発セッションのログを Markdown 形式で保存し、静的サイトジェネレーターで検索可能な日記サイトとして公開するリポジトリです。 | 2026-09-29 | 2026-09-29 2026-09-29 の日記を追加 |
| [iptvrec](repos/iptvrec/) 🔒 | M3UリストからIPTVをブラウザで視聴・録画し、EPG連携でスケジュール管理するWebアプリ。 | 2026-09-04 | 2026-03-05 READMEに画像付き操作マニュアルを追加 |
| [kendo-keychain](repos/kendo-keychain/) 🔒 | 剣道垂ネームをモチーフにした3Dプリント用キーホルダーを、Web入力から3MFデータとして自動生成するシステム。 | 2026-06-25 | 2026-06-25 複数書体対応、印刷品質改善、3Dプレビューのフォント反映を追加 |
| [chime2slack](repos/chime2slack/) 🔒 | ドアホンの点灯を検知してカメラ画像を撮影し、Slackに通知するシステム。 | 2026-02-27 | 2026-02-27 音声通知を廃止し、ファイルアップロードAPIに変更 |
| [camera_viewer](repos/camera_viewer/) 🔒 | RTSP対応カメラ4台の映像をHLS変換し、ブラウザで2×2グリッド表示する監視システム。 | 2025-12-12 | 2025-12-12 READMEのMarkdownリンク形式を修正 |
| [aws_utils_scripts](repos/aws_utils_scripts/) 🔒 | AWS環境の保守・監視を効率化するため、アラーム集計やRDSスナップショット検証、設定値のドキュメント化を行うスクリプト群。 | 2025-12-08 | 2025-12-08 sendmailのメールアドレス設定を更新 |
| [wifi-watchdog](repos/wifi-watchdog/) 🔒 | ラズパイ上のWi-Fi接続状態を監視し、連続失敗時に自動で無線インターフェースを再起動する仕組みを提供します。 | 2025-09-10 | 2025-09-10 READMEにインストール手順を追加 |
| [docker-memo](repos/docker-memo/) 🔒 | Apache Tomcat 9 を Java 21 環境で実行するための Docker イメージを構築し、Web アプリケーションのデプロイ基盤を提供する。 | 2025-06-25 | 2025-06-25 メモファイルとTomcatコンテナ設定を追加 |
| [ansible_trashbox](repos/ansible_trashbox/) 🔒 | Raspberry PiやLinuxサーバーの初期設定、更新、監視エージェント導入をAnsibleで自動化するプレイブック集。 | 2024-03-26 | 2024-03-26 初期コミットを追加 |
| [aws_utils_lambda](repos/aws_utils_lambda/) 🔒 | AWS環境の監視・保守・デプロイを支援するLambda関数群。アラート通知やDB操作、CI/CD承認を自動化し運用負荷を軽減する。 | 2024-03-26 | 2024-03-26 Lambda関数を追加 |
| [cloudformation-util-master](repos/cloudformation-util-master/) 🔒 | AWS環境の構築と運用効率化を支援するCloudFormationテンプレート集。VPC設計からコスト削減、ログ管理、通知までを標準化し、複数プロジェクトで再利用可能にする。 | 2024-03-26 | 2024-03-26 CloudFormation用ユーティリティの初期コミットを追加 |

🔒 非公開 / 🌐 公開 / 🗄️ アーカイブ済み
