#requires -Version 5.1
[CmdletBinding()]
param([string]$ReleaseId='20261023')
$ErrorActionPreference='Stop'
if ($ReleaseId -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid release ID.' }
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$versionFolder=Join-Path $projectRoot ('releases/Windows-x64/'+$ReleaseId)
$zipFolder=Join-Path $versionFolder 'packages'
Add-Type -AssemblyName System.IO.Compression.FileSystem
foreach ($name in @('PowerDesignDesktop','PowerDesignWeb','SemiconductorDatasheetStudio-0.2')) {
    $folder=Join-Path $versionFolder $name
    if (-not (Test-Path -LiteralPath $folder)) { continue }
    & (Join-Path $PSScriptRoot 'release_manifest.ps1') -Folder $folder
    if (Test-Path -LiteralPath (Join-Path $folder 'data')) { throw "Refusing user data in distribution: $folder" }
    $zipPath=Join-Path $zipFolder ($name+'-'+$ReleaseId+'-Windows-x64.zip')
    if (Test-Path -LiteralPath $zipPath) { throw "ZIP exists; will not overwrite: $zipPath" }
    New-Item -ItemType Directory -Path $zipFolder -Force | Out-Null
    [IO.Compression.ZipFile]::CreateFromDirectory($folder,$zipPath,[IO.Compression.CompressionLevel]::Optimal,$true)
    (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash | Set-Content -LiteralPath ($zipPath+'.sha256') -Encoding ASCII
    [pscustomobject]@{ZIP=$zipPath;MiB=[math]::Round((Get-Item -LiteralPath $zipPath).Length/1MB,2)}
}
