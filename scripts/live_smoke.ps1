$ErrorActionPreference = "Stop"

$env:APP_ENV = "development"
$env:RESEARCH_MODE = "live"
$env:DEMO_AUTH_ENABLED = "true"
$env:AGENT_REACH_ENABLED = "true"
$env:DATABASE_URL = "postgresql+asyncpg://gtm:gtm@127.0.0.1:5432/gtm"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:AGENT_REACH_GATEWAY_URL = "http://127.0.0.1:8010"
$env:MAX_RESEARCH_SEARCHES = "4"
$env:MAX_RESEARCH_DOCUMENTS = "8"
$env:MAX_ACCOUNT_CANDIDATES = "8"
$env:MAX_ACCOUNTS_RESEARCHED = "3"

$logDir = Join-Path $PSScriptRoot "..\tmp\live-smoke"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$gateway = $null
$api = $null
$worker = $null

function Wait-Health([string]$Url) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            return Invoke-RestMethod -Uri $Url -TimeoutSec 3
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Service did not become healthy: $Url"
}

function Post-Json([string]$Url, [object]$Body, [hashtable]$Headers = @{}) {
    return Invoke-RestMethod -Method Post -Uri $Url -Headers $Headers `
        -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8) `
        -TimeoutSec 30
}

try {
    $gateway = Start-Process python -ArgumentList @(
        "-m", "uvicorn", "services.research_gateway.app.main:app",
        "--host", "127.0.0.1", "--port", "8010"
    ) -WorkingDirectory (Resolve-Path (Join-Path $PSScriptRoot "..")) `
      -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $logDir "gateway.out.log") `
      -RedirectStandardError (Join-Path $logDir "gateway.err.log")
    $api = Start-Process python -ArgumentList @(
        "-m", "uvicorn", "apps.api.app.main:app",
        "--host", "127.0.0.1", "--port", "8000"
    ) -WorkingDirectory (Resolve-Path (Join-Path $PSScriptRoot "..")) `
      -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $logDir "api.out.log") `
      -RedirectStandardError (Join-Path $logDir "api.err.log")
    $worker = Start-Process python -ArgumentList @(
        "-m", "services.worker.app.main"
    ) -WorkingDirectory (Resolve-Path (Join-Path $PSScriptRoot "..")) `
      -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $logDir "worker.out.log") `
      -RedirectStandardError (Join-Path $logDir "worker.err.log")

    $gatewayHealth = Wait-Health "http://127.0.0.1:8010/internal/v1/health"
    $apiHealth = Wait-Health "http://127.0.0.1:8000/health"

    $user = "live-smoke-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
    $workspace = Post-Json "http://127.0.0.1:8000/api/v1/workspaces" `
        @{ name = "Kubu Works Live Smoke" } @{ "X-Demo-User" = $user }
    $headers = @{
        "X-Demo-User" = $user
        "X-Workspace-Id" = $workspace.id
    }
    $product = Post-Json "http://127.0.0.1:8000/api/v1/products" @{
        company_name = "Kubu Works"
        website = "https://kubuworks.com"
        product = "Evidence-backed GTM intelligence and account prioritization"
        target_market = "Founder-led B2B SaaS companies in India"
    } $headers
    $run = Invoke-RestMethod -Method Post `
        -Uri "http://127.0.0.1:8000/api/v1/research-runs?product_id=$($product.id)" `
        -Headers $headers -TimeoutSec 30

    for ($attempt = 0; $attempt -lt 240; $attempt++) {
        Start-Sleep -Seconds 2
        $run = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/v1/research-runs/$($run.id)" `
            -Headers $headers -TimeoutSec 10
        if ($run.status -in @("awaiting_icp", "failed", "partial")) {
            break
        }
    }

    $icps = @()
    $accounts = @()
    $lineage = $null
    if ($run.status -eq "awaiting_icp") {
        $icps = @(Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/icps" `
            -Headers $headers -TimeoutSec 10)
        if ($icps.Count -gt 0) {
            $icpId = @($icps.id)[0]
            $selected = Invoke-RestMethod -Method Post `
                -Uri "http://127.0.0.1:8000/api/v1/icps/$icpId/select" `
                -Headers $headers -TimeoutSec 30
            for ($attempt = 0; $attempt -lt 90; $attempt++) {
                Start-Sleep -Seconds 2
                $accounts = @(Invoke-RestMethod `
                    -Uri "http://127.0.0.1:8000/api/v1/accounts" `
                    -Headers $headers -TimeoutSec 10)
                if ($accounts.Count -gt 0) {
                    break
                }
            }
            for ($attempt = 0; $attempt -lt 90; $attempt++) {
                $run = Invoke-RestMethod `
                    -Uri "http://127.0.0.1:8000/api/v1/research-runs/$($run.id)" `
                    -Headers $headers -TimeoutSec 10
                if ($run.status -in @("completed", "partial", "failed")) {
                    break
                }
                Start-Sleep -Seconds 2
            }
        }
    }
    $lineage = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/v1/research-runs/$($run.id)/evidence" `
        -Headers $headers -TimeoutSec 10

    [ordered]@{
        gateway_status = $gatewayHealth.status
        api_status = $apiHealth.status
        mode = $apiHealth.mode
        workspace_id = $workspace.id
        research_run_id = $run.id
        research_status = $run.status
        searches_used = $run.searches_used
        documents_used = $run.documents_used
        findings = if ($null -eq $run.findings) { 0 } else { @($run.findings).Count }
        icps = $icps.Count
        accounts = $accounts.Count
        evidence_records = $lineage.evidence.Count
        source_records = $lineage.sources.Count
        source_backends = @($lineage.sources.backend | Sort-Object -Unique)
        demo_data_records = (
            $lineage.sources | Where-Object { $_.demo_data }
        ).Count
        error = $run.error
    } | ConvertTo-Json -Depth 8
} finally {
    foreach ($process in @($worker, $api, $gateway)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        }
    }
}
