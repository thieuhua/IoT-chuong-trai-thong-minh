<#
.SYNOPSIS
Erase an ESP32 and flash MicroPython; requires typing yes unless -Force is set.
Auto-downloads the pinned MicroPython binary into firmware/bin/ if none is found locally.
.EXAMPLE
powershell -File firmware/tools/flash_micropython.ps1 -Port COM3 -WhatIf
.EXAMPLE
powershell -File firmware/tools/flash_micropython.ps1 -Bin firmware/bin/ESP32_GENERIC-example.bin -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Port = "COM3",
    [string]$Bin,
    [ValidateRange(1, 4000000)]
    [int]$Baud = 460800,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$defaultBinName = "ESP32_GENERIC-20260824-v1.29.0.bin"
$defaultBinUrl = "https://micropython.org/resources/firmware/$defaultBinName"
$defaultBinSha256 = "e67ad6015a0a504c1fec9aa9bbf589d0432ed28e62546f4f8dd8a147f8bd95f6"

$firmwareRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $firmwareRoot
$esptoolExe = Join-Path $repoRoot ".venv/Scripts/esptool.exe"
$needsDownload = $false
if ($Bin) {
    $binPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Bin)
} else {
    $binRoot = Join-Path $firmwareRoot "bin"
    $latest = Get-ChildItem -LiteralPath $binRoot -Filter "ESP32_GENERIC-*.bin" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) {
        $binPath = $latest.FullName
    } else {
        $binPath = Join-Path $binRoot $defaultBinName
        $needsDownload = $true
    }
}
$commonArgs = @("--chip", "esp32", "--port", $Port, "--baud", "$Baud")
$eraseArgs = $commonArgs + @("erase-flash")
$writeArgs = $commonArgs + @("write-flash", "-z", "0x1000", $binPath)
if ($needsDownload) {
    Write-Host "No local firmware/bin/ESP32_GENERIC-*.bin found; will download:"
    Write-Host "  $defaultBinUrl -> $binPath"
}
Write-Host ('"{0}" {1}' -f $esptoolExe, ($eraseArgs -join ' '))
Write-Host ('"{0}" {1} "{2}"' -f $esptoolExe, (($commonArgs + @("write-flash", "-z", "0x1000")) -join ' '), $binPath)
Write-Host "After flashing, run: powershell -File firmware/tools/deploy.ps1 -Port $Port -Config"
Write-Host "All board data will be erased. The board must register again and be approved."
if ($WhatIfPreference) {
    $null = $PSCmdlet.ShouldProcess($Port, "Erase flash and install MicroPython")
    return
}
if (-not (Test-Path -LiteralPath $esptoolExe -PathType Leaf)) {
    throw "Missing esptool: $esptoolExe. Use the repository's .venv/Scripts tools."
}
if (-not $needsDownload -and -not (Test-Path -LiteralPath $binPath -PathType Leaf)) {
    throw "Missing MicroPython binary: $binPath"
}
if (-not $Force) {
    $answer = Read-Host "This erases the ENTIRE board. Type yes to continue"
    if ($answer -cne "yes") { throw "Flash cancelled; nothing was erased." }
}
if (-not $PSCmdlet.ShouldProcess($Port, "Erase flash and install MicroPython")) { return }
if ($needsDownload) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $binPath) -Force | Out-Null
    $tmpPath = "$binPath.tmp"
    Write-Host "Downloading $defaultBinName..."
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $defaultBinUrl -OutFile $tmpPath -UseBasicParsing
        $actualHash = (Get-FileHash -LiteralPath $tmpPath -Algorithm SHA256).Hash.ToLower()
        if ($actualHash -ne $defaultBinSha256) {
            throw "SHA-256 mismatch for $defaultBinName (expected $defaultBinSha256, got $actualHash)."
        }
        Move-Item -LiteralPath $tmpPath -Destination $binPath -Force
        Write-Host "Downloaded and verified $binPath"
    } catch {
        Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue
        throw
    }
}
& $esptoolExe @eraseArgs
if ($LASTEXITCODE -ne 0) { throw "esptool erase-flash failed (exit $LASTEXITCODE); flash stopped." }
& $esptoolExe @writeArgs
if ($LASTEXITCODE -ne 0) { throw "esptool write-flash failed (exit $LASTEXITCODE); retry flashing." }
Write-Host "MicroPython flashed successfully. Deploy with -Config, then approve the new registration."
