param(
    [switch]$NoInstall,
    [switch]$SkipPython,
    [switch]$SkipFrontend,
    [switch]$SkipSemgrep,
    [switch]$SkipTrivy,
    [switch]$SkipZap,
    [ValidateSet('baseline', 'api', 'full')]
    [string]$ZapMode = 'baseline',
    [string]$ZapTarget = 'https://host.docker.internal/',
    [string]$ZapApiSpecUrl = 'http://host.docker.internal:5000/api/docs.json',
    [string]$ZapApiKey = $env:ZAP_API_KEY,
    [string]$ZapDockerImage = 'ghcr.io/zaproxy/zaproxy:stable',
    [switch]$ZapFailOnWarn,
    [ValidateSet('low', 'moderate', 'high', 'critical')]
    [string]$NpmAuditLevel = 'moderate',
    [string]$PythonRequirements = 'requirements.txt'
)

$ErrorActionPreference = 'Stop'
$script:FailureCount = 0

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Message)
    Write-Host "[STEP] $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[ OK ] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Magenta
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    $script:FailureCount++
}

function Test-CommandExists {
    param([string]$CommandName)
    return [bool](Get-Command $CommandName -ErrorAction SilentlyContinue)
}

function Invoke-ScanStep {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Step $Name
    try {
        & $Action
        Write-Ok $Name
    }
    catch {
        Write-Fail "$Name failed: $($_.Exception.Message)"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repoRoot

try {
    Write-Section "Security Scan Runner"
    Write-Host "Repository root: $repoRoot"

    if (-not $SkipPython) {
        Write-Section "Python Dependency and Code Scans"

        if (-not (Test-CommandExists 'python')) {
            Write-Fail "python command not found. Install Python or activate your environment."
        }
        else {
            if (-not $NoInstall) {
                Invoke-ScanStep "Install Python scan tools (pip-audit, bandit, semgrep)" {
                    python -m pip install --upgrade pip
                    python -m pip install pip-audit bandit semgrep
                }
            }

            $requirementsPath = Join-Path $repoRoot $PythonRequirements
            if (Test-Path $requirementsPath) {
                Invoke-ScanStep "pip-audit against $PythonRequirements" {
                    pip-audit -r $requirementsPath
                }
            }
            else {
                Write-Warn "Skipped pip-audit: requirements file not found at $PythonRequirements"
            }

            Invoke-ScanStep "Bandit scan for byoint_core" {
                bandit -r (Join-Path $repoRoot 'byoint_core') -f txt
            }

            if (-not $SkipSemgrep) {
                if (-not (Test-CommandExists 'semgrep')) {
                    Write-Fail "semgrep command not found. Re-run without -NoInstall or install semgrep manually."
                }
                else {
                    Invoke-ScanStep "Semgrep OWASP/Python/JavaScript rules" {
                        semgrep --config p/owasp-top-ten --config p/python --config p/javascript $repoRoot
                    }
                }
            }
        }
    }

    if (-not $SkipFrontend) {
        Write-Section "Frontend Dependency Scan"

        $webPath = Join-Path $repoRoot 'byoint-web'
        if (-not (Test-Path $webPath)) {
            Write-Warn "Skipped frontend scan: byoint-web folder not found"
        }
        elseif (-not (Test-CommandExists 'npm')) {
            Write-Fail "npm command not found. Install Node.js/npm to run frontend scans."
        }
        else {
            Push-Location $webPath
            try {
                Invoke-ScanStep "npm install" {
                    npm install
                }
                Invoke-ScanStep "npm audit --audit-level=$NpmAuditLevel" {
                    npm audit --audit-level=$NpmAuditLevel
                }
            }
            finally {
                Pop-Location
            }
        }
    }

    if (-not $SkipTrivy) {
        Write-Section "Trivy Filesystem and Config Scan"

        if (-not (Test-CommandExists 'trivy')) {
            Write-Warn "Skipped Trivy scans: trivy command not found"
        }
        else {
            Invoke-ScanStep "trivy fs" {
                trivy fs $repoRoot
            }
            Invoke-ScanStep "trivy config" {
                trivy config $repoRoot
            }
        }
    }

    if (-not $SkipZap) {
        Write-Section "OWASP ZAP DAST Scan"

        if (-not (Test-CommandExists 'docker')) {
            Write-Fail "docker command not found. Install Docker Desktop to run ZAP scans."
        }
        else {
            $zapVolume = "${repoRoot}:/zap/wrk"
            $ignoreWarnFlag = @()
            if (-not $ZapFailOnWarn) {
                $ignoreWarnFlag = @('-I')
            }

            if ($ZapMode -eq 'baseline') {
                Invoke-ScanStep "ZAP baseline scan against $ZapTarget" {
                    $zapArgs = @(
                        'run', '--rm', '-t',
                        '-v', $zapVolume,
                        $ZapDockerImage,
                        'zap-baseline.py',
                        '-t', $ZapTarget,
                        '-r', 'zap-baseline.html',
                        '-J', 'zap-baseline.json'
                    ) + $ignoreWarnFlag

                    docker @zapArgs
                }
            }
            elseif ($ZapMode -eq 'api') {
                if ([string]::IsNullOrWhiteSpace($ZapApiKey)) {
                    Write-Fail "ZAP API mode requires -ZapApiKey or ZAP_API_KEY environment variable."
                }
                else {
                    Invoke-ScanStep "ZAP API scan against $ZapApiSpecUrl" {
                        $authReplacer = "-config replacer.full_list(0).description=auth -config replacer.full_list(0).enabled=true -config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=Authorization -config replacer.full_list(0).regex=false -config replacer.full_list(0).replacement=Bearer $ZapApiKey"
                        $zapArgs = @(
                            'run', '--rm', '-t',
                            '-v', $zapVolume,
                            $ZapDockerImage,
                            'zap-api-scan.py',
                            '-t', $ZapApiSpecUrl,
                            '-f', 'openapi',
                            '-r', 'zap-api.html',
                            '-J', 'zap-api.json',
                            '-z', $authReplacer
                        ) + $ignoreWarnFlag

                        docker @zapArgs
                    }
                }
            }
            elseif ($ZapMode -eq 'full') {
                Invoke-ScanStep "ZAP full active scan against $ZapTarget" {
                    $zapArgs = @(
                        'run', '--rm', '-t',
                        '-v', $zapVolume,
                        $ZapDockerImage,
                        'zap-full-scan.py',
                        '-t', $ZapTarget,
                        '-r', 'zap-full.html',
                        '-J', 'zap-full.json'
                    ) + $ignoreWarnFlag

                    docker @zapArgs
                }
            }
        }
    }

    Write-Section "Summary"
    if ($script:FailureCount -gt 0) {
        Write-Host "Completed with $script:FailureCount failed step(s)." -ForegroundColor Red
        exit 1
    }

    Write-Host "All enabled scan steps completed successfully." -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
