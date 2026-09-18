param(
    [string]$ReleaseDirectory = "release\DiskScope-v0.1.1-test-windows-x64",
    [switch]$KeepTestDirectory
)

$ErrorActionPreference = "Stop"
$PSDefaultParameterValues['Invoke-WebRequest:UseBasicParsing'] = $true
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseCandidate = if ([IO.Path]::IsPathRooted($ReleaseDirectory)) {
    $ReleaseDirectory
}
else {
    Join-Path $projectRoot $ReleaseDirectory
}
$sourceRelease = (Resolve-Path $releaseCandidate).Path
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("DiskScope-v0.1.1-Smoke-" + [guid]::NewGuid().ToString("N"))
$testRelease = Join-Path $testRoot "DiskScope"
$baseUri = "http://127.0.0.1:8765"
$originHeaders = @{ Origin = $baseUri }
$token = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$server = $null
$previousToken = $env:DISKSCOPE_BOOTSTRAP_TOKEN

function Invoke-ExpectedFailure {
    param(
        [scriptblock]$Action,
        [int]$StatusCode,
        [string]$Label
    )
    try {
        & $Action
        throw "$Label unexpectedly succeeded."
    }
    catch {
        if ($_.Exception.Response.StatusCode.value__ -ne $StatusCode) {
            throw "$Label returned an unexpected status: $($_.Exception.Message)"
        }
    }
}

try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    Copy-Item -LiteralPath $sourceRelease -Destination $testRelease -Recurse
    $exe = Join-Path $testRelease "DiskScope.exe"
    $stdout = Join-Path $testRoot "server.stdout.log"
    $stderr = Join-Path $testRoot "server.stderr.log"
    $env:DISKSCOPE_BOOTSTRAP_TOKEN = $token
    $startedAt = [Diagnostics.Stopwatch]::StartNew()
    $server = Start-Process -FilePath $exe -ArgumentList "--serve" -WorkingDirectory $testRelease `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru

    $health = $null
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($server.HasExited) {
            throw "Packaged server exited before health became ready (exit $($server.ExitCode))."
        }
        try {
            $health = Invoke-RestMethod -Uri "$baseUri/health" -TimeoutSec 2
            break
        }
        catch {
            Start-Sleep -Milliseconds 150
        }
    }
    if ($null -eq $health) { throw "Packaged server did not become healthy within 30 seconds." }
    $startedAt.Stop()
    if ($health.status -ne "ok" -or $health.version -ne "0.1.1" -or $health.developer_mode) {
        throw "Packaged health metadata is invalid."
    }

    $index = Invoke-WebRequest -Uri "$baseUri/" -TimeoutSec 5
    if ($index.StatusCode -ne 200 -or $index.Content -notmatch '<div id="app"></div>') {
        throw "Packaged frontend entry point is unavailable."
    }
    $assetPath = [regex]::Match($index.Content, 'src="([^"]+\.js)"').Groups[1].Value
    if (-not $assetPath) { throw "Packaged frontend JavaScript asset was not found." }
    $asset = Invoke-WebRequest -Uri ($baseUri + $assetPath) -Method Head -TimeoutSec 5
    if ($asset.StatusCode -ne 200) { throw "Packaged frontend asset is unavailable." }

    $webSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-WebRequest -Uri "$baseUri/api/v1/session/bootstrap" -Method Post -WebSession $webSession `
        -Headers $originHeaders -ContentType "application/json" -Body (@{ token = $token } | ConvertTo-Json) | Out-Null
    $session = Invoke-RestMethod -Uri "$baseUri/api/v1/session" -WebSession $webSession
    if (-not $session.ready) { throw "Packaged session was not established." }

    Invoke-ExpectedFailure -StatusCode 403 -Label "Arbitrary-root scan" -Action {
        Invoke-WebRequest -Uri "$baseUri/api/v1/scans" -Method Post -WebSession $webSession `
            -Headers $originHeaders -ContentType "application/json" `
            -Body (@{ root = "C:\Windows" } | ConvertTo-Json) | Out-Null
    }
    Invoke-ExpectedFailure -StatusCode 403 -Label "Development fixture scan" -Action {
        Invoke-WebRequest -Uri "$baseUri/api/v1/scans" -Method Post -WebSession $webSession `
            -Headers $originHeaders -ContentType "application/json" `
            -Body (@{ scope_key = "fixture_sample" } | ConvertTo-Json) | Out-Null
    }

    $scanRequest = Invoke-RestMethod -Uri "$baseUri/api/v1/scans" -Method Post -WebSession $webSession `
        -Headers $originHeaders -ContentType "application/json" `
        -Body (@{ scope_key = "current_user_temp" } | ConvertTo-Json)
    $scan = $null
    $scanDeadline = [DateTime]::UtcNow.AddMinutes(5)
    while ([DateTime]::UtcNow -lt $scanDeadline) {
        $scan = Invoke-RestMethod -Uri "$baseUri/api/v1/scans/$($scanRequest.scan_id)" -WebSession $webSession
        if ($scan.state -in @("cancelled", "failed")) { break }
        if ($scan.state -eq "completed" -and $scan.snapshot_status -ne "pending") { break }
        Start-Sleep -Milliseconds 250
    }
    if ($null -eq $scan -or $scan.state -ne "completed" -or $scan.snapshot_status -ne "saved") {
        throw "Packaged Temp scan did not complete with a saved snapshot."
    }

    $probe = Invoke-RestMethod -Uri "$baseUri/api/v1/cleanup/probes" -Method Post -WebSession $webSession `
        -Headers $originHeaders -ContentType "application/json" -Body "{}"
    $prepared = Invoke-RestMethod -Uri "$baseUri/api/v1/cleanup/probes/$($probe.probe_id)/prepare" `
        -Method Post -WebSession $webSession -Headers $originHeaders -ContentType "application/json" `
        -Body (@{ requested_action = "recycle" } | ConvertTo-Json)
    if (-not $prepared.execution_token -or -not $prepared.real_execution_enabled) {
        throw "Controlled probe did not pass guarded preparation."
    }
    $execution = Invoke-RestMethod -Uri "$baseUri/api/v1/cleanup/execute" -Method Post `
        -WebSession $webSession -Headers $originHeaders -ContentType "application/json" `
        -Body (@{ execution_token = $prepared.execution_token } | ConvertTo-Json)
    if ($execution.status -ne "completed" -or $execution.final_result -ne "recycled" -or `
        $execution.target_mutation -ne "recycle_bin") {
        throw "Controlled probe was not recycled through the guarded workflow."
    }

    $conflictOut = Join-Path $testRoot "port-conflict.stdout.log"
    $conflictErr = Join-Path $testRoot "port-conflict.stderr.log"
    $conflict = Start-Process -FilePath $exe -WorkingDirectory $testRelease `
        -RedirectStandardOutput $conflictOut -RedirectStandardError $conflictErr -WindowStyle Hidden -PassThru -Wait
    if ($conflict.ExitCode -eq 0) { throw "Second instance did not fail safely on the occupied port." }
    $conflictText = ((Get-Content $conflictOut -Raw -ErrorAction SilentlyContinue) + `
        (Get-Content $conflictErr -Raw -ErrorAction SilentlyContinue))
    if ($conflictText -notmatch "already in use") { throw "Port conflict did not produce a clear diagnostic." }

    $databasePath = Join-Path $testRelease "data\diskscope.db"
    if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
        throw "Packaged runtime database was not created beside the executable."
    }
    $combinedLogs = ((Get-Content $stdout -Raw -ErrorAction SilentlyContinue) + `
        (Get-Content $stderr -Raw -ErrorAction SilentlyContinue) + $conflictText)
    if ($combinedLogs.Contains($token)) { throw "Bootstrap token was exposed in process output." }

    [pscustomobject]@{
        test_directory = $testRoot
        startup_ms = $startedAt.ElapsedMilliseconds
        version = $health.version
        developer_mode = $health.developer_mode
        scan_id = $scan.scan_id
        files_seen = $scan.files_seen
        dirs_seen = $scan.dirs_seen
        logical_bytes = $scan.logical_bytes
        duration_ms = $scan.metrics.duration_ms
        files_per_second = $scan.metrics.files_per_second
        rss_peak_bytes = $scan.metrics.rss_peak_observed_bytes
        cpu_seconds = $scan.metrics.cpu_seconds
        process_read_bytes = $scan.metrics.delta_read_bytes
        process_write_bytes = $scan.metrics.delta_write_bytes
        snapshot_id = $scan.snapshot_id
        probe_id = $probe.probe_id
        cleanup_execution_id = $execution.execution_id
        port_conflict_exit_code = $conflict.ExitCode
        database_path = $databasePath
    } | ConvertTo-Json
}
finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
        $server.WaitForExit(10000) | Out-Null
    }
    if ($null -eq $previousToken) {
        Remove-Item Env:DISKSCOPE_BOOTSTRAP_TOKEN -ErrorAction SilentlyContinue
    }
    else {
        $env:DISKSCOPE_BOOTSTRAP_TOKEN = $previousToken
    }
    if (-not $KeepTestDirectory -and (Test-Path -LiteralPath $testRoot)) {
        $resolvedTemp = (Resolve-Path ([System.IO.Path]::GetTempPath())).Path.TrimEnd('\')
        $resolvedTest = (Resolve-Path $testRoot).Path
        if (-not $resolvedTest.StartsWith($resolvedTemp + '\DiskScope-v0.1.1-Smoke-', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove an unexpected smoke-test directory: $resolvedTest"
        }
        Remove-Item -LiteralPath $resolvedTest -Recurse -Force
    }
}
