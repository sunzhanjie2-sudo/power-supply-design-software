#requires -Version 5.1
<# Build self-contained Windows x64 folders. Never bundles the virtualenv or
   node_modules; never overwrites a release directory. Run from any directory. #>
[CmdletBinding()]
param([ValidateSet('web','desktop','all')][string]$Target='all',
      [string]$ReleaseId='20261023', [string]$Python='', [switch]$SkipFrontend)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($ReleaseId -notmatch '^[a-zA-Z0-9_-]+$') { throw 'ReleaseId must contain only letters, numbers, underscores or hyphens.' }
if (-not $Python) { $Python=Join-Path $projectRoot '.venv-web/Scripts/python.exe' }
$releaseRoot=Join-Path $projectRoot ('releases/Windows-x64/'+$ReleaseId)
function Run-Checked([string]$program,[string[]]$arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "$program failed: $LASTEXITCODE" }
}
Push-Location $projectRoot
try {
    Run-Checked $Python @('-c','import PyInstaller; import sys; assert sys.maxsize>2**32')
    if ($Target -ne 'desktop' -and -not $SkipFrontend) {
        Push-Location (Join-Path $projectRoot 'web_app/frontend')
        try {
            Run-Checked 'npm.cmd' @('run','build')
            if (Test-Path -LiteralPath 'vite.pcs.config.ts') {Run-Checked 'npx.cmd' @('--no-install','vite','build','--config','vite.pcs.config.ts')}
        } finally { Pop-Location }
    }
    $targets=if($Target -eq 'all'){@('desktop','web')}else{@($Target)}
    foreach ($part in $targets) {
        $folderName=if($part -eq 'desktop'){'PowerDesignDesktop'}else{'PowerDesignWeb'}
        $folder=Join-Path $releaseRoot $folderName
        if (Test-Path -LiteralPath $folder) { throw "Release exists; choose a new ReleaseId: $folder" }
        Run-Checked $Python @('-m','PyInstaller','--noconfirm','--distpath',$releaseRoot,
            '--workpath',(Join-Path $projectRoot ('artifacts/build/'+$ReleaseId+'/'+$part)),
            (Join-Path $projectRoot ('packaging/'+$part+'.spec')))
        $readme=if($part -eq 'web'){'WEB_README.txt'}else{'DESKTOP_README.txt'}
        Copy-Item -LiteralPath (Join-Path $projectRoot ('packaging/'+$readme)) -Destination (Join-Path $folder 'README.txt')
        if ($part -eq 'web') {
            Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging/StartWeb.cmd') -Destination (Join-Path $folder 'StartWeb.cmd')
        }
        & (Join-Path $PSScriptRoot 'release_manifest.ps1') -Folder $folder -Write -Target $part -ReleaseId $ReleaseId
        Write-Output "Built complete portable folder: $folder"
    }
    $deliveryReadme=Join-Path $releaseRoot 'README.md'
    if (-not (Test-Path -LiteralPath $deliveryReadme)) {
        Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging/DELIVERY_README.md') -Destination $deliveryReadme
    }
} finally { Pop-Location }
