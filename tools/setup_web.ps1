#requires -Version 5.1
<#
Prepare only this checkout's isolated Web environment and static UI.
Usage: powershell -ExecutionPolicy Bypass -File tools/setup_web.ps1
Optional: -Python 'C:/path/to/python.exe'
#>
[CmdletBinding()]
param([string]$Python = 'python', [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$environmentPath = Join-Path $projectRoot '.venv-web'
$frontendPath = Join-Path $projectRoot 'web_app/frontend'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE)." }
}

Get-Command $Python -ErrorAction Stop | Out-Null
$nodeCommand = (Get-Command node -ErrorAction Stop).Source
$npmCommand = (Get-Command npm.cmd -ErrorAction Stop).Source
Invoke-Checked -Program $Python -Arguments @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)')
Invoke-Checked -Program $nodeCommand -Arguments @('-e', 'const [a,b]=process.versions.node.split(String.fromCharCode(46)).map(Number); if(!((a===20&&b>=19)||(a===22&&b>=12)||a>=24)) process.exit(1)')

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $environmentPath 'Scripts/python.exe'))) {
        Invoke-Checked -Program $Python -Arguments @('-m','venv','--system-site-packages',$environmentPath)
    }
    $webPython = Join-Path $environmentPath 'Scripts/python.exe'
    if (-not $SkipInstall) {
        Invoke-Checked -Program $webPython -Arguments @('-m','pip','install','-r','requirements-web.txt')
    }
    Push-Location $frontendPath
    try {
        if (-not $SkipInstall) { Invoke-Checked -Program $npmCommand -Arguments @('ci') }
        Invoke-Checked -Program $npmCommand -Arguments @('run','build')
    } finally { Pop-Location }
    Write-Host 'Ready. Run the launcher in the project root, or:' -ForegroundColor Green
    Write-Host ('"' + $webPython + '" run_web.py --open')
} finally { Pop-Location }
