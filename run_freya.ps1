param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$client = Join-Path $root 'client'
$uiServer = Join-Path $root 'ui_server.py'

function Stop-FreyaPort([int]$port) {
    $matches = netstat -ano | Select-String (":$port\s+.*LISTENING\s+(\d+)$")
    foreach ($match in $matches) {
        $parts = $match.ToString().Trim() -split '\s+'
        if ($parts.Count -gt 0) { taskkill.exe /PID $parts[-1] /T /F | Out-Null }
    }
}

if (-not (Test-Path -LiteralPath $python)) { throw "Freya virtual environment Python was not found: $python" }
if (-not (Test-Path -LiteralPath $uiServer)) { throw "Freya backend entry point was not found: $uiServer" }
if (-not (Test-Path -LiteralPath (Join-Path $client 'package.json'))) { throw "Freya frontend package was not found: $client" }

Stop-FreyaPort 8787
Stop-FreyaPort 5173
Start-Sleep -Milliseconds 500

$venvSitePackages = Join-Path $root '.venv\Lib\site-packages'
if (Test-Path -LiteralPath $venvSitePackages) {
    $existingPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($existingPythonPath)) {
        $venvSitePackages
    } else {
        "$venvSitePackages;$existingPythonPath"
    }
}

$backendArgs = @((('"{0}"' -f $uiServer)), '--host', '127.0.0.1', '--port', '8787')
$backend = Start-Process -FilePath $python -ArgumentList $backendArgs -WorkingDirectory $root -PassThru
$pnpm = (Get-Command pnpm.cmd -ErrorAction Stop).Source
$frontend = Start-Process -FilePath $pnpm -ArgumentList @('dev', '--host', '127.0.0.1', '--port', '5173') -WorkingDirectory $client -PassThru

$deadline = [DateTime]::UtcNow.AddSeconds(60)
$backendReady = $false
$frontendReady = $false
while ([DateTime]::UtcNow -lt $deadline) {
    if (-not $backendReady) {
        try { $backendReady = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8787/api/health' -TimeoutSec 3).StatusCode -eq 200 } catch { }
    }
    if (-not $frontendReady) {
        try { $frontendReady = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/' -TimeoutSec 3).StatusCode -eq 200 } catch { }
    }
    if ($backendReady -and $frontendReady) { break }
    if ($backend.HasExited -or $frontend.HasExited) { break }
    Start-Sleep -Seconds 1
}

if (-not $backendReady -or -not $frontendReady) {
    if ($backend.HasExited) { throw "Freya backend exited before readiness." }
    if ($frontend.HasExited) { throw "Freya frontend exited before readiness." }
    throw "Freya services did not become ready within 60 seconds."
}

Write-Host 'Freya is running at http://127.0.0.1:5173/'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173/' | Out-Null }
