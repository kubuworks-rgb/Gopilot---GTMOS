$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$resultDir = Join-Path $root "tmp\supportpilot-v2-acceptance"
$resultPath = Join-Path $resultDir "preflight.json"
New-Item -ItemType Directory -Force -Path $resultDir | Out-Null

python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('tldextract') else 1)"
$pslDependencyInstalled = $LASTEXITCODE -eq 0

$providerState = [ordered]@{
    exa_authenticated = [bool]$env:EXA_API_KEY
    tavily_authenticated = [bool]$env:TAVILY_API_KEY
    secondary_provider = "tavily"
    psl_dependency_installed = $pslDependencyInstalled
}

if (
    -not $providerState.exa_authenticated -or
    -not $providerState.tavily_authenticated -or
    -not $providerState.psl_dependency_installed
) {
    $result = [ordered]@{
        status = "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE"
        phase = "SupportPilot V2 holdout preflight"
        providers = $providerState
        live_run_started = $false
        message = (
            "SupportPilot V2 requires authenticated Exa, authenticated Tavily, " +
            "and the pinned PSL dependency. No degraded acceptance is allowed."
        )
        checked_at = [DateTimeOffset]::UtcNow.ToString("o")
    }
    $json = $result | ConvertTo-Json -Depth 6
    $json | Set-Content -Encoding utf8 $resultPath
    Write-Output $json
    Write-Output "RESULT_PATH=$resultPath"
    exit 2
}

$env:PRODUCTION_ACCEPTANCE = "true"
$env:SEARCH_BACKEND = "exa_mcp"
$env:SECONDARY_SEARCH_PROVIDER = "tavily"
$env:MINIMUM_GENERAL_SEARCH_RESULTS = "3"
$env:MAX_ACCOUNT_CANDIDATES = "60"
$env:MAX_ACCOUNTS_RESEARCHED = "20"
$env:SUPPORTPILOT_PROFILE_VERSION = "V2"

& (Join-Path $PSScriptRoot "supportpilot_acceptance.ps1")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
