#requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = (Resolve-Path (Join-Path $scriptRoot '..')).Path
$taskName = 'Shutu-Atlas Nightly Auto Index'
$taskMarker = 'Shutu-Atlas Nightly Auto Index'

function Write-UninstallResult {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Message,
        [hashtable]$Fields = @{}
    )
    $payload = [ordered]@{
        status = $Status
        task_name = $taskName
        message = $Message
    }
    foreach ($key in $Fields.Keys) {
        $payload[$key] = $Fields[$key]
    }
    Write-Output ($payload | ConvertTo-Json -Depth 6)
}

try {
    Import-Module ScheduledTasks -ErrorAction Stop
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-UninstallResult -Status 'PASS' -Message 'The Shutu-Atlas task was already absent; no project data was changed.' -Fields @{ project_root = $projectRoot }
        exit 0
    }

    $xmlText = Export-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-String
    if ($xmlText -notmatch [regex]::Escape($taskMarker)) {
        Write-UninstallResult -Status 'BLOCKED_ENV' -Message 'The task name exists but is not identified as Shutu-Atlas-managed; it was not removed.'
        exit 10
    }

    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    $stillThere = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $stillThere) {
        Write-UninstallResult -Status 'FAIL' -Message 'Unregister-ScheduledTask returned but the task is still present.'
        exit 2
    }
    Write-UninstallResult -Status 'PASS' -Message 'Only the Shutu-Atlas-managed task was removed; database, logs, source files, history and user configuration were retained.' -Fields @{ project_root = $projectRoot }
    exit 0
} catch {
    Write-UninstallResult -Status 'BLOCKED_ENV' -Message ("Task Scheduler removal could not be completed: {0}" -f $_.Exception.Message) -Fields @{ error_type = $_.Exception.GetType().Name }
    exit 10
}
