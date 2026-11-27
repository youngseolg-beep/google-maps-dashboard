# Windows Task Scheduler staging only. No automatic crawling or database writes.
# Default is read-only Plan; explicit RegisterDisabled creates a disabled task.
[CmdletBinding()]
param(
    [ValidateSet('Plan','RegisterDisabled','Status','Health','ManualQA','RunScheduled','AppendPlan','PrepareAppend','ProtectAppendCredential','RegisterAppendDisabled','RunAppend')]
    [string]$Action = 'Plan',
    [string]$TargetUrl,
    [string]$PythonPath
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


# Append automation reuses the existing profile, batch lock and source journal.
# Credential XML uses current-user Windows DPAPI, never a portable cookie/key file.
$AppendRoot = Join-Path $DataRoot 'append-automation'
$AppendConfig = Join-Path $AppendRoot 'settings.json'
$AppendCredential = Join-Path $AppendRoot 'backend.credential.xml'
$AppendTaskName = 'SVReviewMaster-Daily-2200-APPEND'
function Protect-AppendDirectory {
    New-Item -ItemType Directory -Path $AppendRoot -Force | Out-Null
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($identity in @($sid,[System.Security.Principal.SecurityIdentifier]'S-1-5-18')) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $AppendRoot -AclObject $acl
}
function Read-AppendConfig {
    $config = Get-Content -LiteralPath $AppendConfig -Raw | ConvertFrom-Json
    if ($config.target_url -notmatch '^https://[a-z0-9]+\.supabase\.co$') { throw 'APPEND_TARGET_INVALID' }
    if (-not (Test-Path -LiteralPath $config.python)) { throw 'APPEND_PYTHON_MISSING' }
    if ($config.repository -ne $RepoRoot) { throw 'APPEND_REPOSITORY_CHANGED_REAPPROVAL_REQUIRED' }
    return $config
}
function New-AppendTaskXml {
    if ((Get-TimeZone).Id -ne $Zone) { throw 'WINDOWS_TIMEZONE_NOT_KST' }
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $start = (Get-Date).Date.AddHours(22)
    if ($start -le (Get-Date)) { $start = $start.AddDays(1) }
    $start = $start.ToString('yyyy-MM-ddTHH:mm:ss')
    $command = Escape-Xml $PowerShell
    $arguments = Escape-Xml ('-NoLogo -NoProfile -NonInteractive -File "' + $PSCommandPath + '" -Action RunAppend')
    $working = Escape-Xml $RepoRoot
    return @"
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
 <RegistrationInfo><Description>SV REVIEW MASTER append-only recent collector; disabled pending approval and legacy-writer cutover.</Description></RegistrationInfo>
 <Triggers><CalendarTrigger><StartBoundary>$start</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
 <Principals><Principal id="Owner"><UserId>$sid</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
 <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>false</Enabled><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT4H</ExecutionTimeLimit></Settings>
 <Actions Context="Owner"><Exec><Command>$command</Command><Arguments>$arguments</Arguments><WorkingDirectory>$working</WorkingDirectory></Exec></Actions>
</Task>
"@
}

switch ($Action) {

    'AppendPlan' {
        [ordered]@{ task_name=$AppendTaskName; schedule='22:00 KST daily'; enabled=$false
            interactive_user_required=$true; protected_config_present=(Test-Path $AppendConfig)
            dpapi_credential_present=(Test-Path $AppendCredential); database_writes=$false
            journal=(Join-Path $DataRoot 'review-source-requests.sqlite3')
            activation_requires_approval_and_legacy_cutover=$true } | ConvertTo-Json
        exit 0
    }
    'PrepareAppend' {
        if (Test-Path $AppendConfig) { throw 'APPEND_CONFIG_ALREADY_EXISTS_NO_OVERWRITE' }
        if ($TargetUrl -notmatch '^https://[a-z0-9]+\.supabase\.co$') { throw 'APPEND_TARGET_REQUIRED' }
        if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -CommandType Application).Source }
        if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'APPEND_PYTHON_MISSING' }
        Protect-AppendDirectory
        @{target_url=$TargetUrl;python=$PythonPath;repository=$RepoRoot;approved=$false;legacy_writer_disabled_confirmed=$false} |
            ConvertTo-Json | Set-Content -LiteralPath $AppendConfig -Encoding UTF8
        Write-Output 'APPEND_CONFIG_PREPARED_NOT_APPROVED'
        exit 0
    }
    'ProtectAppendCredential' {
        $config = Read-AppendConfig
        if (Test-Path $AppendCredential) { throw 'APPEND_CREDENTIAL_ALREADY_EXISTS_NO_OVERWRITE' }
        Protect-AppendDirectory
        $secure = Read-Host 'Supabase backend key (hidden; saved with current-user DPAPI)' -AsSecureString
        if ($secure.Length -eq 0) { throw 'APPEND_CREDENTIAL_EMPTY' }
        $credential = New-Object System.Management.Automation.PSCredential($config.target_url,$secure)
        $credential | Export-Clixml -LiteralPath $AppendCredential
        Write-Output 'APPEND_CREDENTIAL_PROTECTED_CURRENT_USER_ONLY'
        exit 0
    }
    'RegisterAppendDisabled' {
        $null = Read-AppendConfig
        if (Get-ScheduledTask -TaskName $AppendTaskName -TaskPath '\' -ErrorAction SilentlyContinue) {
            throw 'APPEND_TASK_ALREADY_EXISTS_NO_OVERWRITE'
        }
        Register-ScheduledTask -TaskName $AppendTaskName -TaskPath '\' -Xml (New-AppendTaskXml) | Out-Null
        $task = Get-ScheduledTask -TaskName $AppendTaskName -TaskPath '\'
        if ($task.Settings.Enabled -or $task.State -ne 'Disabled') {
            Disable-ScheduledTask -TaskName $AppendTaskName -TaskPath '\' | Out-Null
            throw 'APPEND_DISABLED_STATE_NOT_VERIFIED'
        }
        Write-Output 'APPEND_TASK_REGISTERED_DISABLED'
        exit 0
    }
    'RunAppend' {
        $config = Read-AppendConfig
        if ($config.approved -ne $true -or $config.legacy_writer_disabled_confirmed -ne $true) {
            Write-Output 'APPEND_BLOCKED_PENDING_APPROVAL_AND_LEGACY_CUTOVER'
            exit 3
        }
        if ((Get-TimeZone).Id -ne $Zone) { throw 'WINDOWS_TIMEZONE_NOT_KST' }
        $credential = Import-Clixml -LiteralPath $AppendCredential
        if ($credential.UserName -ne $config.target_url) { throw 'APPEND_CREDENTIAL_TARGET_MISMATCH' }
        $previous = @{}
        foreach ($name in @('SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY','SV_REVIEW_PILOT_EXCLUSIVE','PYTHONUTF8','PYTHONIOENCODING')) {
            $previous[$name] = [Environment]::GetEnvironmentVariable($name,'Process')
        }
        $code = 2
        $log = Join-Path $AppendRoot ('append-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff') + '.log')
        try {
            $env:SUPABASE_URL = $config.target_url
            $env:SUPABASE_SERVICE_ROLE_KEY = $credential.GetNetworkCredential().Password
            $env:SV_REVIEW_PILOT_EXCLUSIVE = '1'
            $env:PYTHONUTF8 = '1'
            $env:PYTHONIOENCODING = 'utf-8'
            Push-Location $RepoRoot
            try {
                & $config.python -B (Join-Path $PSScriptRoot 'local_review_append_batch.py') --target-url $config.target_url --mode recent --commit *> $log
                $code = $LASTEXITCODE
            } finally { Pop-Location }
        } finally {
            foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name,$previous[$name],'Process') }
            @{exit_code=$code;finished_at_utc=[DateTime]::UtcNow.ToString('o');log=$log} |
                ConvertTo-Json | Set-Content -LiteralPath (Join-Path $AppendRoot 'last-result.json') -Encoding UTF8
            $credential = $null
        }
        exit $code
    }

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
        $stage = 'offline_qa_suite'
        $code = 2
        try {
            & $python (Join-Path $PSScriptRoot 'local_review_offline_qa.py')
            if ($LASTEXITCODE -ne 0) { throw 'OFFLINE_QA_FAILED' }
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
