[CmdletBinding()]
param(
    [string]$ApiBaseUrl = "http://127.0.0.1:17890",
    [string]$AppExePath = (Join-Path $env:LOCALAPPDATA "Kuractus\kuractus-desktop.exe"),
    [string]$ArtifactZip,
    [string]$ExpectedArtifactSha256,
    [string]$BackupPath,
    [string]$OutputDirectory = (Join-Path $env:TEMP "kuractus-desktop-dogfood")
)

$ErrorActionPreference = "Stop"
$startedAt = Get-Date
$stamp = $startedAt.ToString("yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$logPath = Join-Path $OutputDirectory "snapshot-$stamp.log"
$jsonPath = Join-Path $OutputDirectory "snapshot-$stamp.json"
$lines = [System.Collections.Generic.List[string]]::new()
$snapshotChecks = [System.Collections.Generic.List[object]]::new()
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Evidence,
        [string]$Blocker = ""
    )
    $checks.Add([pscustomobject]@{
        name = $Name
        status = $Status
        evidence = $Evidence
        blocker = $Blocker
    })
    $suffix = if ($Blocker) { " blocker=$Blocker" } else { "" }
    $lines.Add("[$Status] $Name :: $Evidence$suffix")
}

function Add-ReadOnlySnapshot {
    param([string]$Name, [string]$Status, [string]$Evidence)
    $snapshotChecks.Add([pscustomobject]@{
        name = $Name
        status = $Status
        evidence = $Evidence
    })
    $lines.Add("[$Status] $Name :: $Evidence")
}

$appFile = $null
$appVersion = $null
if (Test-Path -LiteralPath $AppExePath -PathType Leaf) {
    $appFile = Get-Item -LiteralPath $AppExePath
    $appVersion = $appFile.VersionInfo.ProductVersion
    Add-ReadOnlySnapshot "installed_app" "PASS" "Kuractus executable exists; productVersion=$appVersion"
} else {
    Add-ReadOnlySnapshot "installed_app" "FAIL" "Kuractus executable not found at the configured per-user install path"
}

$appProcesses = @()
try {
    $appProcesses = @(Get-Process -Name "aura-desktop", "kuractus-desktop" -ErrorAction SilentlyContinue | ForEach-Object {
        [pscustomobject]@{ processId = $_.Id; processName = $_.ProcessName }
    })
    $processEvidence = if ($appProcesses.Count) {
        "running process IDs=$(@($appProcesses | ForEach-Object processId) -join ',')"
    } else {
        "no Kuractus desktop process is running"
    }
    Add-ReadOnlySnapshot "app_process" $(if ($appProcesses.Count) { "PASS" } else { "NOT TESTED" }) $processEvidence
} catch {
    Add-ReadOnlySnapshot "app_process" "UNAVAILABLE" "process metadata could not be read: $($_.Exception.GetType().Name)"
}

$apiReady = $false
$apiEvidence = ""
try {
    $health = Invoke-RestMethod -Uri "$($ApiBaseUrl.TrimEnd('/'))/ready" -TimeoutSec 5
    $database = [string]$health.checks.database
    $checkpointer = [string]$health.checks.checkpointer
    $apiReady = ($health.status -eq "ready" -and $database -eq "healthy" -and $checkpointer -eq "healthy")
    $apiEvidence = "status=$($health.status); database=$database; checkpointer=$checkpointer"
    Add-ReadOnlySnapshot "api_ready" $(if ($apiReady) { "PASS" } else { "FAIL" }) $apiEvidence
} catch {
    $apiEvidence = "request failed: $($_.Exception.GetType().Name)"
    Add-ReadOnlySnapshot "api_ready" "FAIL" $apiEvidence
}

$dockerAvailable = $false
$containerLines = @()
try {
    $dockerCommand = Get-Command docker -ErrorAction Stop
    $containerLines = @(& $dockerCommand.Source ps -a --filter "name=aura-desktop-postgres-1" --format "{{.Names}}|{{.Status}}|{{.Ports}}" 2>&1)
    $dockerExitCode = $LASTEXITCODE
    if ($dockerExitCode -eq 0) {
        $dockerAvailable = $true
        $containerEvidence = if ($containerLines.Count) { $containerLines -join "; " } else { "Docker CLI reachable; Kuractus PostgreSQL container is not running (legacy container ID retained)" }
        Add-ReadOnlySnapshot "kuractus_postgres_container" $(if ($containerLines.Count -and ($containerLines -join " ") -match "healthy") { "PASS" } elseif ($containerLines.Count) { "FAIL" } else { "FAIL" }) $containerEvidence
    } else {
        Add-ReadOnlySnapshot "kuractus_postgres_container" "UNAVAILABLE" "Docker CLI returned exit code $dockerExitCode"
    }
} catch {
    Add-ReadOnlySnapshot "kuractus_postgres_container" "UNAVAILABLE" "Docker CLI or engine could not be queried: $($_.Exception.GetType().Name)"
}

$listeners = @()
$listenerQueryAvailable = $false
try {
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in @(17890, 15432) } | ForEach-Object {
        [pscustomobject]@{ localAddress = $_.LocalAddress; localPort = $_.LocalPort; processId = $_.OwningProcess }
    })
    $listenerQueryAvailable = $true
    $listenerEvidence = if ($listeners.Count) {
        ($listeners | ForEach-Object { "$($_.localAddress):$($_.localPort)/pid=$($_.processId)" }) -join "; "
    } else {
        "no Kuractus runtime listeners on ports 17890 or 15432"
    }
    Add-ReadOnlySnapshot "kuractus_port_listeners" "PASS" $listenerEvidence
} catch {
    Add-ReadOnlySnapshot "kuractus_port_listeners" "UNAVAILABLE" "listener metadata could not be read: $($_.Exception.GetType().Name)"
}

if ($ArtifactZip) {
    try {
        $artifactHash = (Get-FileHash -LiteralPath $ArtifactZip -Algorithm SHA256).Hash
        $hashMatches = -not $ExpectedArtifactSha256 -or $artifactHash.Equals($ExpectedArtifactSha256.Replace(" ", ""), [StringComparison]::OrdinalIgnoreCase)
        Add-ReadOnlySnapshot "artifact_sha256" $(if ($hashMatches) { "PASS" } else { "FAIL" }) "sha256=$artifactHash; expected supplied=$([bool]$ExpectedArtifactSha256)"
    } catch {
        Add-ReadOnlySnapshot "artifact_sha256" "FAIL" "artifact hash could not be read: $($_.Exception.GetType().Name)"
    }
}

$backupStructure = "NOT TESTED"
if ($BackupPath) {
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [System.IO.Compression.ZipFile]::OpenRead($BackupPath)
        try {
            $entryNames = @($archive.Entries | ForEach-Object FullName)
            $manifestEntry = $archive.GetEntry("manifest.json")
            $databaseEntry = $archive.GetEntry("database/aura.dump")
            $unsafeNames = @($entryNames | Where-Object { $_ -match '(?i)(^|/)(credentials?|mcp_servers\.json|\.env|api[_-]?token|provider[_-]?key)(/|$|\.)' })
            $manifestValid = $false
            if ($manifestEntry) {
                $reader = [System.IO.StreamReader]::new($manifestEntry.Open())
                try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
                $manifestValid = ($manifest.format -eq "aura-desktop-backup" -and $manifest.format_version -eq 1)
            }
            $backupStructure = if ($manifestValid -and $databaseEntry -and $unsafeNames.Count -eq 0) { "PASS" } else { "FAIL" }
            Add-ReadOnlySnapshot "backup_archive_structure" $backupStructure "manifestValid=$manifestValid; databaseDumpPresent=$([bool]$databaseEntry); forbiddenEntryNames=$($unsafeNames.Count); memberCount=$($entryNames.Count)"
        } finally {
            $archive.Dispose()
        }
    } catch {
        $backupStructure = "FAIL"
        Add-ReadOnlySnapshot "backup_archive" "FAIL" "archive verification failed: $($_.Exception.GetType().Name)"
    }
}

$loopbackOnly = $false
if ($listenerQueryAvailable -and $listeners.Count) {
    $loopbackOnly = @($listeners | Where-Object { $_.localAddress -notin @("127.0.0.1", "::1") }).Count -eq 0
}

$d1Status = if (-not $appFile -or -not $appProcesses.Count -or -not $apiReady) { "FAIL" } else { "BLOCKED" }
$d1Blocker = if ($d1Status -eq "FAIL") { "installed process or ready API is missing" } else { "Start Menu launch and visible production UI require an isolated VM check" }
Add-Check "D1 fresh install and runtime" $d1Status "installedApp=$([bool]$appFile); processCount=$($appProcesses.Count); $apiEvidence" $d1Blocker
Add-Check "D2 tray, quit, relaunch, persistence" "BLOCKED" "no process or window actions were performed" "requires an isolated Windows VM/session; primary desktop is excluded"
Add-Check "D3 connected folder and selected file flow" "BLOCKED" "metadata/index/file-access unit tests run in Windows CI" "select/send interaction requires an isolated UI test session"
Add-Check "D4 Windows notifications" "BLOCKED" "notification settings and event UI were not exercised" "real OS toast delivery requires an isolated Windows session"
Add-Check "D5 failure injection" "NOT TESTED" "read-only Docker/API snapshot collected; no ports, processes, or containers were altered" "port conflict, API termination, and Docker outage scenarios need isolated fixtures"
Add-Check "D6 backup and restore" $(if ($backupStructure -eq "PASS") { "BLOCKED" } elseif ($BackupPath) { "FAIL" } else { "BLOCKED" }) "backup structure=$backupStructure; no restore or uninstall was attempted" "restore/uninstall persistence requires disposable profile, volume, and VM"
$d7Status = if ($listenerQueryAvailable -and $listeners.Count -and -not $loopbackOnly) { "FAIL" } else { "BLOCKED" }
Add-Check "D7 security and loopback" $d7Status "listenerQueryAvailable=$listenerQueryAvailable; listenerCount=$($listeners.Count); loopbackOnly=$loopbackOnly" "loopback snapshot is limited to running listeners; full filesystem, renderer, and credential verification is separate"

$finishedAt = Get-Date
$report = [pscustomobject]@{
    schemaVersion = 1
    startedAt = $startedAt.ToString("o")
    finishedAt = $finishedAt.ToString("o")
    appVersion = $appVersion
    apiReady = $apiReady
    dockerAvailable = $dockerAvailable
    listeners = $listeners
    snapshotChecks = $snapshotChecks
    checks = $checks
    logPath = $logPath
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $jsonPath -Encoding utf8
$lines | Set-Content -LiteralPath $logPath -Encoding utf8
Write-Output "Report: $jsonPath"
Write-Output "Log: $logPath"
Write-Output ($checks | ForEach-Object { "[$($_.status)] $($_.name)" })
