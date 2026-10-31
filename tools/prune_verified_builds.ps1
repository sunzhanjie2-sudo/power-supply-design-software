#requires -Version 5.1
<# Post-verification cleanup. Preview first; removes only exact generated paths.
   Never includes release folders, source, original reference files or user data. #>
[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference='Stop'
$workspaceRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$audit=Join-Path $workspaceRoot 'artifacts/releases/20261023'
$targets=@('artifacts/build/20261023','archive/organization-20261023/studio-build-intermediates',
    '__pycache__','tests/__pycache__','design_engine/__pycache__','web_app/__pycache__',
    'packaging/__pycache__','related_projects/semiconductor-datasheet-studio/__pycache__',
    'related_projects/semiconductor-datasheet-studio/studio/__pycache__',
    'related_projects/semiconductor-datasheet-studio/tests/__pycache__')
$entries=@()
foreach ($relative in $targets) {
    $path=[IO.Path]::GetFullPath((Join-Path $workspaceRoot $relative))
    if (-not $path.StartsWith($workspaceRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe: $path" }
    if (-not (Test-Path -LiteralPath $path)) { continue }
    if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing link: $path" }
    if (@(Get-ChildItem -LiteralPath $path -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Nested link: $path" }
    $tracked=@(& git -C $workspaceRoot ls-files -- $relative)
    if ($LASTEXITCODE -ne 0 -or $tracked.Count) { throw "Tracked files in generated target: $relative" }
    $files=@(Get-ChildItem -LiteralPath $path -Recurse -File -Force)
    $entries += [ordered]@{path=$path;files=$files.Count;bytes=[long](($files|Measure-Object Length -Sum).Sum);action='delete-generated'}
}
$entries | ForEach-Object { [pscustomobject]$_ } | Format-Table -AutoSize
if (-not $Apply) { Write-Output 'Preview only. After verifying release packages, use -Apply.';return }
$receipt=Join-Path $workspaceRoot 'archive/organization-20261023/generated-cleanup-final.json'
if (Test-Path -LiteralPath $receipt) { throw 'Already applied; inspect existing receipt.' }
New-Item -ItemType Directory -Path $audit -Force | Out-Null
foreach ($relative in @('artifacts/build/20261023/web/web/warn-web.txt','artifacts/build/20261023/desktop/desktop/warn-desktop.txt')) {
    $path=Join-Path $workspaceRoot $relative
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination (Join-Path $audit (Split-Path $path -Leaf)) }
}
[ordered]@{schema='power-design.generated-cleanup.v1';created=(Get-Date -Format o);entries=$entries} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receipt -Encoding UTF8
foreach ($entry in $entries) { Remove-Item -LiteralPath $entry.path -Recurse -Force }
# Remove only demonstrably empty scaffolding, never recursively.
foreach ($relative in @('dist','related_projects/semiconductor-datasheet-studio/dist/_release_02','related_projects/semiconductor-datasheet-studio/dist')) {
    $path=[IO.Path]::GetFullPath((Join-Path $workspaceRoot $relative))
    if ($path.StartsWith($workspaceRoot+'\') -and (Test-Path -LiteralPath $path) -and -not @(Get-ChildItem -LiteralPath $path -Force).Count) { Remove-Item -LiteralPath $path }
}
Write-Output 'Generated builds/caches removed; complete releases and audit warnings retained.'
