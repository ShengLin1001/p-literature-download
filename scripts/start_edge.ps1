# Start the dedicated automation Edge used by edge_download.py.
#
# Separate profile from the daily browser, so the debugging port stays open
# and the institutional login (WebVPN / CARSI) persists across runs.
#
# --no-proxy-server is load-bearing: through the system proxy, Cloudflare
# scores the exit IP badly enough that publisher challenges (Elsevier's
# pdf.sciencedirectassets.com in particular) hang at "Request Verification:
# In Progress" forever. Direct, the same URL downloads instantly.
param(
    [int]$Port = 9333,
    [string]$ProfileDir = "$env:USERPROFILE\.pj\p-literature-download\profile",
    # Where Edge drops files it downloads. edge_download.py reads this back out
    # of the profile, so changing it here is enough - do not also hard-code it
    # on the Python side.
    [string]$DownloadDir = "$env:USERPROFILE\.pj\p-literature-download\downloads",
    # Landing page of your own institution's WebVPN / SSO. Only a convenience:
    # log in here once and the cookie stays in this profile. Leave at the
    # default if your institution needs no VPN.
    [string]$LoginUrl = "about:blank"
)

# Edge installs to Program Files (x86) on most machines and Program Files on
# some; check both rather than failing with a bare "command not found".
$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) {
    Write-Error "找不到 msedge.exe，请确认已安装 Microsoft Edge。"
    exit 1
}

$prefsFile = Join-Path $ProfileDir "Default\Preferences"
New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $prefsFile) | Out-Null

# The download directory must be written while Edge is stopped, immediately
# before launching, or a shutdown flush reverts it. always_open_pdf_externally
# is deliberately NOT set here: it is a protected preference that Edge
# restores on startup regardless, so edge_download.py fetches PDFs from inside
# the page instead of relying on it.
while (Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
        Where-Object { $_.CommandLine -like "*$ProfileDir*" }) {
    Start-Sleep -Milliseconds 500
}

# A brand-new profile has no Preferences file yet, so this has to seed one
# rather than skip. Skipping is what silently leaves downloads going to the
# user's real Downloads folder, where edge_download.py never looks - the
# Elsevier tier and the manual-download takeover then fail for no visible
# reason. Edge fills in every other preference on first launch.
$p = if (Test-Path $prefsFile) {
    Get-Content $prefsFile -Raw | ConvertFrom-Json
} else {
    [pscustomobject]@{}
}
if (-not $p.download) { $p | Add-Member download ([pscustomobject]@{}) -Force }
if (-not $p.savefile) { $p | Add-Member savefile ([pscustomobject]@{}) -Force }
$p.download | Add-Member prompt_for_download        $false        -Force
$p.download | Add-Member default_directory          $DownloadDir  -Force
$p.savefile | Add-Member default_directory          $DownloadDir  -Force
# UTF-8 with NO byte-order mark. Set-Content -Encoding utf8 emits a BOM on
# Windows PowerShell 5.1, and Chromium writes this file without one; a BOM
# makes it a JSON parse error for anything that reads it back as plain utf-8.
[System.IO.File]::WriteAllText(
    $prefsFile,
    ($p | ConvertTo-Json -Depth 100 -Compress),
    (New-Object System.Text.UTF8Encoding $false))

Write-Host "profile   : $ProfileDir"
Write-Host "downloads : $DownloadDir"
Write-Host "CDP       : http://127.0.0.1:$Port"

& $edge --remote-debugging-port=$Port --user-data-dir=$ProfileDir --no-proxy-server `
    --no-first-run --no-default-browser-check $LoginUrl
