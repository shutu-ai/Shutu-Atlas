[CmdletBinding()]
param([string]$Python = "py")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
if(Test-Path -LiteralPath ".venv\Scripts\python.exe") { $Py = ".venv\Scripts\python.exe" } else { $Py = $Python }
& $Py -m shutu_atlas.cli doctor

