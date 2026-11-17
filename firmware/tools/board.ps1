<#
.SYNOPSIS
Inspect, monitor, back up or reset an ESP32 using repo-local mpremote.
.DESCRIPTION
mpremote exec enters raw REPL and interrupts the application with Ctrl+C.
If watchdog_s > 0, the hardware WDT remains active and may reset the board
during these operations. Use watchdog_s: 0 while developing.
.EXAMPLE
powershell -File firmware/tools/board.ps1 info -Port COM3
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Position = 0)]
    [ValidateSet("ports", "monitor", "info", "scan", "backup", "reset")]
    [string]$Command = "info",
    [string]$Port = "COM3"
)
$ErrorActionPreference = "Stop"
$firmwareRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $firmwareRoot
$remoteExe = Join-Path $repoRoot ".venv/Scripts/mpremote.exe"
if (-not $PSCmdlet.ShouldProcess($Port, "mpremote $Command")) { return }
if (-not (Test-Path -LiteralPath $remoteExe -PathType Leaf)) {
    throw "Missing mpremote: $remoteExe. Use the repository's .venv/Scripts tools."
}

function Invoke-Remote {
    param([string[]]$RemoteArgs)
    & $remoteExe @RemoteArgs
    if ($LASTEXITCODE -ne 0) { throw "mpremote failed (exit $LASTEXITCODE)" }
}

if ($Command -eq "ports") {
    Invoke-Remote -RemoteArgs @("connect", "list")
    return
}
Write-Host "mpremote exec interrupts the app (Ctrl+C). An active WDT can still reset the board; use watchdog_s: 0."
switch ($Command) {
    "monitor" {
        Write-Host "Serial REPL/log: press Ctrl+] to exit; Ctrl+C interrupts the running app."
        Invoke-Remote -RemoteArgs @("connect", $Port, "repl")
    }
    "reset" {
        Invoke-Remote -RemoteArgs @("connect", $Port, "reset")
    }
    "info" {
        $code = @'
import os, sys, machine, binascii, json
print('hw_id:', binascii.hexlify(machine.unique_id()).decode())
print('MicroPython:', sys.version)
stats = os.statvfs('/')
print('free_bytes:', stats[0] * stats[3])
for directory in ('/', '/app'):
 try:
  print('files', directory, ':', os.listdir(directory))
 except OSError:
  print(directory, ': unavailable')
for path in ('/device.json', '/config.json'):
 try:
  os.stat(path)
 except OSError:
  print(path, ': absent')
 else:
  print(path, ': present')
  if path == '/device.json':
   try:
    with open(path) as stream:
     device = json.load(stream)
    print('device_id:', device.get('device_id'))
   except (OSError, ValueError, AttributeError):
    print('device_id: unreadable')
for path in ('/state.json', '/ota.json'):
 try:
  with open(path) as stream:
   print(path, ':', stream.read())
 except OSError:
  print(path, ': absent or unreadable')
'@
        Invoke-Remote -RemoteArgs @("connect", $Port, "exec", $code)
    }
    "scan" {
        $code = @'
import network
wlan = network.WLAN(network.STA_IF)
was_active = wlan.active()
try:
 wlan.active(True)
 for entry in wlan.scan():
  print('SSID:', entry[0].decode('utf-8', 'replace'), 'RSSI:', entry[3])
finally:
 if not was_active:
  wlan.active(False)
'@
        Invoke-Remote -RemoteArgs @("connect", $Port, "exec", $code)
    }
    "backup" {
        # One raw-REPL session; capture the transfer output so secrets never reach the console.
        $code = @'
import binascii
for name in ('device.json', 'state.json', 'config.json', 'ota.json'):
 try:
  with open('/' + name, 'rb') as stream:
   data = stream.read()
 except OSError as exc:
  if exc.args[0] != 2:
   raise
  print('MISSING', name)
 else:
  print('BACKUP', name, binascii.b2a_base64(data).decode().strip())
'@
        $output = @(Invoke-Remote -RemoteArgs @("connect", $Port, "exec", $code))
        $names = @("device.json", "state.json", "config.json", "ota.json")
        $files = @{}
        $missing = @()
        foreach ($line in $output) {
            if ($line -match '^BACKUP (device|state|config|ota)\.json (.*)$') {
                $name = $Matches[1] + ".json"
                $files[$name] = [Convert]::FromBase64String($Matches[2])
            } elseif ($line -match '^MISSING (device|state|config|ota)\.json$') {
                $missing += $Matches[1] + ".json"
            }
        }
        foreach ($name in $names) {
            if (-not $files.ContainsKey($name) -and $name -notin $missing) {
                throw "Incomplete backup transfer; no files saved."
            }
        }
        $destination = Join-Path $firmwareRoot ("bin/board_backups/" + (Get-Date -Format "yyyyMMdd_HHmmss"))
        New-Item -ItemType Directory -Path $destination | Out-Null
        foreach ($name in $names) {
            if ($files.ContainsKey($name)) {
                [IO.File]::WriteAllBytes((Join-Path $destination $name), $files[$name])
                Write-Host "Saved $name"
            } else {
                Write-Host "Skipped absent $name"
            }
        }
        Write-Host "Backup: $destination (contains passwords; keep private)."
    }
}
