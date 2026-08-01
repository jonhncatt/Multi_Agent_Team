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
& $Python -m pytest -q tests\test_desktop_launcher.py
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --noconsole `
    --name VintageProgrammer `
    desktop\launcher.py

Write-Host "Built: $RepoRoot\dist\VintageProgrammer.exe"
