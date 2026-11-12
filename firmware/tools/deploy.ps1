param([string]$Port = "COM3", [switch]$Config, [switch]$Wipe)
# Copy firmware/src to the board root in ONE mpremote session (each new connection resets the
# board), verify every file by SHA-256, then reset so main.py starts.
$ErrorActionPreference = "Stop"
$firmwareRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $firmwareRoot
$remoteExe = Join-Path $repoRoot ".venv/Scripts/mpremote.exe"
$sourceRoot = Join-Path $firmwareRoot "src"
if (-not (Test-Path -LiteralPath $remoteExe)) { throw "Missing $remoteExe" }
if ($Config -and -not (Test-Path -LiteralPath (Join-Path $sourceRoot "config.json"))) {
    throw "Copy firmware/config.example.json to firmware/src/config.json and edit it first."
}

$files = @(Get-ChildItem -LiteralPath $sourceRoot -Filter "*.py" -File -Recurse | ForEach-Object {
    [pscustomobject]@{ Local = $_.FullName; Remote = "/" + $_.FullName.Substring($sourceRoot.Length + 1).Replace('\', '/') }
})
if ($Config) {
    $files += [pscustomobject]@{ Local = (Join-Path $sourceRoot "config.json"); Remote = "/config.json" }
}

$remoteArgs = @("connect", $Port)
# Runtime files are removed only when the operator explicitly uses -Wipe.
if ($Wipe) {
    $remoteArgs += @("exec", "import os`nfor p in ('/device.json', '/state.json'):`n try:`n  os.remove(p)`n except OSError as e:`n  if e.args[0] != 2: raise", "+")
}
# Every package directory under src/ (core, sensors, actuators, ...) must exist before copying.
$dirs = @($files | ForEach-Object { $_.Remote.Substring(0, $_.Remote.LastIndexOf('/')) } |
    Where-Object { $_ } | Sort-Object -Unique | ForEach-Object { "'" + $_ + "'" })
if ($dirs.Count -gt 0) {
    # Build the string first: inside @(...) the comma binds tighter than +.
    $mkdir = "import os`nfor p in (" + ($dirs -join ",") + ",):`n try:`n  os.mkdir(p)`n except OSError as e:`n  if e.args[0] != 17: raise"
    $remoteArgs += @("exec", $mkdir, "+")
}
foreach ($file in $files) {
    $remoteArgs += @("fs", "cp", $file.Local, (":" + $file.Remote), "+")
}
$paths = ($files | ForEach-Object { "'" + $_.Remote + "'" }) -join ","
$verify = "import hashlib,binascii`nfor f in ($paths,):`n h=hashlib.sha256()`n with open(f,'rb') as x:`n  while True:`n   b=x.read(512)`n   if not b: break`n   h.update(b)`n print('SHA', f, binascii.hexlify(h.digest()).decode())"
$remoteArgs += @("exec", $verify)

$output = & $remoteExe @remoteArgs
if ($LASTEXITCODE -ne 0) {
    $output | Select-Object -Last 15 | ForEach-Object { Write-Host $_ }
    throw "mpremote failed (exit $LASTEXITCODE)"
}

$remoteHashes = @{}
foreach ($line in $output) {
    if ($line -match '^SHA (/\S+) ([0-9a-f]{64})\s*$') { $remoteHashes[$Matches[1]] = $Matches[2] }
}
$bad = @($files | Where-Object {
    $remoteHashes[$_.Remote] -ne (Get-FileHash -LiteralPath $_.Local -Algorithm SHA256).Hash.ToLower()
})
if ($bad.Count -gt 0) {
    throw ("Hash mismatch (serial noise?), run deploy again: " + (($bad | ForEach-Object Remote) -join ", "))
}
Write-Host ("Verified {0} files on {1}" -f $files.Count, $Port)

# Windows may not have released the port from the previous mpremote process yet.
$ErrorActionPreference = "Continue"
for ($attempt = 1; $attempt -le 5; $attempt++) {
    Start-Sleep -Milliseconds 800
    & $remoteExe connect $Port reset 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "Board reset; firmware starting."; exit 0 }
}
throw "Files are on the board but reset failed; press the RESET button."
