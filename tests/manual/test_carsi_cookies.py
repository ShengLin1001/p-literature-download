#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test CARSI cookie-based download for APS and other paywalled publishers."""
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

# Load CARSI cookies for APS
carsi_dir = os.path.expanduser("~/.scansci-pdf/cache/carsi_cookies")

# Test 1: APS with CARSI cookies
print("=== Test 1: APS with CARSI cookies ===")
with open(os.path.join(carsi_dir, "aps.json")) as f:
    aps_cookies_list = json.load(f)
print(f"APS cookies: {len(aps_cookies_list)}")
for c in aps_cookies_list:
    print(f"  {c['name']}: domain={c.get('domain', '?')} value={str(c.get('value', ''))[:40]}")

# Convert to dict
aps_cookies = {c["name"]: c["value"] for c in aps_cookies_list}

# Try to access an APS article
doi = "10.1103/PhysRevB.88.064104"
url = f"https://journals.aps.org/prb/abstract/{doi}"
print(f"\nAccessing: {url}")
try:
    resp = requests.get(url, cookies=aps_cookies, verify=False, timeout=15, allow_redirects=True)
    print(f"  Status: {resp.status_code}")
    print(f"  Final URL: {resp.url[:80]}")
    print(f"  Server: {resp.headers.get('server', '?')}")
    body = resp.text
    print(f"  Body length: {len(body)}")
    # Check if Cloudflare
    if "just a moment" in body.lower() or "challenge-platform" in body.lower():
        print("  -> Cloudflare challenge page (cookies don't help with CF)")
    elif "Sign in via your Institution" in body or "Institution" in body:
        print("  -> Paywall (not authenticated)")
    else:
        print(f"  -> Content looks accessible!")
        # Look for PDF link
        import re
        pdf_match = re.search(r'href="([^"]*pdf[^"]*)"', body, re.I)
        if pdf_match:
            print(f"  PDF link: {pdf_match.group(1)[:80]}")
except Exception as e:
    print(f"  Error: {e}")

# Try the PDF URL directly
pdf_url = f"https://journals.aps.org/prb/pdf/{doi}"
print(f"\nDirect PDF URL: {pdf_url}")
try:
    resp = requests.get(pdf_url, cookies=aps_cookies, verify=False, timeout=15, allow_redirects=True, stream=True)
    print(f"  Status: {resp.status_code}")
    print(f"  Content-Type: {resp.headers.get('content-type', '?')}")
    first = next(resp.iter_content(1024), b"")
    print(f"  First bytes: {first[:20]}")
    print(f"  Is PDF: {first[:5] == b'%PDF-'}")
    resp.close()
except Exception as e:
    print(f"  Error: {e}")

# Test 2: Try without proxy (proxy is down)
print("\n=== Test 2: DOI resolution without proxy ===")
try:
    resp = requests.get(f"https://doi.org/{doi}", verify=False, timeout=10, allow_redirects=True, stream=True)
    resp.close()
    print(f"  Resolved URL: {resp.url}")
    print(f"  Status: {resp.status_code}")
except Exception as e:
    print(f"  Error: {e}")

# Test 3: ScienceDirect with CARSI cookies (should work via API instead)
print("\n=== Test 3: ScienceDirect CARSI cookies ===")
with open(os.path.join(carsi_dir, "sciencedirect.json")) as f:
    sd_cookies_list = json.load(f)
print(f"ScienceDirect cookies: {len(sd_cookies_list)}")
sd_cookies = {c["name"]: c["value"] for c in sd_cookies_list}

# Try a ScienceDirect article
doi2 = "10.1016/j.commatsci.2018.12.013"
url2 = f"https://www.sciencedirect.com/science/article/pii/S0927025618307708"
print(f"\nAccessing: {url2}")
try:
    resp = requests.get(url2, cookies=sd_cookies, verify=False, timeout=15, allow_redirects=True)
    print(f"  Status: {resp.status_code}")
    body = resp.text
    if "just a moment" in body.lower():
        print("  -> Cloudflare challenge")
    elif len(body) > 5000:
        print(f"  -> Content accessible ({len(body)} bytes)")
    else:
        print(f"  -> Short response ({len(body)} bytes)")
except Exception as e:
    print(f"  Error: {e}")
