<#
Recoverable cleanup of generated, untracked artifacts only.
Default: preview. -Apply moves targets into the project archive; never deletes them.
Source, release packages, reports, documents and nested projects are excluded.
#>
[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$archiveParent = Join-Path $projectPath 'archive'
$archivePath = Join-Path $archiveParent ('cleanup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$candidates = @(Get-ChildItem -LiteralPath $projectPath -Force | Where-Object {
    $_.Name.StartsWith('_tmp') -or $_.Name -in @('build', '__pycache__')
})
foreach ($cacheRelative in @('tests\__pycache__', 'design_engine\__pycache__')) {
    $cachePath = Join-Path $projectPath $cacheRelative
    if (Test-Path -LiteralPath $cachePath) { $candidates += Get-Item -LiteralPath $cachePath }
}
$entries = @()
foreach ($item in $candidates) {
    $sourcePath = (Resolve-Path -LiteralPath $item.FullName).Path
    if (-not $sourcePath.StartsWith($projectPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target escapes project: $sourcePath"
    }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing reparse-point target: $sourcePath"
    }
    $relativePath = $sourcePath.Substring($projectPath.Length + 1)
    $tracked = @(& git -C $projectPath ls-files -- $relativePath)
    if ($LASTEXITCODE -ne 0 -or $tracked.Count) { throw "Target contains tracked files: $relativePath" }
    $files = if ($item.PSIsContainer) { @(Get-ChildItem -LiteralPath $sourcePath -Recurse -File -Force) } else { @($item) }
    $destination = [IO.Path]::GetFullPath((Join-Path $archivePath $relativePath))
    if (-not $destination.StartsWith($archivePath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Archive target escapes archive: $destination"
    }
    $entries += [pscustomobject]@{
        relative_path=$relativePath; source=$sourcePath; archive=$destination
        files=$files.Count; bytes=[long](($files | Measure-Object Length -Sum).Sum)
    }
}
$entries | Select-Object relative_path,files,@{Name='MiB';Expression={[math]::Round($_.bytes/1MB,2)}} | Format-Table -AutoSize
if (-not $Apply) { Write-Output 'Preview only. Use -Apply to archive these exact targets.'; return }
if (Test-Path -LiteralPath $archivePath) { throw "Archive already exists: $archivePath" }
New-Item -ItemType Directory -Path $archivePath | Out-Null
$manifest = [ordered]@{schema='power-design.cleanup.v1'; created=(Get-Date -Format o); project=$projectPath; entries=$entries}
# Operational manifest, written before moving anything so interrupted work is recoverable.
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $archivePath 'manifest.json') -Encoding UTF8
foreach ($entry in $entries) {
    $destinationParent = Split-Path $entry.archive -Parent
    if (-not (Test-Path -LiteralPath $destinationParent)) { New-Item -ItemType Directory -Path $destinationParent | Out-Null }
    Move-Item -LiteralPath $entry.source -Destination $entry.archive
}
Write-Output "Archived $($entries.Count) targets to $archivePath (recoverable; no files deleted)."
