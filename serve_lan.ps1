# serve_lan.ps1 — launch the dashboard so other computers on the SAME network can open it.
#
# Usage:   .\serve_lan.ps1            # binds 0.0.0.0:8000
#          .\serve_lan.ps1 -Port 9000 # custom port
#
# This binds to every network interface (0.0.0.0). The default `python serve.py` binds loopback-only
# (127.0.0.1) and is NOT reachable from other machines — that default is intentional. See
# docs/LAN_ACCESS.md for the full setup, incl. the one-time Windows Firewall rule (required) and the
# eduroam/public-network caveats. No auth: only do this on a network you trust.

param(
    [int]$Port = 8000
)

# Expose on all interfaces (LAN-reachable). Scoped to this process only.
$env:API_HOST = "0.0.0.0"
$env:API_PORT = "$Port"

# NiceGUI signs its session cookie with this secret, and serve.py REFUSES to bind a non-loopback host
# without one (set NICEGUI_STORAGE_SECRET, or ALLOW_DEV_STORAGE_SECRET_ON_LAN=1 to override). Generate a
# random one per launch if you haven't set a stable one yourself (sessions reset on restart — fine for a
# single-user dashboard).
if (-not $env:NICEGUI_STORAGE_SECRET) {
    $env:NICEGUI_STORAGE_SECRET = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
}

# Show the LAN URL(s) so you know what to type on the other computer.
Write-Host ""
Write-Host "Starting dashboard on 0.0.0.0:$Port" -ForegroundColor Cyan
Write-Host "Open it from another computer on the same network at one of:" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1' -and $_.InterfaceAlias -notlike '*VPN*' } |
    ForEach-Object { Write-Host ("   http://{0}:{1}" -f $_.IPAddress, $Port) -ForegroundColor Green }
Write-Host "(Ctrl+C to stop. Firewall rule must allow inbound TCP $Port — see docs/LAN_ACCESS.md.)" -ForegroundColor DarkGray
Write-Host ""

python serve.py
