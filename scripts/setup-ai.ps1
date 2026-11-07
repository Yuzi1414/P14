param([string]$Version = 'v0.40.5')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot '.runtime'
$ollamaDir = Join-Path $runtimeRoot 'ollama'
$archivePath = Join-Path $runtimeRoot 'ollama-windows-amd64.zip'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $ollamaDir 'ollama.exe'))) {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/ollama/ollama/releases/tags/$Version"
    $asset = $release.assets | Where-Object { $_.name -eq 'ollama-windows-amd64.zip' } | Select-Object -First 1
    if (-not $asset) { throw 'Official release archive not found.' }
    if (-not (Test-Path -LiteralPath $archivePath) -or (Get-Item -LiteralPath $archivePath).Length -ne $asset.size) {
        & curl.exe --fail --location --retry 1 --continue-at - --output $archivePath $asset.browser_download_url
        if ($LASTEXITCODE -ne 0) { throw 'Download failed; re-run to resume.' }
    }
    if ((Get-Item -LiteralPath $archivePath).Length -ne $asset.size) { throw 'Archive size mismatch.' }
    if ($asset.digest -like 'sha256:*') {
        $actualDigest = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualDigest -ne $asset.digest.Substring(7)) { throw 'Official SHA256 verification failed.' }
    }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $ollamaDir -Force
    # Only remove the downloaded archive inside this project; keep installed runtime and models.
    Remove-Item -LiteralPath $archivePath
}
& (Join-Path $PSScriptRoot 'start-ai.ps1')
for ($checkIndex = 0; $checkIndex -lt 30; $checkIndex++) {
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
        break
    } catch { Start-Sleep -Seconds 1 }
}
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_MODELS = Join-Path $runtimeRoot 'models'
$installedModels = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
if ($installedModels.models.name -contains 'qwen3:4b') {
    Write-Host 'qwen3:4b is already installed; no network download required.'
    return
}
& (Join-Path $ollamaDir 'ollama.exe') pull qwen3:4b
if ($LASTEXITCODE -ne 0) {
    $pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExecutable)) { throw 'Model download failed; create the Python environment or re-run to resume.' }
    Write-Warning 'Native downloader failed. Downloading official registry artifacts with system curl and SHA256 checks.'
    & $pythonExecutable (Join-Path $PSScriptRoot 'download_model.py')
    if ($LASTEXITCODE -ne 0) { throw 'Verified model artifact download failed. Re-run download_model.py to resume.' }
}
Write-Host 'Local model ready. Subsequent use does not require internet.'

