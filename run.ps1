# run.ps1 — one-command LOCAL launcher: (optionally) build the SPA, then boot serve.py.
#
# Usage:
#   .\run.ps1                       # build the SPA if missing, boot auth-ON on 127.0.0.1:8000
#   .\run.ps1 -Rebuild              # force an SPA rebuild first
#   .\run.ps1 -Port 9000            # custom port
#   .\run.ps1 -AuthOff              # DISABLE auth (loopback only) — for quick local clicking
#   .\run.ps1 -AuthOff -AllowUnsafeLan   # required to combine auth-off with a non-loopback bind
#
# Safe by default: auth is ON, the bind is loopback (127.0.0.1), and a frontend build failure aborts the
# launch (so we never serve a stale/half-built SPA). For LAN exposure use serve_lan.ps1 (sets 0.0.0.0).
param(
    [int]$Port = 8000,
    [switch]$Rebuild,
    [switch]$AuthOff,
    [switch]$AllowUnsafeLan,
    [string]$BindHost = "127.0.0.1"
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$isLoopback = ($BindHost -eq "127.0.0.1" -or $BindHost -eq "localhost")

# --- safety: auth-off must stay loopback unless the operator explicitly accepts the risk ----------------
if ($AuthOff -and -not $isLoopback -and -not $AllowUnsafeLan) {
    Write-Host "REFUSING: -AuthOff with a non-loopback bind ($BindHost) exposes the app with NO auth." -ForegroundColor Red
    Write-Host "Re-run with -AllowUnsafeLan if you really mean it (trusted network only)." -ForegroundColor Red
    exit 1
}
if ($AuthOff) {
    Write-Host "WARNING: authentication is DISABLED (AUTH_ENABLED=0). Anyone who can reach $BindHost:$Port has full read access." -ForegroundColor Yellow
    $env:AUTH_ENABLED = "0"
}

# --- port-in-use check (don't silently start a second server / fight an occupied port) ------------------
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    Write-Host "Port $Port is already in use — stop the other server or pass -Port <n>." -ForegroundColor Red
    exit 1
}

# --- build the SPA (force with -Rebuild, else only when frontend/dist is missing) -----------------------
$distIndex = Join-Path $root "frontend/dist/index.html"
if ($Rebuild -or -not (Test-Path $distIndex)) {
    Write-Host "Building the SPA (npm ci + npm run build)…" -ForegroundColor Cyan
    Push-Location (Join-Path $root "frontend")
    try {
        npm ci; if (-not $?) { throw "npm ci failed" }
        npm run build; if (-not $?) { throw "npm run build failed" }
    } finally { Pop-Location }
    if (-not (Test-Path $distIndex)) { Write-Host "Build did not produce frontend/dist — aborting." -ForegroundColor Red; exit 1 }
} else {
    Write-Host "SPA already built (frontend/dist present) — use -Rebuild to force a rebuild." -ForegroundColor DarkGray
}

$env:API_HOST = $BindHost
$env:API_PORT = "$Port"

Write-Host ""
Write-Host ("Starting serve.py on http://{0}:{1}/  (auth {2})" -f $BindHost, $Port, ($(if ($AuthOff) { "OFF" } else { "ON" }))) -ForegroundColor Green
Write-Host "SPA at /  ·  NiceGUI dashboard at /dashboard  ·  /healthz  ·  Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""
python serve.py
