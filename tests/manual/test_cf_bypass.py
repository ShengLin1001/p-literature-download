#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test strategies to bypass Cloudflare on APS and Elsevier."""
import time
import sys
import base64

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import cloakbrowser
print(f"CloakBrowser {cloakbrowser.__version__}")

from cloakbrowser import launch
from cloakbrowser.human import human_click, human_move

browser = launch(headless=False, humanize=True, args=["--disable-features=CrossOriginOpenerPolicy"])

try:
    context = browser.new_context()
    page = context.new_page()

    # Strategy 1: Try direct PDF URL for APS (bypass article page Cloudflare)
    print("=== Strategy 1: APS direct PDF URL ===")
    doi = "10.1103/PhysRevB.88.064104"
    # APS PDF URL pattern
    pdf_url = f"https://journals.aps.org/prb/pdf/{doi}"
    print(f"  Trying direct PDF: {pdf_url}")
    try:
        page.goto(pdf_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"  goto error: {e}")

    for i in range(20):
        time.sleep(2)
        try:
            title = page.title() or ""
            body_len = page.evaluate("document.body ? document.body.innerText.length : 0") or 0
            final_url = page.url
        except Exception:
            continue
        markers = ["just a moment", "checking your browser"]
        is_challenge = any(m in title.lower() for m in markers)
        print(f"  [{i*2}s] title='{title[:40]}' body={body_len} url={final_url[:60]}")
        if not is_challenge and body_len > 400:
            print(f"  READY!")
            # Check if it's showing PDF
            ct = page.evaluate("document.contentType || ''")
            print(f"  contentType: {ct}")
            break
    else:
        print("  TIMEOUT")
        # Try to find and click turnstile checkbox
        print("  Looking for turnstile widget...")
        turnstile_info = page.evaluate("""
            (() => {
                const result = {iframes: [], checkboxes: [], widgets: []};
                // Check for cloudflare turnstile iframes
                const allIframes = document.querySelectorAll('iframe');
                for (const f of allIframes) {
                    result.iframes.push({src: f.src?.slice(0, 100), id: f.id, name: f.name});
                }
                // Check for turnstile div
                const ts = document.querySelectorAll('[class*="turnstile"], [class*="cf-"], [id*="turnstile"], [id*="cf-"]');
                for (const t of ts) {
                    result.widgets.push({tag: t.tagName, id: t.id, class: t.className?.slice(0, 80)});
                }
                // Check for checkbox
                const cbs = document.querySelectorAll('input[type="checkbox"], [role="checkbox"]');
                for (const c of cbs) {
                    result.checkboxes.push({id: c.id, class: c.className?.slice(0, 50)});
                }
                return result;
            })()
        """)
        print(f"  turnstile info: {turnstile_info}")

        # Try clicking the turnstile checkbox if found
        # Cloudflare turnstile renders inside an iframe - we need to locate the iframe
        # and click inside it
        print("  Attempting to click turnstile checkbox...")
        try:
            # Try to find the turnstile iframe by its src
            ts_frame = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
            if ts_frame:
                # Try to find and click the checkbox inside
                checkbox = ts_frame.locator('input[type="checkbox"]')
                if checkbox.count() > 0:
                    print(f"  Found checkbox in turnstile iframe")
                    human_click(page, checkbox.first)
                    time.sleep(5)
                    print(f"  After click: title='{page.title()[:40]}'")
                else:
                    print("  No checkbox found in turnstile iframe")
            else:
                # Try a broader search
                frames = page.frames
                print(f"  All frames ({len(frames)}):")
                for f in frames:
                    print(f"    {f.url[:100]}")
        except Exception as e:
            print(f"  Turnstile click error: {e}")

    # Strategy 2: Try Elsevier with different approach
    print("\n=== Strategy 2: Elsevier ScienceDirect direct article ===")
    doi = "10.1016/j.cell.2016.03.044"
    # Try to resolve to PII directly
    # Cell Press article URL: https://www.cell.com/cell/fulltext/S0092-8674(16)30196-7
    # ScienceDirect: https://www.sciencedirect.com/science/article/pii/S0092867416301967
    # Let's try a different approach - use the Elsevier API or try cell.com directly
    cell_url = "https://www.cell.com/cell/fulltext/S0092-8674(16)30196-7"
    print(f"  Trying cell.com directly: {cell_url}")
    try:
        page.goto(cell_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"  goto error: {e}")

    for i in range(20):
        time.sleep(2)
        try:
            title = page.title() or ""
            body_len = page.evaluate("document.body ? document.body.innerText.length : 0") or 0
        except Exception:
            continue
        markers = ["just a moment", "checking your browser"]
        is_challenge = any(m in title.lower() for m in markers)
        print(f"  [{i*2}s] title='{title[:40]}' body={body_len}")
        if not is_challenge and body_len > 400:
            print(f"  READY!")
            # Look for PDF link
            pdf_meta = page.evaluate("""
                (() => {
                    const m = document.querySelector('meta[name="citation_pdf_url"]');
                    return m ? m.content : null;
                })()
            """)
            print(f"  citation_pdf_url: {pdf_meta}")
            break
    else:
        print("  TIMEOUT")

    # Strategy 3: Try using the persistent context (profile) approach
    # This might help with Cloudflare since it preserves the browser fingerprint
    print("\n=== Strategy 3: APS with persistent profile ===")
    import tempfile
    profile_dir = str(Path(tempfile.gettempdir()) / "cloakbrowser_aps_profile")
    print(f"  Using persistent profile: {profile_dir}")
    # Close current browser and use persistent context
    browser.close()
    browser = None

    from cloakbrowser import launch_persistent_context
    ctx = launch_persistent_context(profile_dir, headless=False, humanize=True, args=["--disable-features=CrossOriginOpenerPolicy"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    doi = "10.1103/PhysRevB.88.064104"
    url = f"https://doi.org/{doi}"
    print(f"  Navigating to {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"  goto error: {e}")

    for i in range(20):
        time.sleep(2)
        try:
            title = page.title() or ""
            body_len = page.evaluate("document.body ? document.body.innerText.length : 0") or 0
        except Exception:
            continue
        markers = ["just a moment", "checking your browser"]
        is_challenge = any(m in title.lower() for m in markers)
        print(f"  [{i*2}s] title='{title[:40]}' body={body_len}")
        if not is_challenge and body_len > 400:
            print(f"  READY!")
            break
    else:
        print("  TIMEOUT")

finally:
    if browser:
        browser.close()
    try:
        ctx.close()
    except:
        pass

print("\n=== Done ===")
