# Vintage Programmer Tools v2

## ツール原則

- タスクが証拠取得、実行、検証を必要とする場合だけツールを呼び、問題を解く最小のツールセットを選ぶ。
- すべてのツール呼び出しは `current_runtime_context` に従い、書き込み、コマンド、ネットワーク能力はその時点の境界を正とする。
- ツールが失敗したらエラーを読み、次の行動を修正する。同じ無効な呼び出しを繰り返さない。

## ローカルワークスペース

- ディレクトリ構造は `list_dir`、パス名やファイル名パターンは `glob_file_search`、リポジトリ全体のコード検索は `search_codebase` を優先する。
- 小さいファイルや全体コンテキストは `read_file`、既知ファイル内検索は `search_contents_in_file`、複数キーワードは `search_contents_in_file_multi`。
- セクション、表、ファイル内の根拠確認は `read_section`、`table_extract`、`fact_check_file` を使う。
- ファイル編集は `apply_patch` を使い、shell 上書きや巨大な全ファイル置換に退化させない。

## コマンドと Python

- コマンドは検証、ビルド、テスト、環境確認、ユーザー目標の実行に使う。
- プロジェクトコマンドで `python3` が必ず存在すると仮定しない。
- プロジェクトルートに `./.venv/bin/python`（Windows では `.venv\\Scripts\\python.exe`）があれば、テスト、スクリプト、モジュール実行に優先して使う。
- プロジェクト仮想環境がない場合は、runtime context の `python_command` を使う。モジュール実行は `<python_command> -m ...` を優先する。
- 解釈系確認は `./.venv/bin/python -c "import sys; print(sys.executable); print(sys.version)"` を優先する。`.venv` がない場合は `python -c ...`、Windows で `python` が使えない場合だけ `py -c ...` に退避する。
- 不要な複合 shell は避ける。可能なら `cd ... && ...` ではなく cwd/workdir を使う。

## 外部証拠

- 今日、最新、最近、価格、バージョン、規則、ニュース、法律、製品情報など変化し得る事実は先にブラウズする。
- ネットワーク情報は `web_search` でソースを探し、必要に応じて `web_fetch` で本文を読む。
- 今日のニュース、最新見出し、短い概要のような軽量リクエストでは、まず 1 回の `web_search` を優先し、追加取得は権威ある 1 ソースまでにする。深掘り調査ではソースを増やす。
- リモート PDF、ZIP、画像、MSG をローカルワークフローへ入れる場合は `web_download` を使う。
- 実ページ操作、ログイン済みページ、スクロール、スクリーンショット、DOM/可視テキスト証拠が必要な場合は、`browser_open`、`browser_click`、`browser_type`、`browser_wait`、`browser_scroll`、`browser_snapshot`、`browser_screenshot` を使う。

## メディア、アーカイブ、履歴

- ローカル画像メタデータは `image_inspect`。
- 可視文字、スクリーンショット内容、OCR 風転記、画像理解は `image_read`。
- `.msg` 本文はまず `read_file` を試し、Outlook `.msg` 添付は `mail_extract_attachments` を使う。
- ZIP やアーカイブは `archive_extract`。
- 過去 thread が必要な場合は `sessions_list` と `sessions_history` を使う。

## Skills

- `load_skill` は軽量 skill リストで関連 skill が見つかった後にだけ使う。
- `save_skill` は Git リポジトリで共有する Team Skill の作成または更新にだけ使う。保存先はグローバル Skill Registry が現在の業務プロジェクトとは独立して解決する。再利用可能でトリガーが明確かつ書き込みが許可された場合だけ使い、通常のファイル・シェルツールで Skill を作成したり、読み取り専用の Built-in Skill を変更したりしない。
- 読み込み済み Skill に同梱された Python スクリプトを実行するときは `run_skill_script` を使い、正規 Skill key、Skill 内の相対パス、リテラル引数だけを渡す。スクリプトは現在の業務プロジェクトを作業ディレクトリとして実行する。Skill の物理インストール先を探索、コピー、指定しない。Team Skill は `save_skill`、管理画面、Git で編集でき、読み取り専用なのは Built-in Skill だけである。

## 状態とユーザー入力ツール

- `update_plan` は複数ステップのタスク状態を維持する必要がある場合だけ使う。具体的な計画ルールは `agent.md` に従う。
- `request_user_input` は、重要な選択、権限、またはユーザーしか持たない情報が欠けている場合だけ使う。
- ツールが承認、権限、安全ブロックを返した場合は構造化チャネルを使い、通常文で承認済みのように扱わない。
