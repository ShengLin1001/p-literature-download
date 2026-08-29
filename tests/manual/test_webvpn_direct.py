#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test WebVPN HTTP download directly with saved cookies."""
import sys
import os
import json
import requests
import urllib3
urllib3.disable_warnings()

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load cookies
cookie_file = os.path.expanduser("~/.scansci-pdf/cache/instsci_cookies.json")
with open(cookie_file) as f:
    cookies_data = json.load(f)

cookies = {c["name"]: c["value"] for c in cookies_data}
print(f"Loaded {len(cookies)} cookies")

# Test: Access WebVPN portal
test_url = "https://webvpn.zju.edu.cn"
print(f"\nTest 1: Access WebVPN portal (check if session is valid)")
try:
    resp = requests.get(test_url, cookies=cookies, verify=False, timeout=15, allow_redirects=False)
    if "/login" in resp.headers.get("Location", "") or "/login" in resp.url:
        print(f"  Status: {resp.status_code} -> NOT LOGGED IN (redirected to login)")
    else:
        print(f"  Status: {resp.status_code} -> Session appears valid!")
except Exception as e:
    print(f"  Error: {e}")

# Test 2: Try to access a publisher through the network proxy
# The user has network_proxy = http://127.0.0.1:7897 (v2rayN TUN)
print(f"\nTest 2: Access APS via proxy (check institutional access)")
proxies = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
doi = "10.1103/PhysRevB.88.064104"
url = f"https://doi.org/{doi}"
try:
    resp = requests.get(url, proxies=proxies, verify=False, timeout=15, allow_redirects=True, stream=True)
    resp.close()
    print(f"  Resolved URL: {resp.url[:80]}")
    print(f"  Status: {resp.status_code}")
except Exception as e:
    print(f"  Error: {e}")

# Test 3: Try CARSI federation access
print(f"\nTest 3: Check CARSI cookies")
carsi_cookie_dir = os.path.expanduser("~/.scansci-pdf/cache")
carsi_files = [f for f in os.listdir(carsi_cookie_dir) if "carsi" in f.lower()] if os.path.isdir(carsi_cookie_dir) else []
print(f"  CARSI files: {carsi_files}")

# Test 4: Try direct publisher access with proxy for various publishers
print(f"\nTest 4: Direct publisher access tests (with proxy)")
tests = [
    ("10.1103/PhysRevB.88.064104", "APS"),
    ("10.1002/adma.73337", "Wiley"),
    ("10.1021/jacs.5c20581", "ACS"),
    ("10.1063/5.0316442", "AIP"),
    ("10.1088/1361-648x/ae62e5", "IOP"),
    ("10.1093/nar/gkag457", "Oxford"),
    ("10.1109/tit.2026.3670320", "IEEE"),
    ("10.1145/3806644", "ACM"),
    ("10.1146/annurev.psych.52.1.1", "Annual Reviews"),
]
for doi, name in tests:
    url = f"https://doi.org/{doi}"
    try:
        resp = requests.get(url, proxies=proxies, verify=False, timeout=10, allow_redirects=True, stream=True)
        resp.close()
        final_url = resp.url
        status = resp.status_code
        # Check if Cloudflare challenge
        cf = "challenges.cloudflare.com" in resp.headers.get("server", "") or "cloudflare" in resp.headers.get("server", "")
        print(f"  {name:20s} {status} CF={cf} {final_url[:70]}")
    except Exception as e:
        print(f"  {name:20s} ERROR: {e}")
