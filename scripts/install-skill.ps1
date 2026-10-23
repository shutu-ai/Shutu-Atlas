[CmdletBinding()]
param(
  [switch]$Install,
  [switch]$DryRun = $true,
  [string]$Destination = "$env:USERPROFILE\.agents\skills\local-project-reuse\SKILL.md"
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $ProjectRoot "skills\local-project-reuse\SKILL.md"
if(-not (Test-Path -LiteralPath $Source)) { throw "Skill source not found: $Source" }
$destPath = [IO.Path]::GetFullPath($Destination)
Write-Output "Source: $Source"
Write-Output "Destination: $destPath"
if(-not $Install) { Write-Output "DRY-RUN: no user file changed. Re-run with -Install only after explicit confirmation."; exit 0 }
if($DryRun) { throw "-Install requires -DryRun:`$false" }
$parent = Split-Path -Parent $destPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
if(Test-Path -LiteralPath $destPath) {
  $backup = "$destPath.bak-$(Get-Date -Format yyyyMMddHHmmss)"
  Copy-Item -LiteralPath $destPath -Destination $backup
  Write-Output "Backup: $backup"
}
Copy-Item -LiteralPath $Source -Destination $destPath -Force
Write-Output "Installed skill: $destPath"

