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

$authMode = if ($env:MULTI_AGENT_TEAM_LLM_AUTH_MODE) {
  $env:MULTI_AGENT_TEAM_LLM_AUTH_MODE
} elseif ($env:MULTI_AGENT_TEAM_OPENAI_AUTH_MODE) {
  $env:MULTI_AGENT_TEAM_OPENAI_AUTH_MODE
} else {
  "auto"
}
$authMode = $authMode.ToLowerInvariant()

$providerRaw = if ($env:MULTI_AGENT_TEAM_LLM_PROVIDER) {
  $env:MULTI_AGENT_TEAM_LLM_PROVIDER
} elseif ($env:MULTI_AGENT_TEAM_MODEL_PROVIDER) {
  $env:MULTI_AGENT_TEAM_MODEL_PROVIDER
} else {
  "openai"
}
$llmProvider = $providerRaw.ToLowerInvariant()
switch ($llmProvider) {
  "" { $llmProvider = "openai" }
  "default" { $llmProvider = "openai" }
  "openai_compatible" { $llmProvider = "openai" }
  "openai-compatible" { $llmProvider = "openai" }
}

$providerToken = ($llmProvider -replace '[^a-z0-9]', '_').ToUpperInvariant()
if (-not $providerToken) {
  $providerToken = "OPENAI"
}
$providerApiKeyVar = "MULTI_AGENT_TEAM_PROVIDER_${providerToken}_API_KEY"
$expectedApiKeyEnv = $providerApiKeyVar
$nativeProviderApiKeyVar = switch ($llmProvider) {
  "openai" { "OPENAI_API_KEY" }
  "deepseek" { "DEEPSEEK_API_KEY" }
  "qwen" { "DASHSCOPE_API_KEY" }
  "moonshot" { "MOONSHOT_API_KEY" }
  "openrouter" { "OPENROUTER_API_KEY" }
  "groq" { "GROQ_API_KEY" }
  "ollama" { "OLLAMA_API_KEY" }
  default { "" }
}
$apiKeyHint = "$expectedApiKeyEnv (or MULTI_AGENT_TEAM_LLM_API_KEY / OPENAI_API_KEY)"
if ($nativeProviderApiKeyVar -and $nativeProviderApiKeyVar -ne "OPENAI_API_KEY") {
  $apiKeyHint = "$expectedApiKeyEnv (or MULTI_AGENT_TEAM_LLM_API_KEY / $nativeProviderApiKeyVar / OPENAI_API_KEY)"
}

$providerApiKey = [Environment]::GetEnvironmentVariable($providerApiKeyVar)
$nativeProviderApiKey = if ($nativeProviderApiKeyVar) { [Environment]::GetEnvironmentVariable($nativeProviderApiKeyVar) } else { "" }
$hasApiKey = [bool]($providerApiKey -or $env:MULTI_AGENT_TEAM_LLM_API_KEY -or $nativeProviderApiKey -or $env:OPENAI_API_KEY)
$supportsCodexAuth = ($llmProvider -eq "openai")
if ($llmProvider -eq "ollama") {
  $hasApiKey = $true
}

$codexHome = if ($env:MULTI_AGENT_TEAM_CODEX_HOME) {
  $env:MULTI_AGENT_TEAM_CODEX_HOME
} elseif ($env:CODEX_HOME) {
  $env:CODEX_HOME
} else {
  Join-Path $HOME ".codex"
}
$codexAuthFile = if ($env:MULTI_AGENT_TEAM_CODEX_AUTH_FILE) {
  $env:MULTI_AGENT_TEAM_CODEX_AUTH_FILE
} else {
  Join-Path $codexHome "auth.json"
}
$hasCodexAuth = Test-Path $codexAuthFile

switch ($authMode) {
  "api_key" {
    if (-not $hasApiKey) {
      Write-Warning "AUTH_MODE=api_key but no API key found. Expected env: $apiKeyHint."
    }
  }
  "codex_auth" {
    if (-not $supportsCodexAuth) {
      Write-Warning "AUTH_MODE=codex_auth is only supported when MULTI_AGENT_TEAM_LLM_PROVIDER=openai. Current provider=$llmProvider."
    }
    if (-not $hasCodexAuth) {
      Write-Warning "AUTH_MODE=codex_auth but Codex auth file was not found at $codexAuthFile."
    }
  }
  default {
    if (-not $hasApiKey) {
      if ($supportsCodexAuth -and $hasCodexAuth) {
        # codex auth is available, no warning needed
      } elseif ($supportsCodexAuth) {
        Write-Warning "No API key found and Codex auth.json was not found. /api/chat requests will fail until one auth mode is available."
      } else {
        Write-Warning "No API key found for provider=$llmProvider. Expected env: $apiKeyHint."
      }
    }
  }
}

$appModule = if ($env:MULTI_AGENT_TEAM_APP_MODULE) {
  $env:MULTI_AGENT_TEAM_APP_MODULE
} else {
  "app.main:app"
}
$appPort = if ($env:MULTI_AGENT_TEAM_APP_PORT) {
  $env:MULTI_AGENT_TEAM_APP_PORT
} else {
  "8080"
}

$venvPython = Join-Path $rootDir ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  & $venvPython -m uvicorn $appModule --host 0.0.0.0 --port $appPort --reload
  exit $LASTEXITCODE
}

py -3 -m uvicorn $appModule --host 0.0.0.0 --port $appPort --reload
exit $LASTEXITCODE
