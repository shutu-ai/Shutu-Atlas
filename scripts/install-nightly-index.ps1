#requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = (Resolve-Path (Join-Path $scriptRoot '..')).Path
$scriptPath = (Resolve-Path (Join-Path $scriptRoot 'nightly-index.ps1')).Path
$taskName = 'Shutu-Atlas Nightly Auto Index'
$taskDescription = 'Shutu-Atlas Nightly Auto Index; project-managed, read-only source indexing.'
$taskMarker = 'Shutu-Atlas Nightly Auto Index'
$backupRoot = Join-Path $projectRoot '.local\task-scheduler-backups'
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

function Write-InstallResult {
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
    Write-Output ($payload | ConvertTo-Json -Depth 8)
}

function Get-TaskXmlValue {
    param(
        [Parameter(Mandatory = $true)][System.Xml.XmlDocument]$Document,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $node = $Document.SelectSingleNode("//*[local-name()='$Name']")
    if ($null -eq $node) {
        return $null
    }
    return $node.InnerText
}

if (-not (Test-Path -LiteralPath $scriptPath)) {
    Write-InstallResult -Status 'FAIL' -Message ("Nightly entry script is missing: {0}" -f $scriptPath)
    exit 2
}
if (-not (Test-Path -LiteralPath $windowsPowerShell)) {
    Write-InstallResult -Status 'BLOCKED_ENV' -Message ("Windows PowerShell executable is unavailable: {0}" -f $windowsPowerShell)
    exit 10
}

try {
    Import-Module ScheduledTasks -ErrorAction Stop
} catch {
    Write-InstallResult -Status 'BLOCKED_ENV' -Message 'The Windows ScheduledTasks module is unavailable in this environment.' -Fields @{ error_type = $_.Exception.GetType().Name }
    exit 10
}

try {
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $backupPath = $null
    if ($null -ne $existing) {
        $existingXml = Export-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-String
        if (($existingXml -notmatch [regex]::Escape($taskMarker)) -and ($existingXml -notmatch [regex]::Escape($scriptPath))) {
            Write-InstallResult -Status 'BLOCKED_ENV' -Message 'A task with the project task name exists but is not identified as Shutu-Atlas-managed; it was not overwritten.'
            exit 10
        }
        $backupPath = Join-Path $backupRoot ("{0}-{1}.xml" -f ($taskName -replace '[^A-Za-z0-9_.-]', '_'), (Get-Date).ToString('yyyyMMdd-HHmmss'))
        [System.IO.File]::WriteAllText($backupPath, $existingXml, (New-Object System.Text.UTF8Encoding($false)))
    }

    $trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour 2 -Minute 0 -Second 0)
    $actionArguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $scriptPath
    $action = New-ScheduledTaskAction -Execute $windowsPowerShell -Argument $actionArguments -WorkingDirectory $projectRoot
    $settings = New-ScheduledTaskSettingsSet `
        -RunOnlyIfIdle `
        -IdleDuration (New-TimeSpan -Minutes 10) `
        -IdleWaitTimeout (New-TimeSpan -Hours 1) `
        -MultipleInstances IgnoreNew `
        -Priority 7 `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -DontStopOnIdleEnd
    # No StartWhenAvailable and no WakeToRun: a missed 02:00 run is not
    # replayed during the day and a sleeping/off computer is not woken.
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $taskDescription `
        -Force | Out-Null

    $registered = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $xmlText = Export-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-String
    $xml = New-Object System.Xml.XmlDocument
    $xml.LoadXml($xmlText)
    $verification = [ordered]@{
        task_name = $taskName
        state = [string]$registered.State
        principal_user = [string]$registered.Principal.UserId
        logon_type = [string]$registered.Principal.LogonType
        run_level = [string]$registered.Principal.RunLevel
        start_boundary = Get-TaskXmlValue -Document $xml -Name 'StartBoundary'
        run_only_if_idle = [bool]$registered.Settings.RunOnlyIfIdle
        idle_duration = Get-TaskXmlValue -Document $xml -Name 'Duration'
        idle_wait_timeout = Get-TaskXmlValue -Document $xml -Name 'WaitTimeout'
        stop_on_idle_end = Get-TaskXmlValue -Document $xml -Name 'StopOnIdleEnd'
        multiple_instances = [string]$registered.Settings.MultipleInstances
        priority = [int]$registered.Settings.Priority
        start_when_available = [bool]$registered.Settings.StartWhenAvailable
        wake_to_run = [bool]$registered.Settings.WakeToRun
        command = Get-TaskXmlValue -Document $xml -Name 'Command'
        arguments = Get-TaskXmlValue -Document $xml -Name 'Arguments'
        working_directory = Get-TaskXmlValue -Document $xml -Name 'WorkingDirectory'
    }

    Write-InstallResult -Status 'PASS' -Message 'Task Scheduler registration completed and the live task XML was read back.' -Fields @{
        user = $currentUser
        project_root = $projectRoot
        script = $scriptPath
        backup = $backupPath
        verification = $verification
        policy = '02:00 local; RunOnlyIfIdle; idle 10m; wait up to 1h; IgnoreNew; no StartWhenAvailable; no WakeToRun; InteractiveToken; BelowNormal priority 7'
    }
    exit 0
} catch {
    Write-InstallResult -Status 'BLOCKED_ENV' -Message ("Task Scheduler registration could not be completed without elevation or external changes: {0}" -f $_.Exception.Message) -Fields @{ error_type = $_.Exception.GetType().Name; user = $currentUser }
    exit 10
}
