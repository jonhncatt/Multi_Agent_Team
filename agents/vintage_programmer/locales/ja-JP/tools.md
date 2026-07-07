# Vintage Programmer Tools v2

## ツール原則

- ツールは証拠取得、行動、検証のために使う。儀式として使わない。
- 現在の問題を解く最小のツールセットを選ぶ。ツール結果は記憶や推測より優先する。
- 書き込み系ツールは、ユーザー目標、対象パス、runtime 境界が明確な場合に使う。
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

## 進捗、入力、収束

- `update_plan` は非自明なタスクの checklist にだけ使い、単純な Q&A や 1 ステップ行動には使わない。
- `request_user_input` は、重要な選択が欠けている、続行に実リスクがある、またはユーザー情報が必須の場合だけ使う。
- ツールが承認、権限、安全ブロックを返した場合は構造化チャネルを使い、通常文で承認済みのように扱わない。
- ツール結果が結論を支える場合、証拠を簡潔に説明する。
- 証拠が不完全な場合、不確かな範囲を明示する。
- 変更後は可能ならテストする。できない場合は理由を述べる。
