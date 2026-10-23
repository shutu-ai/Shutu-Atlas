[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$Python = "py",
  [switch]$SkipVenv
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
if(-not $SkipVenv) {
  if(-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) { & $Python -m venv .venv }
  $Py = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
} else { $Py = $Python }
& $Py -m pip install --disable-pip-version-check -e .
if(-not (Test-Path -LiteralPath "atlas.toml")) { Copy-Item -LiteralPath "atlas.example.toml" -Destination "atlas.toml" }
Write-Output "Installed Shutu-Atlas v0.2.0. Review atlas.toml, then run: atlas doctor"

