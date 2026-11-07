$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
# Stop only processes whose saved PID and executable/command match this project.
foreach ($serviceName in @('ollama','streamlit')) {
    $pidFile = Join-Path $projectRoot "runtime\$serviceName.pid"
    if (Test-Path -LiteralPath $pidFile) {
        $servicePid = [int](Get-Content -LiteralPath $pidFile)
        $serviceProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$servicePid" -ErrorAction SilentlyContinue
        if ($serviceProcess -and ($serviceProcess.ExecutablePath -like "$projectRoot\*")) {
            # Windows venv launchers may create a system-Python child; ownership is
            # established by the verified project parent, not the child's exe path.
            $processSnapshot = @(Get-CimInstance Win32_Process)
            $ownedTree = [System.Collections.Generic.HashSet[int]]::new()
            [void]$ownedTree.Add($servicePid)
            do {
                $added = $false
                foreach ($candidateProcess in $processSnapshot) {
                    if ($ownedTree.Contains([int]$candidateProcess.ParentProcessId) -and $ownedTree.Add([int]$candidateProcess.ProcessId)) {
                        $added = $true
                    }
                }
            } while ($added)
            foreach ($childPid in $ownedTree) {
                if ($childPid -ne $servicePid) { Stop-Process -Id $childPid -ErrorAction SilentlyContinue }
            }
            Stop-Process -Id $servicePid
        }
        Remove-Item -LiteralPath $pidFile
    }
}

