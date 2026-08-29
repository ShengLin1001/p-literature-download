#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test CloakBrowser across multiple publishers: can it autonomously pass Cloudflare
and fetch PDFs?"""
import time
import sys
import base64
import hashlib
from pathlib import Path

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from cloakbrowser import launch

# Test DOIs covering various publishers
TESTS = [
    ("10.1038/nature12373", "Nature", "OA_paywall"),
    ("10.1101/2020.03.22.20041079", "bioRxiv preprint", "OA_preprint"),
    ("10.3390/s21051705", "MDPI", "OA"),
    ("10.1371/journal.pone.0000308", "PLOS", "OA"),
    ("10.3389/fnins.2013.00071", "Frontiers", "OA"),
    ("10.1186/1471-2105-15-135", "BMC", "OA"),
    ("10.48550/arXiv.1706.03762", "arXiv", "OA_preprint"),
    ("10.1007/s00220-014-2131-9", "Springer", "OA_maybe"),
    ("10.1103/PhysRevB.88.064104", "APS", "paywall"),
    ("10.1016/j.cell.2016.03.044", "Elsevier Cell", "paywall"),
    ("10.1073/pnas.0507655102", "PNAS", "OA_maybe"),
    ("10.1093/nar/gkag457", "Oxford", "paywall_maybe"),
]

OUT = Path("F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf/mytest/auto_test_downloads")
OUT.mkdir(parents=True, exist_ok=True)

browser = launch(headless=False, humanize=True, args=["--disable-features=CrossOriginOpenerPolicy"])

try:
    context = browser.new_context()

    # Setup PDF capture (response + download events)
    captured = []  # list of (url, bytes)

    def on_response(response):
        try:
            ct = response.headers.get("content-type", "").lower()
            url = response.url
            if ("pdf" not in ct and "octet-stream" not in ct) or response.status >= 400:
                return
            # Skip supplementary
            low = url.lower()
            if any(m in low for m in ["moesm", "mediaobjects", "/media/", "supplementary", "supplement", "supp-"]):
                return
            body = response.body()
            if len(body) > 5000 and body[:5] == b"%PDF-":
                captured.append((url, body))
                print(f"    [CAPTURE] {len(body)}B from {url[:70]}")
        except Exception:
            pass

    def on_download(download):
        try:
            url = download.url
            low = url.lower()
            if any(m in low for m in ["moesm", "mediaobjects", "/media/", "supplementary"]):
                return
            tmp = Path(f"/tmp/scansci_test_{int(time.time()*1000)}.pdf")
            download.save_as(str(tmp))
            body = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
            if len(body) > 5000 and body[:5] == b"%PDF-":
                captured.append((url, body))
                print(f"    [DL-CAPTURE] {len(body)}B from {url[:70]}")
        except Exception:
            pass

    page = context.new_page()
    page.on("response", on_response)
    page.on("download", on_download)
    context.on("page", lambda pg: (pg.on("response", on_response), pg.on("download", on_download)))

    results = []

    for doi, publisher, access_type in TESTS:
        print(f"\n=== {doi} ({publisher}, {access_type}) ===")
        captured.clear()
        doi_suffix = doi.split("/")[-1] if "/" in doi else doi
        # Normalize arXiv DOI URL
        if doi.startswith("https://"):
            url = doi
        else:
            url = f"https://doi.org/{doi}"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  goto error: {e}")

        # Wait for page to be ready (pass Cloudflare)
        ready = False
        for i in range(20):  # 40 seconds max
            time.sleep(2)
            try:
                title = page.title() or ""
                body_len = page.evaluate("document.body ? document.body.innerText.length : 0") or 0
            except Exception:
                continue
            markers = ["just a moment", "checking your browser", "attention required",
                       "请稍候", "请稍后", "正在验证"]
            is_challenge = any(m in title.lower() or m in title for m in markers)
            if not is_challenge and body_len > 400:
                ready = True
                print(f"  ready at {i*2}s: '{title[:60]}' body={body_len}")
                break
            print(f"  [{i*2}s] waiting... title='{title[:40]}' body={body_len}")

        if not ready:
            print(f"  TIMEOUT: still on challenge page")
            results.append({"doi": doi, "publisher": publisher, "status": "cloudflare_timeout"})
            continue

        # Try to find PDF URL
        final_url = page.url
        pdf_url = None

        # Strategy 1: citation_pdf_url meta
        meta_pdf = page.evaluate("""
            (() => {
                const m = document.querySelector('meta[name="citation_pdf_url"]');
                return m ? m.content : null;
            })()
        """)
        if meta_pdf:
            pdf_url = meta_pdf
            print(f"  citation_pdf_url: {pdf_url[:80]}")

        # Strategy 2: construct from URL patterns
        if not pdf_url:
            low_url = final_url.lower()
            if "nature.com" in low_url:
                pdf_url = f"https://www.nature.com/articles/{doi_suffix}.pdf"
            elif "link.springer.com" in low_url:
                pdf_url = f"https://link.springer.com/content/pdf/{doi}.pdf"
            elif "pubs.acs.org" in low_url:
                pdf_url = f"https://pubs.acs.org/doi/pdf/{doi}"
            elif "onlinelibrary.wiley.com" in low_url:
                pdf_url = f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}"
            elif "pnas.org" in low_url:
                pdf_url = f"https://www.pnas.org/doi/pdf/{doi}"
            elif "science.org" in low_url:
                pdf_url = f"https://www.science.org/doi/pdf/{doi}"
            if pdf_url:
                print(f"  constructed pdf_url: {pdf_url[:80]}")

        # Strategy 3: scan DOM for PDF links
        if not pdf_url:
            dom_pdf = page.evaluate("""
                (() => {
                    for (const a of document.querySelectorAll('a[href]')) {
                        const href = (a.href || '').toLowerCase();
                        const text = (a.innerText || '').toLowerCase();
                        if (href.includes('supplement') || text.includes('supplement')) continue;
                        if (href.endsWith('.pdf') || href.includes('/pdf/') || href.includes('pdfdirect') || href.includes('/pdfft')) {
                            if (a.href.startsWith('http')) return a.href;
                        }
                    }
                    return null;
                })()
            """)
            if dom_pdf:
                pdf_url = dom_pdf
                print(f"  DOM pdf_url: {pdf_url[:80]}")

        if not pdf_url:
            print(f"  No PDF URL found (paywall?)")
            results.append({"doi": doi, "publisher": publisher, "status": "no_pdf_url", "final_url": final_url})
            continue

        # Try to download the PDF
        print(f"  Attempting to download: {pdf_url[:80]}")

        # Method 1: in-page fetch (same-origin, credentialed)
        pdf_saved = False
        try:
            result = page.evaluate("""
                async (url) => {
                    try {
                        const resp = await fetch(url, {credentials: 'include'});
                        if (!resp.ok) return {ok: false, status: resp.status};
                        const ct = resp.headers.get('content-type') || '';
                        if (!ct.includes('pdf') && !ct.includes('octet')) return {ok: false, status: 'ct:' + ct};
                        const buf = await resp.arrayBuffer();
                        const b = new Uint8Array(buf);
                        if (b.length < 5000) return {ok: false, status: 'too_small'};
                        if (b[0]!==0x25||b[1]!==0x50||b[2]!==0x44||b[3]!==0x46) return {ok: false, status: 'not_pdf'};
                        let s = '';
                        const chunk = 0x8000;
                        for (let i = 0; i < b.length; i += chunk)
                            s += String.fromCharCode.apply(null, b.subarray(i, i + chunk));
                        return {ok: true, b64: btoa(s)};
                    } catch (e) { return {ok: false, status: 'error', msg: String(e)}; }
                }
            """, pdf_url)
            if result and result.get("ok"):
                pdf_bytes = base64.b64decode(result["b64"])
                if len(pdf_bytes) > 5000 and pdf_bytes[:5] == b"%PDF-":
                    out_file = OUT / f"{doi_suffix}.pdf"
                    out_file.write_bytes(pdf_bytes)
                    print(f"  SAVED via in-page fetch: {len(pdf_bytes)}B -> {out_file}")
                    results.append({"doi": doi, "publisher": publisher, "status": "ok", "method": "in_page_fetch", "size": len(pdf_bytes)})
                    pdf_saved = True
            else:
                print(f"  in-page fetch failed: {result}")
        except Exception as e:
            print(f"  in-page fetch error: {e}")

        # Method 2: navigate to PDF URL and capture
        if not pdf_saved:
            try:
                page.goto(pdf_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                for url, body in captured:
                    if len(body) > 5000 and body[:5] == b"%PDF-":
                        out_file = OUT / f"{doi_suffix}.pdf"
                        out_file.write_bytes(body)
                        print(f"  SAVED via capture: {len(body)}B from {url[:70]}")
                        results.append({"doi": doi, "publisher": publisher, "status": "ok", "method": "capture", "size": len(body)})
                        pdf_saved = True
                        break
            except Exception as e:
                print(f"  goto PDF error: {e}")

        if not pdf_saved:
            print(f"  FAILED to download PDF")
            results.append({"doi": doi, "publisher": publisher, "status": "download_failed"})

        time.sleep(2)

    print("\n\n========= SUMMARY =========")
    for r in results:
        print(f"  {r['doi'][:40]:42s} {r['publisher']:20s} {r['status']}")
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\n  Success: {ok}/{len(results)}")

finally:
    browser.close()
