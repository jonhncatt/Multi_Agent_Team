# Vintage Programmer

[English README](README.en.md)  
[中文 README](README.zh-CN.md)  
[Windows Guide](README.windows.md)  
[Release Flow](RELEASING.md)

これはローカル実行の単一メイン agent ワークステーションです。既定のメイン agent は `vintage_programmer` です。  
現在の安定版は `v2.6.9` です。

現在のワークステーション構成:
- 左側の thread rail
- 中央のフル幅ワークプレーン
- 常時表示の下部 composer
- 下部ステータスバー
- 右側の Workbench drawer
- ローカル skill / agent spec の編集

## 起動

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
./run.sh
```

起動先:

- <http://127.0.0.1:8080>

### Windows

Windows では仮想環境の activate を省略し、venv 内の Python を直接呼ぶ方法を推奨します。

```powershell
py -3.11 -m venv .venv
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

詳細は [README.windows.md](README.windows.md) を参照してください。

## 最小 `.env`

OpenAI 公式:

```env
VP_LLM_PROVIDER=openai
VP_OPENAI_API_KEY=your_key
VP_OPENAI_DEFAULT_MODEL=gpt-5.1-chat
```

`VP_OPENAI_API_KEY` がなくても、ローカルに `VP_CODEX_AUTH_FILE` があれば自動的に Codex auth を使います。

OpenAI-compatible gateway:

```env
VP_LLM_PROVIDER=openai_compatible
VP_OPENAI_COMPAT_API_KEY=your_gateway_key
VP_OPENAI_COMPAT_BASE_URL=https://your-gateway.example.com/v1
VP_OPENAI_COMPAT_CA_CERT_PATH=/absolute/path/to/your-root-ca.pem
VP_OPENAI_COMPAT_DEFAULT_MODEL=gpt-5.1-chat
```

OpenRouter:

```env
VP_LLM_PROVIDER=openrouter
VP_OPENROUTER_API_KEY=your_openrouter_key
VP_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
VP_OPENROUTER_DEFAULT_MODEL=google/gemma-4-31b-it:free
VP_OPENROUTER_MODEL_FALLBACKS=nvidia/nemotron-3-super-120b-a12b:free
```

その他の例は [.env.example](.env.example) を参照してください。

言語の既定値を固定したい場合は `.env` に次を追加できます。

```env
VP_DEFAULT_LOCALE=ja-JP
```

サポート値は `zh-CN`、`ja-JP`、`en` です。実際の言語優先順位は
Settings での現在選択 > ブラウザ保存値 > ブラウザ言語 > `VP_DEFAULT_LOCALE`
です。

## 日本語配布方針

- 言語のために別リポジトリは作らず、単一リポジトリを維持します。
- 内部のクラス名、関数名、ルーティング、変数名は翻訳しません。
- 翻訳対象は、ユーザーに見える UI 文言、後端のユーザー向けメッセージ、agent の既定 spec、README です。
- 社内配布では既定 locale を `ja-JP` にしつつ、同じコードベースで `zh-CN` と `en` にも切り替えられます。

## Agent Specs

メイン agent は 4 つの markdown spec で定義されます。ランタイムは locale に応じて対応版を優先ロードします。

- `agents/vintage_programmer/soul.md`
- `agents/vintage_programmer/identity.md`
- `agents/vintage_programmer/agent.md`
- `agents/vintage_programmer/tools.md`

ローカライズ版:

- `agents/vintage_programmer/locales/ja-JP/`
- `agents/vintage_programmer/locales/en/`

## Local Skills

ローカル skills は次に配置します:

- `workspace/skills/<skill_id>/SKILL.md`

`enabled: true` かつ `bind_to` に `vintage_programmer` を含む skill だけがメイン agent に注入されます。

## Release

正式リリース手順:

- `codex/*` 候補ブランチで変更を進める
- 回帰確認後に `main` へマージする
- リリース commit に `v2.6.0` のような annotated tag を付ける
- 次の作業は常に最新 `main` から新しい `codex/*` ブランチを切って始める

詳細は [RELEASING.md](RELEASING.md) を参照してください。
