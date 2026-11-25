# Windows Task Scheduler staging only. No automatic crawling or database writes.
# Default is read-only Plan; explicit RegisterDisabled creates a disabled task.
[CmdletBinding()]
param(
    [ValidateSet('Plan','RegisterDisabled','Status','Health','ManualQA','RunScheduled')]
    [string]$Action = 'Plan'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$TaskName = 'SVReviewMaster-Daily-0800-STAGING'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$DataRoot = Join-Path $env:LOCALAPPDATA 'SVReviewMaster'
$StateFile = Join-Path $DataRoot 'scheduler-staging-state.json'
$Profile = Join-Path $DataRoot 'GoogleMapsSortProfile'
$Zone = 'Korea Standard Time'
$PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Batch = Join-Path $PSScriptRoot 'local_review_batch.py'
$Probe = Join-Path $PSScriptRoot 'local_review_profile_probe.py'

function Write-State([hashtable]$State) {
    New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
    $State['recorded_at_utc'] = [DateTime]::UtcNow.ToString('o')
    $State['production_ready'] = $false
    $State['database_writes'] = $false
    $tmp = Join-Path $DataRoot ('scheduler-state-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $State | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $tmp -Encoding UTF8
        Move-Item -LiteralPath $tmp -Destination $StateFile -Force
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
}
function Escape-Xml([string]$Value) {
    return [System.Security.SecurityElement]::Escape($Value)
}
function New-DisabledTaskXml {
    # Explicit timezone check prevents a local 08:00 trigger being mistaken for KST.
    if ((Get-TimeZone).Id -ne $Zone) { throw 'WINDOWS_TIMEZONE_NOT_KST' }
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $start = (Get-Date).Date.AddDays(1).AddHours(8).ToString('yyyy-MM-ddTHH:mm:ss')
    $command = Escape-Xml $PowerShell
    $arguments = Escape-Xml ('-NoLogo -NoProfile -NonInteractive -File "' + $PSCommandPath + '" -Action RunScheduled')
    $working = Escape-Xml $RepoRoot
    return @"
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>SV Review Master staging only; production execution blocked pending final manual QA.</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$start</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Owner">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>false</Enabled>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Owner">
    <Exec><Command>$command</Command><Arguments>$arguments</Arguments><WorkingDirectory>$working</WorkingDirectory></Exec>
  </Actions>
</Task>
"@
}

switch ($Action) {
    'Plan' {
        [ordered]@{
            task_name = $TaskName
            schedule = '08:00 KST daily'
            windows_timezone_is_kst = ((Get-TimeZone).Id -eq $Zone)
            interactive_user_required = $true
            start_when_available = $true
            wake_computer = $false
            multiple_instances = 'IgnoreNew'
            registration_enabled = $false
            scheduled_execution_allowed = $false
            production_ready = $false
            final_manual_production_qa_required = $true
            database_writes = $false
        } | ConvertTo-Json
        exit 0
    }
    'RegisterDisabled' {
        if (Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction SilentlyContinue) {
            throw 'STAGING_TASK_ALREADY_EXISTS_NO_OVERWRITE'
        }
        $xml = New-DisabledTaskXml
        Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Xml $xml | Out-Null
        $task = Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
        if ($task.Settings.Enabled -or $task.State -ne 'Disabled') {
            Disable-ScheduledTask -TaskName $TaskName -TaskPath '\' | Out-Null
            throw 'DISABLED_STATE_NOT_VERIFIED'
        }
        Write-Output 'STAGING_TASK_REGISTERED_DISABLED'
        exit 0
    }
    'Status' {
        $task = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction SilentlyContinue
        $status = [ordered]@{
            registered = ($null -ne $task)
            enabled = $false
            state = 'NotRegistered'
            production_ready = $false
            scheduled_execution_allowed = $false
        }
        if ($null -ne $task) {
            $status['enabled'] = [bool]$task.Settings.Enabled
            $status['state'] = [string]$task.State
            $info = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath '\'
            $status['last_task_result'] = $info.LastTaskResult
            $status['missed_runs'] = $info.NumberOfMissedRuns
            $status['next_run_local'] = $info.NextRunTime.ToString('o')
        }
        if (Test-Path -LiteralPath $StateFile) {
            $status['latest_staging_result'] = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        }
        $status | ConvertTo-Json -Depth 6
        exit 0
    }
    'Health' {
        $python = (Get-Command python.exe -CommandType Application).Source
        & $python (Join-Path $PSScriptRoot 'local_review_health.py')
        exit $LASTEXITCODE
    }
    'ManualQA' {
        # Offline self-tests followed by a bounded two-store adapter sample.
        # This is not the final all-store or production-write acceptance test.
        $python = (Get-Command python.exe -CommandType Application).Source
        $started = [DateTime]::UtcNow.ToString('o')
        $stage = 'offline_probe_tests'
        $code = 2
        try {
            & $python $Probe --self-test
            if ($LASTEXITCODE -ne 0) { throw 'PROBE_SELF_TEST_FAILED' }
            $stage = 'offline_batch_tests'
            & $python $Batch --self-test
            if ($LASTEXITCODE -ne 0) { throw 'BATCH_SELF_TEST_FAILED' }
            $stage = 'offline_health_tests'
            & $python (Join-Path $PSScriptRoot 'local_review_health.py') --self-test
            if ($LASTEXITCODE -ne 0) { throw 'HEALTH_SELF_TEST_FAILED' }
            $stage = 'offline_audit_invariants_tests'
            & $python (Join-Path $PSScriptRoot 'review_audit_invariants.py')
            if ($LASTEXITCODE -ne 0) { throw 'AUDIT_INVARIANTS_SELF_TEST_FAILED' }
            $stage = 'offline_append_preflight_tests'
            & $python (Join-Path $PSScriptRoot 'review_append_preflight.py')
            if ($LASTEXITCODE -ne 0) { throw 'APPEND_PREFLIGHT_SELF_TEST_FAILED' }
            $stage = 'offline_append_snapshot_tests'
            & $python (Join-Path $PSScriptRoot 'review_append_snapshot.py')
            if ($LASTEXITCODE -ne 0) { throw 'APPEND_SNAPSHOT_SELF_TEST_FAILED' }
            $stage = 'offline_append_execution_tests'
            & $python (Join-Path $PSScriptRoot 'review_append_execution_qa.py')
            if ($LASTEXITCODE -ne 0) { throw 'APPEND_EXECUTION_SELF_TEST_FAILED' }
            $stage = 'known_store_adapter_samples'
            & $python $Batch --scope known --mode adapter
            $code = $LASTEXITCODE
            if ($code -ne 0) { throw 'ADAPTER_BATCH_NOT_PASSED' }
            $stage = 'staging_sample_passed'
            exit 0
        } catch {
            $code = 2
            Write-Output ('MANUAL_QA_NOT_PASSED: ' + $stage)
            exit 2
        } finally {
            Write-State @{
                action = 'ManualQA'
                stage = $stage
                started_at_utc = $started
                exit_code = $code
                final_production_qa_passed = $false
            }
        }
    }
    'RunScheduled' {
        # Deliberate hard gate even if the task is accidentally enabled.
        # A passing sample never removes this gate or authorizes writes.
        Write-State @{
            action = 'RunScheduled'
            stage = 'BLOCKED_PENDING_FINAL_MANUAL_PRODUCTION_QA'
            exit_code = 3
            final_production_qa_passed = $false
        }
        Write-Output 'SCHEDULED_EXECUTION_BLOCKED_PENDING_FINAL_MANUAL_QA'
        exit 3
    }
}
