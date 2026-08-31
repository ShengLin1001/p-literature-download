#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Warm-start CloakBrowser download driver.

Root cause this works around: the CloakBrowser binary holds a heartbeat to
its license server over an idle HTTPS connection. v2rayN TUN (myruleset)
drops idle/proxied connections, so ~15-30 s after launch the heartbeat dies
and the binary exits with a license-denial code — surfacing as a misleading
'license server unreachable' or a bare TargetClosedError, and orphaning the
server-side seat for ~5-6 min.

Workaround: a daemon thread pings the license host every ~10 s through the
same process, keeping NAT/proxy state warm so the heartbeat survives. Each
attempt also pre-flights the seat count and refuses to launch when the seat
is still held (avoiding the leak-amplification loop).

Usage:
    python cb_download.py dois.txt -o outdir [--timeout 240] [--headless]
    python cb_download.py --selftest
"""

import argparse
import base64
import os
import random
import re
import sys
import threading
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

os.environ.setdefault("CLOAKBROWSER_VERSION", "151.0.7922.108.2")
PROFILE = os.path.expanduser("~/.scansci-pdf/cache/official-browser-profile")
LICENSE_HOST = "https://cloakbrowser.dev"

DENIAL_MARKERS = ("couldn't verify your license", "session limit", "license server", "license")


def is_denial(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in DENIAL_MARKERS)


def is_browser_death(exc: Exception) -> bool:
    return "TargetClosed" in type(exc).__name__ or "has been closed" in str(exc)


class KeepAlive:
    """Ping the license host every `interval` s for the process lifetime."""

    def __init__(self, interval=10.0):
        self.interval = interval
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        import httpx
        while not self._stop.is_set():
            try:
                httpx.get(LICENSE_HOST, timeout=8.0)
            except Exception:
                pass
            self._stop.wait(self.interval)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()


def seat_free() -> bool:
    """True when the server reports 0 active seats for our key."""
    try:
        import httpx
        key = Path(os.path.expanduser("~/.cloakbrowser/license.key")).read_text().strip()
        r = httpx.post(f"{LICENSE_HOST}/api/license/session/count",
                       json={"license_key": key}, timeout=10.0)
        return r.json().get("active", 1) == 0
    except Exception:
        return False


def classify(html, url):
    low = (html or "").lower()
    if "just a moment" in low and "cloudflare" in low:
        return "cloudflare_challenge"
    if "cf-turnstile" in low or "challenges.cloudflare.com" in low:
        return "cloudflare_turnstile"
    if "hcaptcha" in low or "recaptcha" in low:
        return "captcha_waiting_user"
    if "access through your institution" in low or "sign in via your institution" in low:
        return "institution_access_needed"
    if url and re.search(r"\.pdf(\?|$)", url, re.I):
        return "pdf_ready"
    if re.search(r'download[^"<]{0,40}pdf', low):
        return "article_with_pdf_button"
    if "get access" in low or "purchase pdf" in low:
        return "paywall_or_login"
    return "article_unknown"


def click_turnstile_human(page):
    box = None
    try:
        hidden = page.locator("input[name='cf-turnstile-response']")
        if hidden.count():
            box = hidden.first.locator("..").bounding_box()
        if not box:
            iframe = page.locator("iframe[src*='challenges.cloudflare.com']")
            if iframe.count():
                box = iframe.first.bounding_box()
    except Exception:
        return False
    if not box:
        return False
    x = box["x"] + random.uniform(19, 30)
    y = box["y"] + box["height"] * random.uniform(0.45, 0.55)
    page.mouse.move(random.uniform(100, 500), random.uniform(100, 400))
    time.sleep(random.uniform(0.3, 0.8))
    page.mouse.move(x, y, steps=random.randint(15, 30))
    time.sleep(random.uniform(0.2, 0.5))
    page.mouse.down()
    time.sleep(random.uniform(0.09, 0.19))
    page.mouse.up()
    return True


PDF_CLICK_JS = r"""
(() => {
  const norm = (s) => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const els = [...document.querySelectorAll('a,button,[role=button]')];
  const std = els.find(e => /standard\s*pdf/.test(norm(e.innerText)));
  if (std) { std.click(); return 'clicked:standard-pdf'; }
  const dl = els.find(e => /download\s*(full[\s-]*)?(text\s*)?pdf|^pdf$|view\s*pdf|download\s*pdf/.test(norm(e.innerText)));
  if (dl) { dl.click(); return 'clicked:download-pdf'; }
  const link = [...document.querySelectorAll('a[href]')]
    .map(a => a.href).find(h => /\.pdf(\?|$)/i.test(h) || /\/pdf\//i.test(h));
  if (link) return 'link:' + link;
  return 'none';
})()
"""


def find_pdf_in_page(page):
    out = page.evaluate(PDF_CLICK_JS)
    time.sleep(5)
    if out and out.startswith("link:"):
        return out[5:]
    if re.search(r"\.pdf(\?|$)", page.url, re.I):
        return page.url
    m = re.search(r'https?://[^"\'<>\s]+?\.pdf(\?[^"\'<>\s]*)?', page.content(), re.I)
    return m.group(0) if m else None


def fetch_pdf_bytes(page, pdf_url):
    b64 = page.evaluate(
        """(url) => fetch(url, {credentials:'include'})
            .then(r => { if(!r.ok) throw new Error('http '+r.status); return r.arrayBuffer(); })
            .then(b => { const u=new Uint8Array(b); let s='';
              for(let i=0;i<u.length;i+=0x8000) s+=String.fromCharCode.apply(null,u.subarray(i,i+0x8000));
              return btoa(s); })""",
        pdf_url,
    )
    data = base64.b64decode(b64)
    return data if data[:5] == b"%PDF-" else None


class BrowserDied(Exception):
    pass


# Injected into every page right after navigation. The CloakBrowser binary's
# license heartbeat is keyed to ITS OWN renderer's network activity; a python
# -side ping does not count. A no-cors fetch to the license host every few
# seconds keeps the browser-side connection warm so v2rayN's TUN/myruleset
# does not drop it (which otherwise kills the browser ~15s after launch).
KEEPALIVE_JS = """
if (!window.__cbKeepalive) {
  window.__cbKeepalive = setInterval(() => {
    fetch('https://cloakbrowser.dev/favicon.ico', {mode:'no-cors'}).catch(()=>{});
  }, 8000);
}
"""


def run_session(dois, out_dir, timeout, headless):
    from cloakbrowser import launch_persistent_context

    ctx = launch_persistent_context(
        PROFILE, headless=headless, humanize=True, human_preset="careful",
        ignore_https_errors=True,  # doi.org redirect chain has a cert-CN quirk
    )
    results, remaining, died = [], list(dois), None
    try:
        page = ctx.new_page()
        page.set_default_navigation_timeout(90000)   # Cloudflare/slow redirects
        page.add_init_script(KEEPALIVE_JS)  # re-injected on every navigation
        # warm the heartbeat channel before the first real navigation
        try:
            page.goto(LICENSE_HOST, timeout=15000)
        except Exception:
            pass
        for i, doi in enumerate(dois):
            res = {"doi": doi, "path": "cloakbrowser", "status": "failed",
                   "file": None, "reason": ""}
            print(f"▶️  {doi}")
            try:
                page.goto("https://doi.org/" + doi, timeout=90000)
                page.evaluate(KEEPALIVE_JS)  # ensure live on the landed page
            except Exception as exc:
                msg = str(exc)
                if is_denial(exc) or is_browser_death(exc):
                    remaining = dois[i:]
                    died = BrowserDied(msg[:120])
                    break
                # doi.org redirect sometimes races into chrome-error; the page
                # still lands if we wait, so fall through to the wait loop.
                if "interrupted by another navigation" in msg or "ERR_" in msg:
                    print(f"   nav warning (waiting for settle): {msg[:70]}")
                else:
                    res.update(status="error", reason=f"goto: {msg[:120]}")
                    results.append(res)
                    continue

            deadline = time.time() + timeout
            state = "navigating"
            while time.time() < deadline:
                try:
                    url, html = page.url, page.content()
                    page.evaluate(KEEPALIVE_JS)  # keep alive across reloads
                except Exception as exc:
                    if is_denial(exc) or is_browser_death(exc):
                        remaining = dois[i:]
                        died = BrowserDied(str(exc)[:120])
                        break
                    time.sleep(5)
                    continue
                state = classify(html, url)
                if state == "captcha_waiting_user":
                    res.update(status=state, reason=f"hCaptcha at {url[:100]}")
                    break
                if state in ("cloudflare_challenge", "cloudflare_turnstile"):
                    if click_turnstile_human(page):
                        time.sleep(random.uniform(8, 14))
                    else:
                        time.sleep(random.uniform(10, 16))
                        try:
                            page.reload()
                        except Exception:
                            pass
                        time.sleep(random.uniform(8, 12))
                    continue
                if state == "institution_access_needed":
                    page.evaluate(
                        """() => { const e=[...document.querySelectorAll('a,button')]
                          .find(x=>/access through your institution|institutional/i.test(x.innerText||''));
                          if(e) e.click(); }""")
                    time.sleep(10)
                    continue
                link = find_pdf_in_page(page)
                if link:
                    try:
                        data = fetch_pdf_bytes(page, link)
                    except Exception as exc:
                        data = None
                        res["reason"] = f"fetch: {str(exc)[:100]}"
                    if data:
                        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", doi).strip("_")
                        dst = out_dir / f"{safe}_Official.pdf"
                        dst.write_bytes(data)
                        res.update(status="downloaded", file=str(dst),
                                   reason=f"{len(data)} bytes")
                        break
                time.sleep(6)
            if died:
                break
            if res["status"] == "failed" and not res["reason"]:
                res.update(status="timeout", reason=f"no pdf in {timeout}s ({state})")
            results.append(res)
            print(f"   {res['status']}: {res['reason']}")
        else:
            remaining = []
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    if died is not None:
        raise died
    return results, remaining


def selftest():
    assert classify("<html>Just a moment... cloudflare</html>", "https://x/") == "cloudflare_challenge"
    assert classify("<html>Access through your institution</html>", "https://x/") == "institution_access_needed"
    assert classify("<html><a>Download PDF</a></html>", "https://x/a") == "article_with_pdf_button"
    assert classify("<html/>", "https://x/p/1.pdf") == "pdf_ready"
    assert is_denial(Exception("couldn't verify your license"))
    assert is_browser_death(Exception("Target page, context or browser has been closed"))
    print("✅ cb_download selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dois", nargs="?")
    ap.add_argument("-o", "--output", default=".")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--report", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return

    from mymetal.academic.search.literature_download import parse_dois
    dois = parse_dois(Path(args.dois))
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    todo, results = list(dois), []
    with KeepAlive(interval=10):
        for attempt in range(args.retries + 1):
            if not todo:
                break
            if not seat_free():
                wait = 60 * (attempt + 1)
                print(f"⏳ seat busy, waiting {wait}s for server to release...")
                time.sleep(wait)
                if not seat_free():
                    print("❌ seat still held; aborting to avoid denial loop")
                    break
            if attempt:
                print(f"⏳ retry {attempt} ({len(todo)} left)")
                time.sleep(30)
            try:
                batch, remaining = run_session(todo, out_dir, args.timeout, args.headless)
            except BrowserDied as exc:
                print(f"⚠️  browser died: {exc}")
                done = {r["doi"] for r in results}
                todo = [d for d in todo if d not in done]
                continue
            except Exception as exc:
                if is_denial(exc) or is_browser_death(exc):
                    print(f"⚠️  launch denial/crash: {str(exc)[:100]}")
                    continue
                raise
            results.extend(batch)
            todo = remaining

    if args.report:
        import json
        Path(args.report).write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = sum(1 for r in results if r["status"] == "downloaded")
    print(f"\n📊 downloaded {ok}/{len(dois)}")
    if ok < len(dois):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
