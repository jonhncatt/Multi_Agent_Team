param(
    [string]$Python = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

if (-not (Test-Path $Python)) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $Python = "python"
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $Python = "py"
    }
    else {
        throw "Python was not found. Install Python 3.11 or create .venv first."
    }
}

& $Python -m pip install -r desktop\windows\requirements-build.txt
& $Python -m pytest -q tests\test_desktop_assets.py tests\test_desktop_launcher.py
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --noconsole `
    --icon desktop\windows\assets\validation_assistant_shell_v1.ico `
    --add-data "desktop\windows\assets\validation_assistant.ico;desktop\windows\assets" `
    --name ValidationAssistant `
    desktop\launcher.py

& $Python desktop\windows\verify_executable_icon.py dist\ValidationAssistant.exe

Write-Host "Built: $RepoRoot\dist\ValidationAssistant.exe"
Write-Host "Copy ValidationAssistant.exe into $RepoRoot before double-clicking it."
