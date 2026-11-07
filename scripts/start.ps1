$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
}
& $pythonExecutable -c "import streamlit,pandas,openpyxl,xlrd,pydantic,httpx" 2>$null
if ($LASTEXITCODE -ne 0) {
    $dependencyFile = if (Test-Path -LiteralPath 'requirements-lock.txt') { 'requirements-lock.txt' } else { 'requirements.txt' }
    & $pythonExecutable -m pip install -r $dependencyFile
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'samples\expected.json'))) {
    & $pythonExecutable scripts\generate_samples.py
}
if (Test-Path -LiteralPath (Join-Path $projectRoot '.runtime\ollama\ollama.exe')) {
    try { & (Join-Path $PSScriptRoot 'start-ai.ps1') } catch { Write-Warning $_ }
}
& $pythonExecutable -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false

