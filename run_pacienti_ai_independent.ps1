param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$entry = Join-Path $projectRoot "pacienti_ai_independent\pacienti_ai_app.py"
if (-not (Test-Path $entry)) {
    throw "Lipseste entrypoint-ul: $entry"
}

$python = ""
$py312 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$venvPy = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (Test-Path $py312) {
    $python = $py312
} elseif (Test-Path $venvPy) {
    $python = $venvPy
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py -3"
} else {
    throw "Nu am gasit Python. Instaleaza Python 3.12+ sau configureaza .venv."
}

Write-Host "[INFO] Python runtime: $python"
Write-Host "[INFO] App entrypoint: $entry"

if ($CheckOnly) {
    exit 0
}

if ($python -eq "py -3") {
    & py -3 $entry
} else {
    & $python $entry
}
