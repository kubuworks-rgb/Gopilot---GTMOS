$ErrorActionPreference = "Stop"

$env:APP_ENV = "development"
$env:RESEARCH_MODE = "live"
$env:DEMO_AUTH_ENABLED = "true"
$env:AGENT_REACH_ENABLED = "true"
if (-not $env:SEARCH_BACKEND) {
    $env:SEARCH_BACKEND = "exa_mcp"
}
$env:DATABASE_URL = "postgresql+asyncpg://gtm:gtm@127.0.0.1:5432/gtm"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:AGENT_REACH_GATEWAY_URL = "http://127.0.0.1:8010"
$env:RESEARCH_GATEWAY_TIMEOUT_SECONDS = "180"
$env:GATEWAY_FETCH_TIMEOUT_SECONDS = "45"
$env:GDELT_MAX_ATTEMPTS = "1"
$env:MAX_RESEARCH_SEARCHES = "60"
$env:MAX_RESEARCH_DOCUMENTS = "100"
$env:MAX_ACCOUNT_CANDIDATES = "40"
$env:MAX_ACCOUNTS_RESEARCHED = "15"
$env:MAX_RESEARCH_ELAPSED_SECONDS = "900"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $root "tmp\supportpilot-acceptance"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$resultPath = Join-Path $logDir "result.json"

$gateway = $null
$api = $null
$worker = $null

function Wait-Health([string]$Url) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
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
        -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 12) `
        -TimeoutSec 180
}

try {
    $gateway = Start-Process python -ArgumentList @(
        "-m", "uvicorn", "services.research_gateway.app.main:app",
        "--host", "127.0.0.1", "--port", "8010"
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $logDir "gateway.out.log") `
      -RedirectStandardError (Join-Path $logDir "gateway.err.log")
    $api = Start-Process python -ArgumentList @(
        "-m", "uvicorn", "apps.api.app.main:app",
        "--host", "127.0.0.1", "--port", "8000"
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $logDir "api.out.log") `
      -RedirectStandardError (Join-Path $logDir "api.err.log")
    $worker = Start-Process python -ArgumentList @(
        "-m", "services.worker.app.main"
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $logDir "worker.out.log") `
      -RedirectStandardError (Join-Path $logDir "worker.err.log")

    $gatewayHealth = Wait-Health "http://127.0.0.1:8010/internal/v1/health"
    $apiHealth = Wait-Health "http://127.0.0.1:8000/health"

    if ($env:SUPPORTPILOT_RESUME_WORKSPACE -and $env:SUPPORTPILOT_RESUME_USER) {
        $user = $env:SUPPORTPILOT_RESUME_USER
        $workspace = [pscustomobject]@{ id = $env:SUPPORTPILOT_RESUME_WORKSPACE }
        $headers = @{
            "X-Demo-User" = $user
            "X-Workspace-Id" = $workspace.id
        }
        $bootstrap = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/v1/bootstrap" `
            -Headers $headers -TimeoutSec 30
        $product = $bootstrap.product
        $run = $bootstrap.research_run
        if ($env:SUPPORTPILOT_REFRESH_ACCOUNTS -eq "true") {
            Invoke-RestMethod -Method Post `
                -Uri "http://127.0.0.1:8000/api/v1/accounts/refresh" `
                -Headers $headers -TimeoutSec 60 | Out-Null
            for ($attempt = 0; $attempt -lt 30; $attempt++) {
                Start-Sleep -Seconds 1
                $run = Invoke-RestMethod `
                    -Uri "http://127.0.0.1:8000/api/v1/research-runs/$($run.id)" `
                    -Headers $headers -TimeoutSec 20
                if ($run.status -eq "discovering_accounts") {
                    break
                }
            }
        }
    } else {
        $user = "supportpilot-acceptance-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
        $workspace = Post-Json "http://127.0.0.1:8000/api/v1/workspaces" `
            @{ name = "SupportPilot AI Live Acceptance" } `
            @{ "X-Demo-User" = $user }
        $headers = @{
            "X-Demo-User" = $user
            "X-Workspace-Id" = $workspace.id
        }
        $product = Post-Json "http://127.0.0.1:8000/api/v1/products" @{
            company_name = "SupportPilot AI"
            website = "https://supportpilot.test"
            product = (
                "AI customer-support automation platform. AI agents answer repetitive " +
                "customer questions, triage support tickets, assist human support agents, " +
                "reduce response time, and reduce repetitive support workload."
            )
            target_market = "India B2B SaaS companies with 50-500 employees"
        } $headers
        $run = Invoke-RestMethod -Method Post `
            -Uri "http://127.0.0.1:8000/api/v1/research-runs?product_id=$($product.id)" `
            -Headers $headers -TimeoutSec 60
    }

    for ($attempt = 0; $attempt -lt 600; $attempt++) {
        Start-Sleep -Seconds 2
        $run = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/v1/research-runs/$($run.id)" `
            -Headers $headers -TimeoutSec 20
        if ($run.status -in @("awaiting_icp", "completed", "failed", "partial")) {
            break
        }
    }

    $icps = @()
    $selected = $null
    if ($run.status -eq "awaiting_icp") {
        $rawIcps = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/v1/icps" `
            -Headers $headers -TimeoutSec 20
        $icps = @()
        for ($index = 0; $index -lt $rawIcps.Count; $index++) {
            $icps += $rawIcps[$index]
        }
        $icpIds = @($icps.id)
        $recommendedId = if ($icpIds.Count -gt 0) { $icpIds[0] } else { $null }
        if ($null -ne $recommendedId) {
            $selected = Invoke-RestMethod -Method Post `
                -Uri "http://127.0.0.1:8000/api/v1/icps/$recommendedId/select" `
                -Headers $headers -TimeoutSec 60
        }
    }

    for ($attempt = 0; $attempt -lt 900; $attempt++) {
        Start-Sleep -Seconds 2
        $run = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/v1/research-runs/$($run.id)" `
            -Headers $headers -TimeoutSec 20
        if ($run.status -in @("completed", "partial", "failed")) {
            break
        }
    }

    $rawAccounts = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/v1/accounts" `
        -Headers $headers -TimeoutSec 30
    $accounts = @()
    for ($index = 0; $index -lt $rawAccounts.Count; $index++) {
        $accounts += $rawAccounts[$index]
    }
    $lineage = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/v1/research-runs/$($run.id)/evidence" `
        -Headers $headers -TimeoutSec 30
    $topBriefs = @()
    foreach ($account in @($accounts | Select-Object -First 10)) {
        try {
            $brief = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8000/api/v1/accounts/$($account.id)/opportunity-brief" `
                -Headers $headers -TimeoutSec 30
            $topBriefs += [ordered]@{
                account_id = $account.id
                company = $account.name
                domain = $account.domain
                qualification = $account.qualification_status
                priority = $account.scores.priority
                signals = @($brief.signals)
                evidence = @($brief.evidence)
                sources = @($brief.sources)
                recommended_action = $brief.recommended_action
                risks = @($brief.risks)
            }
        } catch {
            $topBriefs += [ordered]@{
                account_id = $account.id
                company = $account.name
                domain = $account.domain
                error = $_.Exception.Message
            }
        }
    }

    $result = [ordered]@{
        test_product_label = "TEST PRODUCT PROFILE - NOT A REAL COMPANY CLAIM"
        gateway_status = $gatewayHealth.status
        api_status = $apiHealth.status
        mode = $apiHealth.mode
        workspace_id = $workspace.id
        user_id = $user
        product = $product
        research_run = $run
        icps = $icps
        selected_icp = $selected
        account_count = $accounts.Count
        accounts = $accounts
        evidence_record_count = @($lineage.evidence).Count
        source_record_count = @($lineage.sources).Count
        source_backends = @($lineage.sources.backend | Sort-Object -Unique)
        top_briefs = $topBriefs
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
    }
    $json = $result | ConvertTo-Json -Depth 20
    $json | Set-Content -Encoding utf8 $resultPath
    Write-Output $json
    Write-Output "RESULT_PATH=$resultPath"
} finally {
    foreach ($process in @($worker, $api, $gateway)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        }
    }
}
