#!/usr/bin/env bash
set -euo pipefail

mkdir -p audit

# keyword scans
git grep -n -i \
  "codex\|openclaw\|responses\|chatgpt-account-id\|backend-api/codex\|auth.openai.com\|apply_patch\|browser_fallback\|openclaw_inspired\|codex_core" \
  > audit/keyword_source_hits.txt || true

git grep -l -i \
  "codex\|openclaw\|responses\|chatgpt-account-id\|backend-api/codex\|auth.openai.com\|apply_patch\|browser_fallback\|openclaw_inspired\|codex_core" \
  -- '*.py' '*.js' '*.ts' '*.css' '*.json' '*.yml' '*.yaml' \
  > audit/keyword_source_files.txt || true

git grep -l -i \
  "codex\|openclaw\|responses\|chatgpt-account-id\|backend-api/codex\|auth.openai.com\|apply_patch\|browser_fallback\|openclaw_inspired\|codex_core" \
  -- '*.md' 'NOTICE' \
  > audit/keyword_doc_files.txt || true

# dependency scans
python -m pip install pip-licenses
pip-licenses --format=markdown --with-urls --with-description > THIRD_PARTY_LICENSES.md
python -m pip freeze > audit/pip_freeze_snapshot.txt

# secret scans
git grep -n -i \
  "api_key\|token\|secret\|password\|bearer\|refresh_token\|access_token\|id_token\|account_id\|proxy\|internal\|corp\|kioxia\|zeus\|base_url\|ca_cert" \
  > audit/secret_internal_keyword_hits.txt || true

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --source . --redact --report-path audit/gitleaks_report.json || true
else
  printf 'gitleaks unavailable\n' > audit/gitleaks_status.txt
fi

if command -v trufflehog >/dev/null 2>&1; then
  trufflehog git file://. --only-verified --json > audit/trufflehog_verified.json || true
else
  printf 'trufflehog unavailable\n' > audit/trufflehog_status.txt
fi

# validation
./.venv/bin/python -m compileall app packages tests || python3 -m compileall app packages tests
pytest -q

# notes for external similarity scan
# Run from a temp directory outside the repository root, for example /tmp/vp-oss-audit.
# Example:
#   mkdir -p /tmp/vp-oss-audit
#   cd /tmp/vp-oss-audit
#   git clone https://github.com/jonhncatt/Multi_Agent_Team.git vp
#   git clone https://github.com/openai/codex.git codex
#   git clone https://github.com/openclaw/openclaw.git openclaw
#
# Preferred duplicate scan:
#   jscpd vp codex \
#     --no-gitignore \
#     --pattern "**/*.{py,js,ts,css,md}" \
#     --min-lines 8 \
#     --min-tokens 50 \
#     --reporters console,json,html \
#     --output /tmp/vp-oss-audit/report-vp-vs-codex
#
#   jscpd vp openclaw \
#     --no-gitignore \
#     --pattern "**/*.{py,js,ts,css,md}" \
#     --min-lines 8 \
#     --min-tokens 50 \
#     --reporters console,json,html \
#     --output /tmp/vp-oss-audit/report-vp-vs-openclaw
#
# If full-tree OpenClaw scan exceeds memory, narrow the scan to the reviewed files:
#   jscpd /path/to/repo/app/local_tools.py /tmp/vp-oss-audit/openclaw/src/agents/apply-patch.ts \
#     /tmp/vp-oss-audit/openclaw/src/agents/tool-catalog.ts /tmp/vp-oss-audit/openclaw/src/agents/tools \
#     --no-gitignore --min-lines 8 --min-tokens 50 --reporters console,json
