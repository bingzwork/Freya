param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$client = Join-Path $root 'client'
$uiServer = Join-Path $root 'ui_server.py'
function Stop-FreyaPort([int]$port) {
    $matches = netstat -ano | Select-String (":$port\s+.*LISTENING\s+(\d+)$")
    foreach ($match in $matches) { $parts = $match.ToString().Trim() -split '\s+'; if ($parts.Count -gt 0) { taskkill.exe /PID $parts[-1] /T /F | Out-Null } }
}
$backend = $null
$frontend = $null
try {
$backend = Start-Process -FilePath $python -ArgumentList @(("`"{0}`"" -f $uiServer), '--host', '127.0.0.1', '--port', '8787') -WorkingDirectory $root -PassThru
$pnpm = (Get-Command pnpm.cmd -ErrorAction Stop).Source
$frontend = Start-Process -FilePath $pnpm -ArgumentList @('dev', '--host', '127.0.0.1', '--port', '5173') -WorkingDirectory $client -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds(60)
$ready = $false
while ([DateTime]::UtcNow -lt $deadline) { try { if ((Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/' -TimeoutSec 3).StatusCode -eq 200) { $ready = $true; break } } catch { } Start-Sleep -Seconds 1 }
if (-not $ready) { throw 'Freya frontend did not become ready within 60 seconds.' }
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173/' }
Write-Host 'Freya is running at http://127.0.0.1:5173/'
while ((netstat -ano | Select-String ':8787\s+.*LISTENING') -or (netstat -ano | Select-String ':5173\s+.*LISTENING')) { Start-Sleep -Seconds 2 }
} finally {
    Stop-FreyaPort 5173
    Stop-FreyaPort 8787
    if ($null -ne $frontend -and -not $frontend.HasExited) { taskkill.exe /PID $frontend.Id /T /F | Out-Null }
    if ($null -ne $backend -and -not $backend.HasExited) { taskkill.exe /PID $backend.Id /T /F | Out-Null }
}
