# Accessing the dashboard from another computer on the same network

By default `python serve.py` binds to `127.0.0.1` (loopback) — it is only reachable from the **same
machine**. To let another computer on the same local network open the dashboard, bind to all network
interfaces and open the firewall port. Nothing in the code needs editing — it's driven by two
environment variables and one firewall rule.

> ⚠️ **No authentication.** This dashboard has no login. Only expose it on a network you trust
> (your home/office LAN), never directly on the public internet.

## 1. Find this machine's LAN IP address

On the machine that will run the server (PowerShell):

```powershell
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1'
}).IPAddress
```

You'll get something like `192.168.1.42`. That's the address other computers will use.

## 2. Set the storage secret (REQUIRED when exposing beyond loopback)

NiceGUI signs its per-session cookie with a secret. The built-in fallback is a clearly-labelled
dev-only value, so **`serve.py` refuses to start** when you bind a non-loopback host (e.g.
`API_HOST=0.0.0.0`) without a real secret:

```powershell
$env:NICEGUI_STORAGE_SECRET = "pick-any-long-random-string-here"
# generate one: python -c "import secrets; print(secrets.token_hex(32))"
```

For a quick test on a trusted LAN you can override the refusal and run with the dev fallback secret:

```powershell
$env:ALLOW_DEV_STORAGE_SECRET_ON_LAN = "1"   # the server starts, but prints a loud warning
```

Don't leave the override on for anything you keep running — set a real `NICEGUI_STORAGE_SECRET` instead.
(Loopback `127.0.0.1`, the default, needs neither.)

## 3. Bind to all interfaces and start the server

```powershell
$env:API_HOST = "0.0.0.0"      # bind every interface (default is 127.0.0.1, loopback only)
# $env:API_PORT = "8000"       # optional; 8000 is the default
python serve.py
```

The server prints the URL and a reminder of the LAN address. (Or just run `.\serve_lan.ps1`, which sets
these for you and prints the reachable URLs.)

## 4. Allow the port through Windows Firewall (one-time)

Inbound connections on the port (default **8000**) must be allowed. Run **once**, in an
**Administrator** PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Kalshi dashboard (8000)" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private
```

`-Profile Private` restricts the rule to networks you've marked Private (home/work) — keep it off
Public Wi-Fi. To remove it later:

```powershell
Remove-NetFirewallRule -DisplayName "Kalshi dashboard (8000)"
```

## 5. Open it from the other computer

In a browser on any computer on the same network:

```
http://<this-machine-LAN-IP>:8000
```

e.g. `http://192.168.1.42:8000`. The REST API (`/opportunities`, `/docs`, …) is reachable at the
same host/port.

## Troubleshooting

- **`serve.py` exits immediately with "Refusing to bind …"** — you bound a non-loopback host without
  `NICEGUI_STORAGE_SECRET`. Set it (step 2), or set `ALLOW_DEV_STORAGE_SECRET_ON_LAN=1` for a trusted-LAN
  test.
- **Page won't load from the other computer** — confirm step 4 (firewall) ran as Administrator, that
  both machines are on the *same* network/subnet, and that `API_HOST=0.0.0.0` was set in the **same**
  PowerShell session that launched `serve.py` (env vars don't carry across windows).
- **Loads on the server machine but not elsewhere** — you're still bound to loopback. Re-check
  `$env:API_HOST` is `0.0.0.0` in the session running the server.
- **Multiple viewers** — the dashboard reads from the shared in-process snapshot store, so several
  people can watch at once. The Kalshi request throttle is process-wide, so extra viewers don't
  increase the API request rate (only a "Scan now" triggers fetches). Run a **single** worker — the
  store and throttle are process-local, so multiple workers would fragment them.
- **Reverting to loopback-only** — just unset the variable (`Remove-Item Env:\API_HOST`) or open a
  fresh PowerShell window and run `python serve.py` normally.
