#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test CloakBrowser's ability to pass Cloudflare autonomously."""
import time
import sys

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from cloakbrowser import launch

browser = launch(headless=False, humanize=True, args=["--disable-features=CrossOriginOpenerPolicy"])
try:
    context = browser.new_context()
    page = context.new_page()

    # Test 1: Nature (light Cloudflare)
    print("=== Test 1: Nature article ===")
    url = "https://www.nature.com/articles/nature12373"
    print(f"Navigating to {url}...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    for i in range(30):
        time.sleep(2)
        title = page.title() or ""
        body_len = page.evaluate("document.body ? document.body.innerText.length : 0") or 0
        final_url = page.url
        print(f"  [{i*2}s] title='{title[:60]}' body_len={body_len} url={final_url[:80]}")
        if body_len > 400 and "just a moment" not in title.lower() and "checking" not in title.lower():
            print("  -> Page ready!")
            break
    else:
        print("  -> Timeout (still on challenge page)")

    # Check for PDF link
    html = page.content()
    print(f"  HTML length: {len(html)}")

    # Look for citation_pdf_url meta tag
    pdf_meta = page.evaluate("""
        (() => {
            const m = document.querySelector('meta[name="citation_pdf_url"]');
            return m ? m.content : null;
        })()
    """)
    print(f"  citation_pdf_url: {pdf_meta}")

    # Look for PDF links
    pdf_links = page.evaluate("""
        (() => {
            const links = [];
            for (const a of document.querySelectorAll('a[href]')) {
                const href = a.href.toLowerCase();
                const text = (a.innerText || '').toLowerCase();
                if (href.includes('.pdf') || href.includes('/doi/pdf/') || text.includes('pdf')) {
                    links.push({href: a.href, text: a.innerText.trim().slice(0, 50)});
                }
            }
            return links.slice(0, 5);
        })()
    """)
    print(f"  PDF links found: {pdf_links}")

finally:
    browser.close()

print("\n=== Test complete ===")
