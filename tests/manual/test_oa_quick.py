#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quick test: CloakBrowser on PNAS, bioRxiv, MDPI (OA publishers that should work)."""
import time
import sys
import base64

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from cloakbrowser import launch

TESTS = [
    ("10.1073/pnas.0507655102", "PNAS"),
    ("10.1101/2020.03.22.20041079", "bioRxiv"),
    ("10.3390/s21051705", "MDPI"),
]

browser = launch(headless=False, humanize=True, args=["--disable-features=CrossOriginOpenerPolicy"])
try:
    context = browser.new_context()
    page = context.new_page()

    for doi, name in TESTS:
        print(f"\n=== {doi} ({name}) ===")
        url = f"https://doi.org/{doi}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  goto error: {e}")

        ready = False
        for i in range(20):
            time.sleep(2)
            try:
                title = page.title() or ""
                body_len = page.evaluate("document.body ? document.body.innerText.length : 0") or 0
            except Exception:
                continue
            markers = ["just a moment", "checking your browser"]
            is_challenge = any(m in title.lower() for m in markers)
            if not is_challenge and body_len > 400:
                ready = True
                print(f"  READY at {i*2}s: '{title[:50]}' body={body_len}")
                break
            print(f"  [{i*2}s] title='{title[:40]}' body={body_len}")

        if not ready:
            print(f"  TIMEOUT")
            continue

        # Find PDF URL
        final_url = page.url
        meta_pdf = page.evaluate("""
            (() => {
                const m = document.querySelector('meta[name="citation_pdf_url"]');
                return m ? m.content : null;
            })()
        """)
        print(f"  citation_pdf_url: {meta_pdf}")

        if meta_pdf:
            # Try in-page fetch
            result = page.evaluate("""
                async (url) => {
                    try {
                        const resp = await fetch(url, {credentials: 'include'});
                        if (!resp.ok) return {ok: false, status: resp.status};
                        const buf = await resp.arrayBuffer();
                        const b = new Uint8Array(buf);
                        if (b.length < 5000) return {ok: false, status: 'too_small'};
                        if (b[0]!==0x25||b[1]!==0x50||b[2]!==0x44||b[3]!==0x46) return {ok: false, status: 'not_pdf'};
                        let s = '';
                        const chunk = 0x8000;
                        for (let i = 0; i < b.length; i += chunk)
                            s += String.fromCharCode.apply(null, b.subarray(i, i + chunk));
                        return {ok: true, b64: btoa(s), size: b.length};
                    } catch (e) { return {ok: false, status: 'error', msg: String(e)}; }
                }
            """, meta_pdf)
            if result and result.get("ok"):
                pdf_bytes = base64.b64decode(result["b64"])
                print(f"  SAVED: {len(pdf_bytes)}B")
            else:
                print(f"  fetch failed: {result}")
finally:
    browser.close()
