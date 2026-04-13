$ErrorActionPreference = "Stop"

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $rootDir

if (Test-Path ".env") {
  Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
      if ($line.StartsWith("export ")) {
        $line = $line.Substring(7).Trim()
      }

      $eq = $line.IndexOf("=")
      if ($eq -ge 1) {
        $key = $line.Substring(0, $eq).Trim().TrimStart([char]0xFEFF)
        if ($key) {
          $value = $line.Substring($eq + 1).Trim()
          if (
            ($value.Length -ge 2) -and
            (
              ($value.StartsWith('"') -and $value.EndsWith('"')) -or
              ($value.StartsWith("'") -and $value.EndsWith("'"))
            )
          ) {
            $value = $value.Substring(1, $value.Length - 2)
          }

          if ($value.Contains(" #")) {
            $value = $value.Split(" #", 2)[0].TrimEnd()
          }

          Set-Item -Path "Env:$key" -Value $value
        }
      }
    }
  }
}

function Get-EnvFirst {
  param([string[]]$Keys)
  foreach ($key in $Keys) {
    $value = [Environment]::GetEnvironmentVariable($key)
    if ($value) {
      return $value
    }
  }
  return $null
}

$providerRaw = Get-EnvFirst @("VP_LLM_PROVIDER", "VP_MODEL_PROVIDER")
if (-not $providerRaw) { $providerRaw = "openai" }
$llmProvider = $providerRaw.ToLowerInvariant()
switch ($llmProvider) {
  "" { $llmProvider = "openai" }
  "default" { $llmProvider = "openai" }
  "openai-compatible" { $llmProvider = "openai_compatible" }
}

$expectedApiKeyEnv = switch ($llmProvider) {
  "openai" { "VP_OPENAI_API_KEY" }
  "openai_compatible" { "VP_OPENAI_COMPAT_API_KEY" }
  "openrouter" { "VP_OPENROUTER_API_KEY" }
  "deepseek" { "VP_DEEPSEEK_API_KEY" }
  "qwen" { "VP_DASHSCOPE_API_KEY" }
  "moonshot" { "VP_MOONSHOT_API_KEY" }
  "groq" { "VP_GROQ_API_KEY" }
  "ollama" { "VP_OLLAMA_API_KEY" }
  default { "VP_LLM_API_KEY" }
}

$providerApiKey = Get-EnvFirst @($expectedApiKeyEnv, "VP_LLM_API_KEY")
$hasApiKey = [bool]$providerApiKey
$supportsCodexAuth = ($llmProvider -eq "openai")
if ($llmProvider -eq "ollama") {
  $hasApiKey = $true
}

$codexHome = Get-EnvFirst @("VP_CODEX_HOME")
if (-not $codexHome) {
  $codexHome = Join-Path $HOME ".codex"
}
$codexAuthFile = Get-EnvFirst @("VP_CODEX_AUTH_FILE")
if (-not $codexAuthFile) {
  $codexAuthFile = Join-Path $codexHome "auth.json"
}
$hasCodexAuth = Test-Path $codexAuthFile

if (-not $hasApiKey) {
  if ($supportsCodexAuth -and $hasCodexAuth) {
  } elseif ($supportsCodexAuth) {
    Write-Warning "No API key found and Codex auth.json was not found. /api/chat requests will fail until one auth source is available."
  } else {
    Write-Warning "No API key found for provider=$llmProvider. Expected env: $expectedApiKeyEnv (or VP_LLM_API_KEY)."
  }
}

$appModule = Get-EnvFirst @("VP_APP_MODULE")
if (-not $appModule) { $appModule = "app.main:app" }
$appPort = Get-EnvFirst @("VP_APP_PORT")
if (-not $appPort) { $appPort = "8080" }

$env:OFFICETOOL_APP_PROFILE = if ($env:OFFICETOOL_APP_PROFILE) { $env:OFFICETOOL_APP_PROFILE } else { "multi_agent_robot" }

$venvPython = Join-Path $rootDir ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  & $venvPython -m uvicorn $appModule --host 0.0.0.0 --port $appPort --reload
  exit $LASTEXITCODE
}

py -3 -m uvicorn $appModule --host 0.0.0.0 --port $appPort --reload
exit $LASTEXITCODE
