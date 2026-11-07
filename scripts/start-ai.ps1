$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$ollamaExecutable = Join-Path $projectRoot '.runtime\ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $ollamaExecutable)) {
    throw 'Ollama not installed. Run scripts\setup-ai.ps1 first.'
}
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_MODELS = Join-Path $projectRoot '.runtime\models'
$env:OLLAMA_CONTEXT_LENGTH = '4096'
$env:OLLAMA_NUM_PARALLEL = '1'
# Use CPU consistently on the reference laptop; no driver changes are needed.
$env:CUDA_VISIBLE_DEVICES = '-1'
$env:ROCR_VISIBLE_DEVICES = '-1'
$env:GGML_VK_VISIBLE_DEVICES = '-1'
$runtimeDir = Join-Path $projectRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$existingListener = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
if ($existingListener) {
    $existingProcess = Get-Process -Id $existingListener[0].OwningProcess -ErrorAction Stop
    if ($existingProcess.Path -ne $ollamaExecutable -or $existingListener.LocalAddress -contains '0.0.0.0' -or $existingListener.LocalAddress -contains '::') {
        throw 'Port 11434 is owned by another service/configuration. Existing services will not be stopped.'
    }
    Write-Host 'Project local AI service is already running.'
    return
}
$startedProcess = Start-Process -FilePath $ollamaExecutable -ArgumentList 'serve' -WindowStyle Hidden -PassThru `
    -WorkingDirectory $projectRoot -RedirectStandardOutput (Join-Path $runtimeDir 'ollama.stdout.log') `
    -RedirectStandardError (Join-Path $runtimeDir 'ollama.stderr.log')
$startedProcess.Id | Set-Content -LiteralPath (Join-Path $runtimeDir 'ollama.pid')
Write-Host "Local AI started (PID $($startedProcess.Id)), loopback only."

