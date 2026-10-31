#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Folder,
      [switch]$Write, [string]$Target='manual', [string]$ReleaseId='20261023')
$ErrorActionPreference='Stop'
$releaseRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../releases'))
$bundle=(Resolve-Path -LiteralPath $Folder).Path
if (-not $bundle.StartsWith($releaseRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Only a project release child is accepted.' }
$manifestPath=Join-Path $bundle 'manifest.json'
if ($Write) {
    $files=@(Get-ChildItem -LiteralPath $bundle -Recurse -File -Force | Where-Object FullName -ne $manifestPath | ForEach-Object {
        [ordered]@{path=$_.FullName.Substring($bundle.Length+1);bytes=$_.Length;sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash}
    })
    [ordered]@{schema='power-design.release.v1';id=$ReleaseId;target=$Target;created=(Get-Date -Format o);
        architecture='Windows-x64';files=$files} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
}
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$total=0L
foreach ($entry in $manifest.files) {
    $path=[IO.Path]::GetFullPath((Join-Path $bundle $entry.path))
    if (-not $path.StartsWith($bundle+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path escapes bundle.' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing: $($entry.path)" }
    if ((Get-Item -LiteralPath $path).Length -ne $entry.bytes -or (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash -ne $entry.sha256) { throw "Hash mismatch: $($entry.path)" }
    $total += $entry.bytes
}
[pscustomobject]@{Bundle=$bundle;Files=$manifest.files.Count;MiB=[math]::Round($total/1MB,2);Verified=$true}
