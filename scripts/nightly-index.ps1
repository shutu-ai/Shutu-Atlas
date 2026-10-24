#requires -Version 5.1
[CmdletBinding()]
param(
    # This switch is intentionally test/maintenance-only.  The registered
    # Task Scheduler action never passes it, so daytime invocations still
    # fail closed instead of becoming catch-up runs.
    [switch]$IgnoreTimeWindowForTest
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = (Resolve-Path (Join-Path $scriptRoot '..')).Path
$logRoot = Join-Path $projectRoot '.local\logs\nightly-index'
$logDate = Get-Date
$logPath = Join-Path $logRoot ($logDate.ToString('yyyy-MM-dd') + '.jsonl')
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

try {
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
} catch {
    Write-Error ("Unable to create the Nightly Auto Index log directory: {0}" -f $_.Exception.Message)
    exit 3
}

function Write-NightlyLog {
    param(
        [Parameter(Mandatory = $true)][string]$Event,
        [hashtable]$Fields = @{}
    )

    $entry = [ordered]@{
        timestamp = (Get-Date).ToString('o')
        event = $Event
    }
    foreach ($key in $Fields.Keys) {
        $entry[$key] = $Fields[$key]
    }
    try {
        [System.IO.File]::AppendAllText($logPath, (($entry | ConvertTo-Json -Compress -Depth 6) + [Environment]::NewLine), $utf8NoBom)
    } catch {
        Write-Warning ("Unable to append Nightly Auto Index log: {0}" -f $_.Exception.Message)
    }
}

# Rotate only this task's own daily JSONL files.  Failure to remove an old
# file is recorded but never deletes another .local artifact.
try {
    $cutoff = $logDate.AddDays(-30)
    Get-ChildItem -LiteralPath $logRoot -Filter '*.jsonl' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            $oldLogFile = $_
            try {
                Remove-Item -LiteralPath $oldLogFile.FullName -Force -ErrorAction Stop
            } catch {
                Write-NightlyLog -Event 'rotation_failed' -Fields @{ file = $oldLogFile.Name; error_type = $_.Exception.GetType().Name }
            }
        }
} catch {
    Write-NightlyLog -Event 'rotation_failed' -Fields @{ error_type = $_.Exception.GetType().Name }
}

$pythonPath = Join-Path $projectRoot '.local\integration-venv\Scripts\python.exe'
$configPath = Join-Path $projectRoot 'atlas.toml'
$sourcePath = Join-Path $projectRoot 'src'
$commandSummary = 'python -m shutu_atlas.cli --config atlas.toml index --changed-only --resume'
$windowStart = [TimeSpan]::FromHours(2)
$windowEnd = [TimeSpan]::FromHours(4)
$runStarted = Get-Date

Write-NightlyLog -Event 'start' -Fields @{
    project_root = $projectRoot
    python = $pythonPath
    config = $configPath
    pythonpath = $sourcePath
    command = $commandSummary
    time_window = '02:00-04:00 local time'
    test_time_window_bypass = [bool]$IgnoreTimeWindowForTest
}

if (-not $IgnoreTimeWindowForTest -and (($runStarted.TimeOfDay -lt $windowStart) -or ($runStarted.TimeOfDay -ge $windowEnd))) {
    Write-NightlyLog -Event 'skip' -Fields @{
        status = 'SKIPPED_TIME_WINDOW'
        skip_reason = 'entry started outside the 02:00-04:00 local start window'
        exit_code = 0
    }
    Write-Output ([ordered]@{
        status = 'SKIPPED_TIME_WINDOW'
        skip_reason = 'outside 02:00-04:00 local start window'
        log = $logPath
        exit_code = 0
    } | ConvertTo-Json -Depth 5)
    exit 0
}

foreach ($requiredPath in @($pythonPath, $configPath, $sourcePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        $missing = Split-Path -Leaf $requiredPath
        Write-NightlyLog -Event 'failure' -Fields @{
            status = 'FAILED_ENV'
            error_type = 'RequiredPathMissing'
            missing = $missing
            exit_code = 3
        }
        Write-Error ("Nightly Auto Index prerequisite is missing: {0}. Repair the project-local integration-venv/configuration; no global Python fallback is used." -f $requiredPath)
        exit 3
    }
}

$priorityMode = 'BelowNormal'
try {
    $currentProcess = [System.Diagnostics.Process]::GetCurrentProcess()
    try {
        $currentProcess.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
    } finally {
        $currentProcess.Dispose()
    }
} catch {
    $priorityMode = 'normal-fallback'
    Write-NightlyLog -Event 'priority_fallback' -Fields @{
        requested_priority = 'BelowNormal'
        error_type = $_.Exception.GetType().Name
    }
}

$oldPythonPath = $env:PYTHONPATH
$exitCode = 1
$output = @()
$outputParse = 'not_attempted'
$payload = $null
try {
    $env:PYTHONPATH = $sourcePath
    Push-Location -LiteralPath $projectRoot
    try {
        $output = @(& $pythonPath -m shutu_atlas.cli --config $configPath index --changed-only --resume 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
        if ($null -eq $oldPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONPATH = $oldPythonPath
        }
    }
} catch {
    Write-NightlyLog -Event 'failure' -Fields @{
        status = 'FAILED_EXECUTION'
        error_type = $_.Exception.GetType().Name
        exit_code = 1
    }
    Write-Error ("Nightly Auto Index failed before the CLI completed: {0}" -f $_.Exception.Message)
    exit 1
}

$outputText = (($output | ForEach-Object { [string]$_ }) -join "`n").Trim()
if ($outputText) {
    try {
        $payload = $outputText | ConvertFrom-Json
        $outputParse = 'ok'
    } catch {
        $outputParse = 'failed'
    }
}

$runStatus = $null
if ($null -ne $payload -and $payload.PSObject.Properties.Name -contains 'status') {
    $runStatus = [string]$payload.status
}
$resultStatus = 'FAILED'
$effectiveExitCode = if ($null -eq $exitCode) { 1 } else { [int]$exitCode }
if ($runStatus -eq 'skipped_running' -and $effectiveExitCode -eq 0) {
    $resultStatus = 'SKIPPED_RUNNING'
} elseif ($runStatus -eq 'ok' -and $effectiveExitCode -eq 0) {
    $resultStatus = 'SUCCESS'
}

$getPayloadValue = {
    param([string]$Name, $Fallback = $null)
    if ($null -ne $payload -and $payload.PSObject.Properties.Name -contains $Name) {
        return $payload.$Name
    }
    return $Fallback
}
$durationSeconds = [Math]::Round(((Get-Date) - $runStarted).TotalSeconds, 3)
$fields = @{
    status = $resultStatus
    cli_status = $runStatus
    exit_code = $effectiveExitCode
    duration_seconds = $durationSeconds
    priority = $priorityMode
    output_parse = $outputParse
    run_id = & $getPayloadValue 'run_id'
    projects_total = & $getPayloadValue 'projects_total' 0
    projects_completed = & $getPayloadValue 'projects_completed' 0
    files_indexed = & $getPayloadValue 'files_indexed' 0
    files_scanned = & $getPayloadValue 'files_scanned' 0
    changed_files = & $getPayloadValue 'changed_files' 0
    unchanged_files = & $getPayloadValue 'unchanged_files' 0
    errors = & $getPayloadValue 'errors' 0
    skip_reason = & $getPayloadValue 'skip_reason'
}
Write-NightlyLog -Event 'finish' -Fields $fields

$summary = [ordered]@{
    status = $resultStatus
    cli_status = $runStatus
    run_id = $fields.run_id
    projects_total = $fields.projects_total
    projects_completed = $fields.projects_completed
    files_indexed = $fields.files_indexed
    files_scanned = $fields.files_scanned
    changed_files = $fields.changed_files
    unchanged_files = $fields.unchanged_files
    errors = $fields.errors
    duration_seconds = $durationSeconds
    priority = $priorityMode
    exit_code = $effectiveExitCode
    log = $logPath
}
Write-Output ($summary | ConvertTo-Json -Depth 5)
exit $effectiveExitCode
