# Start the dedicated automation Edge used by edge_download.py.
#
# Separate profile from the daily browser, so the debugging port stays open
# and the institutional login (WebVPN / CARSI) persists across runs.
#
# --no-proxy-server is load-bearing: through the system proxy, Cloudflare
# scores the exit IP badly enough that publisher challenges (Elsevier's
# pdf.sciencedirectassets.com in particular) hang at "Request Verification:
# In Progress" forever. Direct, the same URL downloads instantly.
#
# Switch names are single-dash + underscore, matching edge_download.py, so the
# two sides read the same in bash, PowerShell and argparse.
param(
    [int]$port = 9333,
    # Every bit of local state this skill keeps, under one root:
    #   <data_dir>\profile   Edge --user-data-dir; your institutional session
    #   <data_dir>\download  where Edge drops downloaded files
    # edge_download.py takes the same -data_dir and expects the same two names.
    [string]$data_dir = "$env:USERPROFILE\.pj\p-literature-download",
    # Landing page of your own institution's WebVPN / SSO. Only a convenience:
    # log in here once and the cookie stays in this profile. Leave at the
    # default if your institution needs no VPN.
    [string]$login_url = "about:blank"
)

### check, to here ###

# Edge installs to Program Files (x86) on most machines and Program Files on
# some; check both rather than failing with a bare "command not found".
$path_edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $path_edge) {
    Write-Host "❌ ERROR: 找不到 msedge.exe，请确认已安装 Microsoft Edge。"
    exit 1
}

### prepare, to here ###

$path_profile  = Join-Path $data_dir "profile"
$path_download = Join-Path $data_dir "download"
$path_prefs    = Join-Path $path_profile "Default\Preferences"
New-Item -ItemType Directory -Force -Path $path_download | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $path_prefs) | Out-Null

# The download directory must be written while Edge is stopped, immediately
# before launching, or a shutdown flush reverts it. always_open_pdf_externally
# is deliberately NOT set here: it is a protected preference that Edge
# restores on startup regardless, so edge_download.py fetches PDFs from inside
# the page instead of relying on it.
while (Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
        Where-Object { $_.CommandLine -like "*$path_profile*" }) {
    Start-Sleep -Milliseconds 500
}

# A brand-new profile has no Preferences file yet, so this has to seed one
# rather than skip. Skipping is what silently leaves downloads going to the
# user's real Downloads folder, where edge_download.py never looks - the
# Elsevier tier and the manual-download takeover then fail for no visible
# reason. Edge fills in every other preference on first launch.
$dict_prefs = if (Test-Path $path_prefs) {
    [System.IO.File]::ReadAllText($path_prefs) | ConvertFrom-Json
} else {
    [pscustomobject]@{}
}
if (-not $dict_prefs.download) { $dict_prefs | Add-Member download ([pscustomobject]@{}) -Force }
if (-not $dict_prefs.savefile) { $dict_prefs | Add-Member savefile ([pscustomobject]@{}) -Force }
$dict_prefs.download | Add-Member prompt_for_download $false          -Force
$dict_prefs.download | Add-Member default_directory   $path_download  -Force
$dict_prefs.savefile | Add-Member default_directory   $path_download  -Force
# UTF-8 with NO byte-order mark. Set-Content -Encoding utf8 emits a BOM on
# Windows PowerShell 5.1, and Chromium writes this file without one; a BOM
# makes it a JSON parse error for anything that reads it back as plain utf-8.
[System.IO.File]::WriteAllText(
    $path_prefs,
    ($dict_prefs | ConvertTo-Json -Depth 100 -Compress),
    (New-Object System.Text.UTF8Encoding $false))

### main, to here ###

Write-Host "================ 📁 专用自动化 Edge"
Write-Host "📍 data_dir  : $data_dir"
Write-Host "📍 profile   : $path_profile"
Write-Host "📍 download  : $path_download"
Write-Host "📍 CDP       : http://127.0.0.1:$port"
Write-Host "▶️  启动 $path_edge"

& $path_edge --remote-debugging-port=$port --user-data-dir=$path_profile --no-proxy-server `
    --no-first-run --no-default-browser-check $login_url
