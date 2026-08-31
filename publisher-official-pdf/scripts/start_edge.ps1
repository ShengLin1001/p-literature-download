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
    [string]$ProfileDir = "$env:USERPROFILE\edge-automation"
)

$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$downloads = Join-Path $ProfileDir "downloads"
$prefsFile = Join-Path $ProfileDir "Default\Preferences"
New-Item -ItemType Directory -Force -Path $downloads | Out-Null

# The download directory must be written while Edge is stopped, immediately
# before launching, or a shutdown flush reverts it. always_open_pdf_externally
# is deliberately NOT set here: it is a protected preference that Edge
# restores on startup regardless, so edge_download.py fetches PDFs from inside
# the page instead of relying on it.
while (Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
        Where-Object { $_.CommandLine -like "*$ProfileDir*" }) {
    Start-Sleep -Milliseconds 500
}

if (Test-Path $prefsFile) {
    $p = Get-Content $prefsFile -Raw | ConvertFrom-Json
    if (-not $p.download) { $p | Add-Member download ([pscustomobject]@{}) -Force }
    if (-not $p.savefile) { $p | Add-Member savefile ([pscustomobject]@{}) -Force }
    $p.download | Add-Member prompt_for_download        $false      -Force
    $p.download | Add-Member default_directory          $downloads  -Force
    $p.savefile | Add-Member default_directory          $downloads  -Force
    $p | ConvertTo-Json -Depth 100 -Compress | Set-Content $prefsFile -Encoding utf8 -NoNewline
}

& $edge --remote-debugging-port=$Port --user-data-dir=$ProfileDir --no-proxy-server `
    --no-first-run --no-default-browser-check "https://webvpn.zju.edu.cn/"
