param(
    [ValidateSet("Live", "Mock")]
    [string]$Mode = "Live",
    [string]$DiagnosticsPath = "",
    [switch]$InjectMockFailure
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = "C:\Python313\python.exe"
$phaseDir = if ($Mode -eq "Mock") {
    Join-Path $root "tmp\phase5-acceptance-mock-$PID"
} else {
    Join-Path $root "tmp\phase5-acceptance"
}
$statusPath = Join-Path $phaseDir "status.json"
$failureStatusPath = Join-Path $root "tmp\phase5-acceptance-last-status.json"
$controlsPath = Join-Path $phaseDir "controls.json"
$holdoutBundle = Join-Path $phaseDir "holdout_bundle.json"
$evaluationOutput = Join-Path $phaseDir "holdout_evaluation.json"
$manualOutput = Join-Path $phaseDir "manual_qa.json"
$gatesOutput = Join-Path $phaseDir "final_gates.json"
$manualSignal = Join-Path $phaseDir "manual_complete.flag"
$reportSignal = Join-Path $phaseDir "report_recorded.flag"
$holdoutLog = Join-Path $phaseDir "holdout.log"
$gateLog = Join-Path $phaseDir "engineering_gates.log"
$holdoutResult = Join-Path $root "tmp\supportpilot-acceptance\result.json"
$stageHistory = [System.Collections.Generic.List[string]]::new()
$currentStage = "INITIALIZING"
$failureCode = "UNCLASSIFIED_FAILURE"
$secureKey = $null
$keyBuffer = [IntPtr]::Zero
$cleanupComplete = $false
$completed = $false

function Normalize-ProcessPath {
    # Windows may supply both Path and PATH. PowerShell's environment provider
    # treats them as the same dictionary key and child launches become unreliable.
    $processPath = [Environment]::GetEnvironmentVariable("Path", "Process")
    if (-not $processPath) {
        $processPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
    }
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    if ($processPath) {
        [Environment]::SetEnvironmentVariable("Path", $processPath, "Process")
    }
}

function Write-Status([string]$Status, [hashtable]$Extra = @{}) {
    if ($stageHistory.Count -eq 0 -or $stageHistory[$stageHistory.Count - 1] -ne $Status) {
        $stageHistory.Add($Status)
    }
    $payload = [ordered]@{
        status = $Status
        mode = $Mode.ToUpperInvariant()
        timestamp = [DateTimeOffset]::UtcNow.ToString("o")
        stage_history = @($stageHistory)
    }
    foreach ($key in $Extra.Keys) {
        $payload[$key] = $Extra[$key]
    }
    $payload | ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $statusPath -Encoding UTF8
}

function Set-Stage([string]$Status) {
    $script:currentStage = $Status
    Write-Status $Status
}

function Assert-ExitCode([string]$Code, [string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        $script:failureCode = $Code
        throw $Message
    }
}

function Wait-ForFile([string]$Path, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $Path) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    $script:failureCode = "CONTROLLED_STAGE_TIMEOUT"
    throw "Timed out waiting for the controlled acceptance stage."
}

function Invoke-LoggedGate(
    [string]$Name,
    [scriptblock]$Command,
    [hashtable]$Results
) {
    # Native tools routinely use stderr for warnings and progress. Under the
    # runner's global Stop policy, PowerShell turns redirected stderr into a
    # terminating RemoteException before we can capture the native exit code.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command *>> $gateLog
        $nativeExitCode = $LASTEXITCODE
    } catch {
        $_ | Out-String | Add-Content -LiteralPath $gateLog -Encoding UTF8
        $nativeExitCode = 1
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $Results[$Name] = ($nativeExitCode -eq 0)
}

function Invoke-MockWorkflow {
    Set-Stage "AUTHENTICATED_REST_CONTROL"
    if ($InjectMockFailure) {
        $script:failureCode = "INJECTED_MOCK_FAILURE"
        throw "Injected credential-free orchestration failure."
    }
    Push-Location $root
    try {
        & $python -m scripts.phase5_acceptance_controls `
            --mode mock --output $controlsPath
    } finally {
        Pop-Location
    }
    Assert-ExitCode "MOCK_CONTROLS_FAILED" "Controlled provider responses failed."
    foreach ($stage in @(
        "AUTHENTICATED_MCP_PREFLIGHT",
        "PROVIDER_RELIABILITY",
        "CANDIDATE_PRECISION",
        "POSITIVE_SIGNAL_CONTROL",
        "CLEAN_SUPPORTPILOT_V2_HOLDOUT",
        "DISCOVERY_FUNNEL_REPORTING",
        "TOP10_MANUAL_QA",
        "EVIDENCE_LINK_VALIDATION",
        "OPPORTUNITY_BRIEF_USEFULNESS",
        "FOUNDER_VALUE_EVALUATION",
        "FINAL_ENGINEERING_GATES",
        "SECRET_SCAN",
        "COMPLETE"
    )) {
        Set-Stage $stage
    }
    $mockResult = [ordered]@{
        mode = "MOCK"
        all_passed = $true
        stage_history = @($stageHistory)
        credential_prompted = $false
        credential_persisted = $false
        cleanup_contract = "outermost_finally"
    }
    if ($DiagnosticsPath) {
        $mockResult | ConvertTo-Json -Depth 10 |
            Set-Content -LiteralPath $DiagnosticsPath -Encoding UTF8
    }
    $script:completed = $true
}

try {
    Normalize-ProcessPath
    if (Test-Path -LiteralPath $phaseDir) {
        Remove-Item -LiteralPath $phaseDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $phaseDir | Out-Null
    Remove-Item -LiteralPath $failureStatusPath -Force -ErrorAction SilentlyContinue

    if ($Mode -eq "Mock") {
        Invoke-MockWorkflow
        return
    }

    Set-Stage "AWAITING_SECURE_KEY"
    $secureKey = Read-Host "Paste rotated EXA_API_KEY" -AsSecureString
    $keyBuffer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyBuffer)
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        $failureCode = "EMPTY_CREDENTIAL"
        throw "Credential input was empty."
    }
    [Environment]::SetEnvironmentVariable("EXA_API_KEY", $plainKey, "Process")
    $plainKey = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyBuffer)
    $keyBuffer = [IntPtr]::Zero
    $secureKey.Dispose()
    $secureKey = $null

    [Environment]::SetEnvironmentVariable("TAVILY_API_KEY", $null, "Process")
    $env:APP_ENV = "development"
    $env:RESEARCH_MODE = "live"
    $env:DEMO_AUTH_ENABLED = "true"
    $env:AGENT_REACH_ENABLED = "true"
    $env:PRODUCTION_ACCEPTANCE = "true"
    $env:SEARCH_BACKEND = "exa_mcp"
    $env:SECONDARY_SEARCH_PROVIDER = "tavily"
    $env:MINIMUM_GENERAL_SEARCH_RESULTS = "3"
    $env:MAX_ACCOUNT_CANDIDATES = "60"
    $env:MAX_ACCOUNTS_RESEARCHED = "20"
    $env:MAX_RESEARCH_SEARCHES = "60"
    $env:MAX_RESEARCH_DOCUMENTS = "100"
    $env:MAX_RESEARCH_ELAPSED_SECONDS = "900"
    $env:DATABASE_URL = "postgresql+asyncpg://gtm:gtm@127.0.0.1:5432/gtm"
    $env:REDIS_URL = "redis://127.0.0.1:6379/0"
    $env:AGENT_REACH_GATEWAY_URL = "http://127.0.0.1:8010"
    $env:RESEARCH_GATEWAY_TIMEOUT_SECONDS = "180"
    $env:GATEWAY_FETCH_TIMEOUT_SECONDS = "45"
    $env:GDELT_MAX_ATTEMPTS = "1"

    Set-Stage "RUNTIME_PREFLIGHT"
    & $python -c (
        "import sys,tldextract;" +
        "assert sys.executable.lower()==r'C:\Python313\python.exe'.lower();" +
        "assert tldextract.__version__=='5.3.0'"
    )
    Assert-ExitCode "PINNED_RUNTIME_FAILED" "Pinned Python runtime preflight failed."
    $listeners = @(
        Get-NetTCPConnection -State Listen -LocalPort 8000,8010 `
            -ErrorAction SilentlyContinue
    )
    if ($listeners.Count -gt 0) {
        $failureCode = "ACCEPTANCE_PORT_IN_USE"
        throw "A required acceptance port is already in use."
    }

    Set-Stage "AUTHENTICATED_REST_CONTROL"
    Push-Location $root
    try {
        & $python -m scripts.phase5_acceptance_controls `
            --mode live --output $controlsPath
    } finally {
        Pop-Location
    }
    Assert-ExitCode "AUTHENTICATED_CONTROLS_FAILED" (
        "Authenticated REST, MCP, reliability, precision, or positive control failed."
    )
    $controls = Get-Content -LiteralPath $controlsPath -Raw | ConvertFrom-Json
    if (
        -not $controls.provider.authenticated -or
        $controls.provider.anonymous_mcp_capacity -or
        $controls.provider.tavily -ne "NOT_CONFIGURED"
    ) {
        $failureCode = "PROVIDER_AUTHENTICATION_NOT_PROVEN"
        throw "Authenticated Exa-only provider state was not proven."
    }
    Set-Stage "AUTHENTICATED_MCP_PREFLIGHT"
    Set-Stage "PROVIDER_RELIABILITY"
    Set-Stage "CANDIDATE_PRECISION"
    Set-Stage "POSITIVE_SIGNAL_CONTROL"

    Set-Stage "CLEAN_SUPPORTPILOT_V2_HOLDOUT"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
        (Join-Path $root "scripts\supportpilot_v2_acceptance.ps1") *> $holdoutLog
    Assert-ExitCode "SUPPORTPILOT_V2_HOLDOUT_FAILED" (
        "Fresh SupportPilot V2 holdout failed."
    )
    if (-not (Test-Path -LiteralPath $holdoutResult)) {
        $failureCode = "HOLDOUT_RESULT_MISSING"
        throw "Fresh holdout result was not produced."
    }

    Set-Stage "DISCOVERY_FUNNEL_REPORTING"
    Push-Location $root
    try {
        & $python -m scripts.phase5_holdout_export `
            $holdoutResult --output $holdoutBundle *> $holdoutLog
    } finally {
        Pop-Location
    }
    Assert-ExitCode "HOLDOUT_EXPORT_FAILED" "Holdout evidence export failed."

    Set-Stage "EVIDENCE_LINK_VALIDATION"
    Push-Location $root
    try {
        & $python -m scripts.evaluate_supportpilot_v2 `
            $holdoutResult --check-links --output $evaluationOutput *> $holdoutLog
    } finally {
        Pop-Location
    }
    Assert-ExitCode "EVIDENCE_LINK_EVALUATION_FAILED" (
        "Evidence-link evaluation failed."
    )

    Set-Stage "AWAITING_MANUAL_QA"
    Write-Status $currentStage @{
        controls_output = $controlsPath
        bundle_output = $holdoutBundle
        evaluation_output = $evaluationOutput
        manual_output = $manualOutput
    }
    Wait-ForFile $manualSignal 7200
    Set-Stage "TOP10_MANUAL_QA"
    Set-Stage "OPPORTUNITY_BRIEF_USEFULNESS"
    Set-Stage "FOUNDER_VALUE_EVALUATION"

    Set-Stage "FINAL_ENGINEERING_GATES"
    $gateResults = [ordered]@{}
    Set-Content -LiteralPath $gateLog -Value "" -Encoding UTF8
    Invoke-LoggedGate "python_all" {
        & $python -m pytest apps/api/tests services/research_gateway/tests `
            -q -p no:cacheprovider
    } $gateResults
    $env:RUN_LIVE_DB_TESTS = "1"
    Invoke-LoggedGate "postgres_redis_integration" {
        & $python -m pytest apps/api/tests/test_live_database_integration.py `
            -q -p no:cacheprovider
    } $gateResults
    Remove-Item Env:RUN_LIVE_DB_TESTS -ErrorAction SilentlyContinue
    Invoke-LoggedGate "gateway_security" {
        & $python -m pytest services/research_gateway/tests/test_security.py `
            -q -p no:cacheprovider
    } $gateResults
    Invoke-LoggedGate "frontend_tests" {
        & npm.cmd run test --workspace apps/web
    } $gateResults
    Invoke-LoggedGate "ruff" {
        & $python -m ruff check apps/api services/research_gateway scripts
    } $gateResults
    Invoke-LoggedGate "mypy" {
        & $python -m mypy apps/api/app services/research_gateway/app
    } $gateResults
    Invoke-LoggedGate "eslint" {
        & npm.cmd run lint --workspace apps/web
    } $gateResults
    Invoke-LoggedGate "typescript" {
        & npm.cmd run typecheck --workspace apps/web
    } $gateResults
    Invoke-LoggedGate "next_build" {
        & npm.cmd run build --workspace apps/web
    } $gateResults
    Invoke-LoggedGate "alembic" {
        & $python -m alembic -c apps/api/alembic.ini current
    } $gateResults
    Invoke-LoggedGate "docker_compose" {
        & docker compose config --quiet
    } $gateResults

    Set-Stage "SECRET_SCAN"
    $trackedFiles = @(git ls-files)
    $secretMatches = @(
        $trackedFiles | ForEach-Object {
            $fullPath = Join-Path $root $_
            if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
                Select-String -LiteralPath $fullPath -ErrorAction SilentlyContinue `
                    -Pattern '(?i)(EXA_API_KEY|TAVILY_API_KEY)\s*[:=]\s*["''][^"'']{8,}["'']'
            }
        }
    )
    $gateResults["secret_scan"] = ($secretMatches.Count -eq 0)
    & git diff --check *>> $gateLog
    $gateResults["git_diff_check"] = ($LASTEXITCODE -eq 0)
    $gateResults["all_passed"] = -not ($gateResults.Values -contains $false)
    $gateResults | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $gatesOutput -Encoding UTF8

    Set-Stage "AWAITING_REPORT_INCORPORATION"
    Write-Status $currentStage @{
        gates_output = $gatesOutput
        manual_output = $manualOutput
    }
    Wait-ForFile $reportSignal 7200
    Set-Stage "COMPLETE"
    $completed = $true
} catch {
    $failurePayload = [ordered]@{
        status = "FAILED"
        failure_stage = $currentStage
        failure_code = $failureCode
        exception_type = $_.Exception.GetType().Name
        mode = $Mode.ToUpperInvariant()
        timestamp = [DateTimeOffset]::UtcNow.ToString("o")
        stage_history = @($stageHistory)
    }
    if (Test-Path -LiteralPath $controlsPath) {
        try {
            $safeControls = Get-Content -LiteralPath $controlsPath -Raw |
                ConvertFrom-Json
            $failurePayload["provider_diagnostics"] = [ordered]@{
                rest_category = (
                    $safeControls.rest_control.diagnostic.error_category
                )
                mcp_category = (
                    $safeControls.mcp_preflight.safe_provider_category
                )
                reliability_pass_count = @(
                    $safeControls.reliability | Where-Object { $_.passed }
                ).Count
                positive_control_passed = [bool](
                    $safeControls.positive_signal_control.passed
                )
            }
        } catch {
            $failurePayload["provider_diagnostics"] = "UNAVAILABLE"
        }
    }
    $failurePayload | ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $failureStatusPath -Encoding UTF8
    exit 1
} finally {
    [Environment]::SetEnvironmentVariable("EXA_API_KEY", $null, "Process")
    [Environment]::SetEnvironmentVariable("TAVILY_API_KEY", $null, "Process")
    if ($keyBuffer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyBuffer)
        $keyBuffer = [IntPtr]::Zero
    }
    if ($null -ne $secureKey) {
        $secureKey.Dispose()
        $secureKey = $null
    }
    foreach ($name in @(
        "APP_ENV", "RESEARCH_MODE", "DEMO_AUTH_ENABLED", "AGENT_REACH_ENABLED",
        "PRODUCTION_ACCEPTANCE", "SEARCH_BACKEND", "SECONDARY_SEARCH_PROVIDER",
        "MINIMUM_GENERAL_SEARCH_RESULTS", "MAX_ACCOUNT_CANDIDATES",
        "MAX_ACCOUNTS_RESEARCHED", "MAX_RESEARCH_SEARCHES",
        "MAX_RESEARCH_DOCUMENTS", "MAX_RESEARCH_ELAPSED_SECONDS",
        "DATABASE_URL", "REDIS_URL", "AGENT_REACH_GATEWAY_URL",
        "RESEARCH_GATEWAY_TIMEOUT_SECONDS", "GATEWAY_FETCH_TIMEOUT_SECONDS",
        "GDELT_MAX_ATTEMPTS", "RUN_LIVE_DB_TESTS"
    )) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    if (Test-Path -LiteralPath $phaseDir) {
        Remove-Item -LiteralPath $phaseDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($path in @(
        (Join-Path $root "tmp\supportpilot-v2-acceptance\preflight.json"),
        (Join-Path $root "tmp\supportpilot-acceptance\result.json"),
        (Join-Path $root "tmp\supportpilot-acceptance\gateway.out.log"),
        (Join-Path $root "tmp\supportpilot-acceptance\gateway.err.log"),
        (Join-Path $root "tmp\supportpilot-acceptance\api.out.log"),
        (Join-Path $root "tmp\supportpilot-acceptance\api.err.log"),
        (Join-Path $root "tmp\supportpilot-acceptance\worker.out.log"),
        (Join-Path $root "tmp\supportpilot-acceptance\worker.err.log")
    )) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
    Get-ChildItem -LiteralPath (Join-Path $root "scripts\__pycache__") `
        -Filter "phase5_*.pyc" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    $cleanupComplete = $true
    if (Test-Path -LiteralPath $failureStatusPath) {
        $failurePayload = Get-Content -LiteralPath $failureStatusPath -Raw |
            ConvertFrom-Json
        $failurePayload | Add-Member -NotePropertyName cleanup_complete `
            -NotePropertyValue $true -Force
        $failurePayload | Add-Member -NotePropertyName credential_remaining `
            -NotePropertyValue $false -Force
        $failurePayload | ConvertTo-Json -Depth 10 |
            Set-Content -LiteralPath $failureStatusPath -Encoding UTF8
    }
    if ($DiagnosticsPath -and $Mode -eq "Live" -and $completed) {
        [ordered]@{
            status = "COMPLETE"
            cleanup_complete = $true
            credential_remaining = $false
            stage_history = @($stageHistory)
        } | ConvertTo-Json -Depth 10 |
            Set-Content -LiteralPath $DiagnosticsPath -Encoding UTF8
    }
}
