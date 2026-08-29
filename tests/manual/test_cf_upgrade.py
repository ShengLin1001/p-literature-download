#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test upgraded CloakBrowser 0.5.9 against Cloudflare-protected publishers."""
import time
import sys

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import cloakbrowser
print(f"CloakBrowser {cloakbrowser.__version__} (chromium {cloakbrowser.CHROMIUM_VERSION})")

from cloakbrowser import launch

browser = launch(headless=False, humanize=True, args=["--disable-features=CrossOriginOpenerPolicy"])

try:
    context = browser.new_context()
    page = context.new_page()

    # Test APS (Cloudflare Turnstile)
    tests = [
        ("10.1103/PhysRevB.88.064104", "APS Physical Review B"),
        ("10.1016/j.cell.2016.03.044", "Elsevier Cell"),
        ("10.1073/pnas.0507655102", "PNAS"),
    ]

    for doi, name in tests:
        print(f"\n=== {doi} ({name}) ===")
        url = f"https://doi.org/{doi}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  goto error: {e}")

        for i in range(30):  # 60s max
            time.sleep(2)
            try:
                title = page.title() or ""
                body_len = page.evaluate("document.body ? document.body.innerText.length : 0") or 0
                final_url = page.url
            except Exception:
                continue
            markers = ["just a moment", "checking your browser", "attention required"]
            is_challenge = any(m in title.lower() for m in markers)
            if not is_challenge and body_len > 400:
                print(f"  READY at {i*2}s: '{title[:60]}' body={body_len}")
                # Check for PDF link
                pdf_meta = page.evaluate("""
                    (() => {
                        const m = document.querySelector('meta[name="citation_pdf_url"]');
                        return m ? m.content : null;
                    })()
                """)
                print(f"  citation_pdf_url: {pdf_meta}")
                break
            print(f"  [{i*2}s] title='{title[:40]}' body={body_len}")
        else:
            print(f"  TIMEOUT: still on challenge page")
            # Check if there's a turnstile iframe we can click
            turnstile = page.evaluate("""
                (() => {
                    const iframes = document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]');
                    return iframes.length > 0 ? Array.from(iframes).map(f => f.src.slice(0, 80)) : [];
                })()
            """)
            print(f"  turnstile iframes: {turnstile}")

finally:
    browser.close()

print("\n=== Done ===")
