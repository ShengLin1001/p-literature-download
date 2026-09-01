#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download publisher PDFs through a real, institution-logged-in Edge.

Each DOI is first *resolved* with Playwright over CDP - open doi.org, clear
Cloudflare with a human-shaped Turnstile click, dismiss the cookie overlay,
walk the institution flow if needed, and collect PDF candidate URLs - and
then *fetched*. No single fetch method covers every publisher, so four are
tried in order, cheapest first:

1. fetch() inside the page. Works almost everywhere and touches no disk.
2. Navigate + Playwright download. For hosts that reject a cross-origin
   fetch on CORS grounds but serve a plain navigation (MDPI's Akamai wall).
3. Navigate, then fetch(location.href) from the PDF's own origin. For
   Silverchair hosts (AIP, RSC, OUP) that send the PDF inline, so no
   download event ever fires, but the tab is now same-origin with it.
4. Detach Playwright entirely, then open the URL in a bare CDP tab. Only
   Elsevier needs this: a DevTools session attached to *any* page makes
   pdf.sciencedirectassets.com hang at "Request Verification: In Progress"
   forever. Detached, the same URL downloads instantly.

Every tab is created in the background and the window is minimized once per
run, so a batch does not keep raising Edge onto the user's desktop. Only
--human-wait restores it, because a captcha has to be visible to be solved.

Manual takeover is always available and needs no flag. Restore the window
whenever you like and drive it yourself: the resolve loop re-reads every tab
a few times a minute, so a challenge you clear by hand is simply noticed, and
a PDF you open by hand - in this tab or a new one - is captured as the
article. Detection is document.contentType, not a URL suffix, because several
publishers serve the file from an extension-less path.

Note that Edge's built-in PDF viewer cannot be turned off from here:
always_open_pdf_externally is a protected preference and Edge restores it on
startup. Tiers 1 and 3 are what make that irrelevant.

Start the browser once and leave it running (see start_edge.ps1):

    msedge.exe --remote-debugging-port=9333
        --user-data-dir=%USERPROFILE%\\.pj\\p-literature-download\\profile
        --no-proxy-server

--no-proxy-server matters as much as the profile: through the system proxy,
Cloudflare scores the exit IP badly enough to stall the same downloads.

The daily Edge's runtime-enabled port (edge://inspect) is not usable here: it
serves no /json/* endpoints and stops accepting WebSocket handshakes after
the first client disconnects.

Two presets cover the callers. --preset agent turns in-script retries and the
captcha prompt off, because an agent reruns the script itself on failure and
cannot solve an image captcha either way; --preset human turns both on, because
a person running this by hand has no outer loop. An explicit flag beats both.

The folder watched for browser downloads is read from the Edge profile rather
than assumed: Edge decides where a file lands, and watching the wrong folder
makes tier 4 and the manual-download takeover fail without saying anything.

Usage:
    python edge_download.py dois.txt -o outdir --preset agent
    python edge_download.py dois.txt -o outdir --preset human
    python edge_download.py --selftest
"""

import argparse
import base64
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

# Run as a script from anywhere: put this file's own directory first, so the
# vendored modules below resolve without installing anything.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from literature_download import (
    check_journal_metadata, fetch_doi_metadata, generate_pdf_filename,
    normalize_doi, parse_dois)
from publisher_pdf import (
    JS_ACCEPT_CONSENT, JS_FETCH_PDF, JS_FIND_PDF_URLS, JS_IS_PDF_DOCUMENT,
    JS_OPEN_INSTITUTION, JS_PICK_INSTITUTION, JS_READ_CHUNK, JS_TYPE_INSTITUTION,
    check_article_url, check_supplement_url, filter_pdf_candidates,
    get_page_state, get_publisher_pdf_url)
from verify_pdf import (doi_in_text, looks_like_supplementary, read_pdf,
                        title_in_text)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


# --- page state ---------------------------------------------------------

def click_turnstile_human(page):
    """Click the Turnstile checkbox with human-shaped mouse motion.

    Fingerprint alone does not clear these; Cloudflare scores the pointer
    trajectory and press duration. The checkbox lives in a cross-origin
    iframe, so aim at the *parent* of the hidden cf-turnstile-response input
    (the iframe's own box is offset) and fall back to the iframe box.
    """
    box = None
    try:
        hidden = page.locator("input[name='cf-turnstile-response']")
        if hidden.count():
            box = hidden.first.locator("..").bounding_box()
        if not box:
            frame = page.locator("iframe[src*='challenges.cloudflare.com']")
            if frame.count():
                box = frame.first.bounding_box()
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


# --- PDF URL resolution -------------------------------------------------

def pdf_candidates(page, doi=""):
    """PDF URLs to try, best first.

    A host rule outranks the page's own citation_pdf_url, because some
    publishers advertise a link that only redirects back to the abstract.
    """
    ldom = []
    try:
        ldom = page.evaluate(JS_FIND_PDF_URLS) or []
    except Exception:
        pass
    lurl = [get_publisher_pdf_url(page.url)] + list(ldom)
    return filter_pdf_candidates([u for u in lurl if u], doi, page.url)


# --- human takeover -----------------------------------------------------

def check_pdf_tab(page) -> bool:
    """Return whether this tab is currently displaying a PDF."""
    try:
        return bool(page.evaluate(JS_IS_PDF_DOCUMENT))
    except Exception:
        return False


def grab_takeover_pdf(page, doi=""):
    """Capture a PDF the user opened by hand, in this tab or any other.

    Takeover needs no flag and never blocks: the resolve loop re-reads the
    tabs every few seconds, so clearing a challenge, signing in, or opening
    the PDF yourself is simply noticed on the next pass. Publishers like
    Nature and IEEE open the PDF in a *new* tab, which is why every tab is
    scanned rather than just the one the script drives.

    Returns (pdf_bytes_or_None, source_url).
    """
    lpage = [page] + [pg for pg in page.context.pages if pg is not page]
    for pg in lpage:
        try:
            if not check_pdf_tab(pg) or check_supplement_url(pg.url):
                continue
            data = fetch_in_page(pg, pg.url)
            if data:
                return data, pg.url
        except Exception:
            pass
    return None, ""


def close_stale_pdf_tabs(page) -> None:
    """Close PDF tabs left over from an earlier DOI.

    Takeover scans every tab and a PDF tab outlives the article that opened
    it, so without this the next DOI captures the previous article's PDF as
    its own. Only PDF tabs are touched; the user's other tabs are left alone.
    """
    for pg in page.context.pages:
        if pg is page:
            continue
        try:
            if check_pdf_tab(pg):
                pg.close()
        except Exception:
            pass


# --- institutional access ----------------------------------------------

INSTITUTION = "Zhejiang University"


def try_institution_login(page):
    """Walk the publisher's "access through your institution" flow.

    Only the first article per publisher needs it: once the school IdP
    (zjuam) has issued its SSO cookie into this profile, later redirects
    resolve without any interaction.
    """
    try:
        if not page.evaluate(JS_OPEN_INSTITUTION):
            return False
        page.wait_for_timeout(3500)
        if page.evaluate(JS_TYPE_INSTITUTION, INSTITUTION):
            page.wait_for_timeout(2500)
            page.evaluate(JS_PICK_INSTITUTION, INSTITUTION)
        page.wait_for_timeout(6000)
        return True
    except Exception:
        return False


# --- fetch: raw CDP, nothing attached -----------------------------------

def browser_ws(endpoint: str) -> str:
    with urllib.request.urlopen(endpoint.rstrip("/") + "/json/version", timeout=10) as fh:
        return json.load(fh)["webSocketDebuggerUrl"]


def check_endpoint(endpoint: str) -> str:
    """Fail fast when the automation Edge is not up.

    Without this the run burns through every DOI reporting connection errors,
    which reads like a download problem rather than a browser that was never
    started.
    """
    try:
        browser_ws(endpoint)
    except Exception as exc:
        print(f"❌ ERROR: 连不上自动化 Edge（{endpoint}）：{str(exc)[:90]}")
        print(r"   先启动它：powershell -NoProfile -File scripts\start_edge.ps1")
        print("   首次使用还需在弹出的窗口里手动登录一次机构账号（WebVPN / CARSI）。")
        raise SystemExit(1)
    return endpoint


class RawCdp:
    """Browser-level CDP client that never attaches to a page.

    Attaching is what trips the stricter publisher bot walls, so this client
    only creates and closes targets and lets Edge's own download machinery
    write the file to disk.
    """

    def __init__(self, endpoint: str):
        import websocket  # pip install websocket-client
        self.ws = websocket.create_connection(browser_ws(endpoint), timeout=30,
                                              suppress_origin=True)
        self.n = 0

    def send(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def get_page_targets(endpoint: str) -> list:
    """Return open page target ids, newest first."""
    with urllib.request.urlopen(endpoint.rstrip("/") + "/json/list", timeout=10) as fh:
        return [t["id"] for t in json.load(fh) if t.get("type") == "page"]


def set_window_state(endpoint: str, state: str) -> None:
    """Minimize or restore the automation window.

    Opening a tab is what raises Edge onto the user's desktop, so every tab
    this script opens passes Target.createTarget's ``background`` flag and the
    window is minimized once per run. Windows clamps a negative window
    position back to (0, 0), so moving the window off-screen is not an option.
    Restoring is only for the ``--human-wait`` path, where the user has to see
    the captcha to solve it.

    Some page targets carry no window at all (edge://downloads-hub is one), so
    try each until one answers rather than trusting the first.
    """
    try:
        cdp = RawCdp(endpoint)
    except Exception:
        return
    try:
        for tid in get_page_targets(endpoint):
            try:
                wid = cdp.send("Browser.getWindowForTarget", {"targetId": tid})["windowId"]
            except Exception:
                continue
            cdp.send("Browser.setWindowBounds",
                     {"windowId": wid, "bounds": {"windowState": state}})
            return
    except Exception:
        pass
    finally:
        cdp.close()


def open_background_tab(endpoint: str) -> str:
    """Open a tab without raising Edge's window; return its URL marker.

    Playwright's ``new_page`` always creates a foreground tab, which restores
    the minimized window, and it only adopts targets that already exist when
    ``connect_over_cdp`` runs. So the tab is created here over raw CDP with
    ``background: true``, *before* Playwright connects, and picked back out by
    the marker in its URL.
    """
    token = "bg-%d" % random.randrange(10 ** 9)
    cdp = RawCdp(endpoint)
    try:
        cdp.send("Target.createTarget",
                 {"url": "about:blank#" + token, "background": True})
    finally:
        cdp.close()
    return token


def get_tab_by_token(context, token: str):
    """Return the page whose URL carries ``token``, else a fresh foreground tab."""
    for page in context.pages:
        try:
            if token in page.url:
                return page
        except Exception:
            pass
    return context.new_page()  # window pops up, but the run still works


# Edge - not this script - decides where a download lands, so the folder below
# is only a default: main() rebinds it from the profile Edge is actually using.
# Watching the wrong folder makes tier 4 and the manual-download takeover fail
# silently, which reads like a publisher problem rather than a wrong path.
PJ_ROOT = Path.home() / ".pj" / "p-literature-download"
PROFILE_DIR = PJ_ROOT / "profile"        # Edge --user-data-dir: the logged-in session
DOWNLOAD_DIR = PJ_ROOT / "downloads"     # where Edge drops files


def get_download_dir(profile_dir=PROFILE_DIR) -> Path:
    """Read the download folder out of the Edge profile that will serve us.

    start_edge.ps1 writes it into the profile, so the profile is the source of
    truth; a constant on this side goes stale the moment someone passes
    -ProfileDir or -DownloadDir. Falls back to the default when the profile has
    not been created yet.
    """
    try:
        # utf-8-sig, not utf-8: a byte-order mark is a JSON parse error, and
        # anything that writes this file from PowerShell can leave one behind.
        prefs = json.loads(
            (Path(profile_dir) / "Default" / "Preferences").read_text(encoding="utf-8-sig"))
        directory = (prefs.get("download") or {}).get("default_directory")
        if directory:
            return Path(directory)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return DOWNLOAD_DIR


def snapshot_downloads(watch_dir: Path = None) -> set:
    """Names already in the browser's download folder."""
    try:
        return {f.name for f in (watch_dir or DOWNLOAD_DIR).iterdir()}
    except OSError:
        return set()


def grab_downloaded_pdf(sbefore, watch_dir: Path = None):
    """Pick up a PDF that the user's own click told Edge to download.

    A publisher answering with Content-Disposition: attachment never shows the
    file in a tab, so scanning tabs cannot see it. There is no moment to guess
    at: the baseline is taken once when the article opens and every poll diffs
    against it, so whichever poll follows the download finds the file. Edge
    keeps a half-written download under a .crdownload name, which is what
    makes a partial file distinguishable from a finished one.

    Returns (pdf_bytes_or_None, source_label).
    """
    watch_dir = watch_dir or DOWNLOAD_DIR
    try:
        lnew = [f for f in watch_dir.iterdir()
                if f.name not in sbefore and f.is_file()
                and not f.name.endswith(".crdownload")]
    except OSError:
        return None, ""
    for path_new in lnew:
        try:
            data = path_new.read_bytes()
        except OSError:
            continue
        if not data.startswith(b"%PDF-"):
            continue
        try:
            path_new.unlink()   # consumed; the copy that matters goes to out_dir
        except OSError:
            pass
        return data, "下载目录/" + path_new.name
    return None, ""


def check_pdf_identity(data: bytes, doi: str, title: str) -> str:
    """Warn when a PDF does not look like the requested article.

    Advisory only, never a gate. Papers from before DOIs were printed carry no
    DOI at all, and their scans are OCR: the 1971 PRB test article extracts
    "PHYSICAL REVIEW" as "PH YSICA L BEVI EUV", and its first page starts with
    the tail of the *previous* article. A failed match is therefore weak
    evidence, not proof, and must never delete or reject a file.

    Returns a warning string, or "" when nothing looks wrong.
    """
    try:
        _, text = read_pdf(data)
    except Exception as exc:
        return f"PDF 文本解析失败（{str(exc)[:40]}）"
    if looks_like_supplementary(text):
        return "首页像补充材料而非正文"
    if doi_in_text(text, doi) or (title and title_in_text(text, title)):
        return ""
    if len((text or "").strip()) < 200:
        return "几乎抽不出文本（多半是扫描件），无法核对是否为本篇"
    return "正文里没找到本篇 DOI 或标题，可能抓错文章"


def cdp_download(endpoint: str, urls, timeout: int, watch_dir: Path = None):
    """Open each URL in a bare tab; return (pdf_bytes, url) for the first hit.

    Watches Edge's own download folder rather than redirecting it:
    Browser.setDownloadBehavior does not reliably apply to the already-open
    default context, and a download that silently lands in the user's real
    Downloads folder looks identical to a failure. The folder is set once, in
    the automation profile's preferences, to keep it out of the way.
    """
    if not urls:
        return None, ""
    watch_dir = watch_dir or DOWNLOAD_DIR
    watch_dir.mkdir(parents=True, exist_ok=True)
    cdp = RawCdp(endpoint)
    try:
        for url in urls:
            before = {f.name for f in watch_dir.iterdir()}
            tid = cdp.send("Target.createTarget",
                           {"url": url, "background": True})["targetId"]
            deadline = time.time() + timeout
            done = None
            try:
                while time.time() < deadline:
                    time.sleep(2)
                    new = [f for f in watch_dir.iterdir()
                           if f.name not in before and f.is_file()
                           and not f.name.endswith(".crdownload")]
                    if new:
                        done = new[0]
                        break
            finally:
                try:
                    cdp.send("Target.closeTarget", {"targetId": tid})
                except Exception:
                    pass
            if not done:
                continue
            data = done.read_bytes()
            try:
                done.unlink()
            except OSError:
                pass
            if data[:5] == b"%PDF-":
                return data, url
        return None, ""
    finally:
        cdp.close()


# In-page fetch: the tab's own session, cookies and Cloudflare clearance.
# Preferred when the publisher allows it, because it needs no download at all
# and so does not depend on Edge's PDF-viewer setting (which is a protected
# preference - editing Preferences directly gets reverted on startup).
CHUNK = 3 * 1024 * 1024      # a multiple of 3, so no chunk needs base64 padding


def fetch_in_page(page, url: str):
    """Fetch url from inside the tab. Returns PDF bytes or None."""
    size = page.evaluate(JS_FETCH_PDF, url)
    if not size or size < 1024:
        return None
    # Decode each chunk separately: every chunk carries its own base64
    # padding, so concatenating the *encoded* strings corrupts the file.
    parts = []
    off = 0
    while off < size:
        n = min(CHUNK, size - off)
        parts.append(base64.b64decode(page.evaluate(JS_READ_CHUNK, [off, n])))
        off += n
    data = b"".join(parts)
    return data if data[:5] == b"%PDF-" else None


def fetch_by_download(page, url: str, timeout: int = 90):
    """Navigate to url and capture the download Playwright forces.

    Publishers that reject a page-context fetch() on CORS grounds (AIP, RSC,
    OUP, MDPI) still serve a plain navigation. Playwright's own download
    behaviour makes Chromium save the file instead of opening the built-in
    PDF viewer, so this works without touching always_open_pdf_externally -
    which Edge protects and restores on startup anyway.
    """
    with page.expect_download(timeout=timeout * 1000) as info:
        try:
            page.goto(url, wait_until="commit", timeout=timeout * 1000)
        except Exception as exc:
            # Playwright aborts a navigation that turned into a download with
            # this message; that is the success path.
            if "download is starting" not in str(exc).lower():
                raise
    data = Path(info.value.path()).read_bytes()
    return data if data[:5] == b"%PDF-" else None


def fetch_after_navigate(page, url: str, timeout: int = 90):
    """Navigate to the PDF, then fetch it same-origin from that very tab.

    Silverchair hosts (AIP, RSC, OUP) hand out a tokenised URL that Chromium
    renders in the built-in viewer instead of downloading, so no download
    event ever fires. But the tab is now *on* the PDF's own origin, which
    makes a plain fetch(location.href) succeed where a cross-origin one from
    the article page was rejected.
    """
    try:
        page.goto(url, wait_until="commit", timeout=timeout * 1000)
    except Exception as exc:
        if "download is starting" not in str(exc).lower():
            raise
    page.wait_for_timeout(6000)
    if not re.search(r"\.pdf(\?|#|$)", page.url, re.I):
        return None
    return fetch_in_page(page, page.url)


def fetch_any_in_page(page, urls):
    """First candidate the tab can fetch itself. Returns (bytes, url)."""
    for url in urls:
        try:
            data = fetch_in_page(page, url)
        except Exception:
            data = None
        if data:
            return data, url
    return None, ""


# --- resolve: Playwright ------------------------------------------------

def resolve_candidates(endpoint, page, doi, timeout, human_wait):
    """Open the DOI in ``page``, clear challenges and logins.

    Returns (candidate_urls, state, pdf_bytes_or_None, source_url).
    """
    asked_human = False
    tried_institution = False
    accepted_consent = False
    next_click = 0.0
    lost_since = 0.0
    relanded = 0
    state = "navigating"
    sbefore = snapshot_downloads()
    try:
        page.goto("https://doi.org/" + doi, wait_until="domcontentloaded", timeout=90000)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                html = page.content()
            except Exception:
                time.sleep(2)
                continue
            state = get_page_state(html, page.url)

            # A PDF open in any tab is the answer, whatever the state says -
            # this is what makes manual takeover work without a flag.
            data, src = grab_takeover_pdf(page, doi)
            if not data:
                data, src = grab_downloaded_pdf(sbefore)
            if data:
                return [src], "pdf_ready", data, src

            # Recovery: the tab can end up somewhere that is not this article
            # at all - an APS section index, or the SSO wayfinder the
            # institution flow clicked into and never returned from. Nothing
            # downstream can succeed from there, so go back to the DOI rather
            # than poll a dead page until the deadline.
            if state == "unknown" and not check_article_url(page.url, doi, page.url):
                lost_since = lost_since or time.time()
                if time.time() - lost_since > 25 and relanded < 2:
                    relanded += 1
                    lost_since = 0.0
                    print(f"   ↩️  偏离到 {page.url[:60]}，退回 DOI 重来")
                    page.goto("https://doi.org/" + doi,
                              wait_until="domcontentloaded", timeout=90000)
                    continue
            else:
                lost_since = 0.0

            # Cloudflare is the script's job: keep re-clicking the Turnstile
            # checkbox with human-shaped motion until it lets go.
            if state == "cloudflare":
                if time.time() >= next_click:
                    next_click = time.time() + 20
                    click_turnstile_human(page)
                    time.sleep(random.uniform(6, 10))
                    continue
                time.sleep(3)
                continue

            # An image captcha cannot be scripted; if the caller opted into
            # being asked, surface the tab once.
            if state == "captcha":
                if human_wait and not asked_human:
                    asked_human = True
                    set_window_state(endpoint, "normal")
                    page.bring_to_front()
                    print(f"   🖐  captcha: 请在弹出的标签页里完成验证，最多等 {human_wait}s")
                    deadline = max(deadline, time.time() + human_wait)
                time.sleep(4)
                continue

            if not accepted_consent:
                accepted_consent = True
                try:
                    if page.evaluate(JS_ACCEPT_CONSENT):
                        page.wait_for_timeout(2500)
                        continue
                except Exception:
                    pass

            urls = pdf_candidates(page, doi)
            if urls:
                data, src = fetch_any_in_page(page, urls)
                if not data:
                    # Escalate: force a download, then - for hosts that render
                    # the PDF inline instead - fetch it same-origin.
                    for grab in (fetch_by_download, fetch_after_navigate):
                        for url in urls:
                            try:
                                data = grab(page, url, min(90, timeout))
                            except Exception:
                                data = None
                            if data:
                                src = url
                                break
                        if data:
                            break
                if data or tried_institution:
                    return urls, state, data, src
                # Links are there but unreadable: usually the institution
                # is not signed in yet on this publisher. Sign in and retry.
                tried_institution = True
                if try_institution_login(page):
                    continue
                return urls, state, None, ""

            # No PDF link at all: publishers hide it until access is granted.
            if not tried_institution:
                tried_institution = True
                if try_institution_login(page):
                    if human_wait:
                        set_window_state(endpoint, "normal")
                        page.bring_to_front()
                        deadline = max(deadline, time.time() + human_wait)
                    continue
            time.sleep(4)
        return [], state, None, ""
    except Exception as exc:
        return [], f"error: {str(exc)[:120]}", None, ""
    finally:
        try:
            page.close()
        except Exception:
            pass


def get_output_name(doi):
    """Resolve a DOI to its ``year-JOURNAL-title.pdf`` name, or a skip reason.

    Naming and the journal abbreviation index live in literature_download,
    so every run produces identical filenames. Crossref is queried before the
    browser opens, which also filters out records this pipeline must not save
    (non-journal types, SnapShots, journals with no abbreviation).

    Returns:
        ``(filename, None, title)`` when supported, else ``(None, reason, "")``.
    """
    dict_metadata = fetch_doi_metadata(doi)
    reason = check_journal_metadata(dict_metadata)
    if reason:
        return None, reason, ""
    ltitle = (dict_metadata or {}).get("title") or [""]
    return generate_pdf_filename(dict_metadata), None, ltitle[0]


def download_one(endpoint, doi, out_dir, timeout, human_wait, name, title=""):
    """Resolve with Playwright, then fetch detached. Returns a status dict."""
    from playwright.sync_api import sync_playwright

    res = {"doi": doi, "status": "failed", "file": None, "state": "",
           "reason": "", "warning": ""}
    token = open_background_tab(endpoint)  # must exist before Playwright connects
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint, timeout=30000)
        page = get_tab_by_token(browser.contexts[0], token)
        close_stale_pdf_tabs(page)
        urls, state, data, src = resolve_candidates(
            endpoint, page, doi, timeout, human_wait)
        # Never browser.close(): on a CDP attachment that tears the DevTools
        # server down and Edge stops accepting clients.
    res["state"] = state
    if not urls:
        res.update(status="no_pdf_link", reason=f"no pdf link (state {state})")
        return res

    if not data:
        # Playwright is fully disconnected by here, which is what lets the
        # stricter publisher challenges actually complete.
        data, src = cdp_download(endpoint, urls, min(120, timeout))
    if not data:
        res.update(status="fetch_failed",
                   reason="links not retrievable: " + ", ".join(u[:90] for u in urls))
        return res
    dst = Path(out_dir) / name
    dst.write_bytes(data)
    res.update(status="downloaded", file=str(dst),
               reason=f"{len(data)} bytes from {src[:90]}",
               warning=check_pdf_identity(data, doi, title))
    return res


# --- presets and the retry loop -----------------------------------------

# Only these statuses are worth another attempt. "unsupported" and "skipped"
# are settled facts (not a journal article, no journal abbreviation, already on
# disk); retrying them just asks Crossref the same question again.
SRETRIABLE = {"failed", "no_pdf_link", "fetch_failed", "error"}

# Retrying a Cloudflare challenge straight away fails again, and a burst of
# instant retries is itself part of what the wall scores.
RETRY_BACKOFF = 45

DEFAULTS = {"retries": 0, "human_wait": 0, "skip_existing": False, "timeout": 300}

PRESETS = {
    # An agent reruns the script itself when it sees a failure, so in-script
    # retries would only multiply the wall clock and the publisher's load. It
    # also cannot solve an image captcha, so surfacing the window is pointless.
    "agent": {"retries": 0, "human_wait": 0, "skip_existing": True, "timeout": 300},
    # A person running this by hand has no such outer loop, and can clear a
    # captcha when one does show up.
    "human": {"retries": 2, "human_wait": 120, "skip_existing": True, "timeout": 300},
}


def apply_preset(args):
    """Fill in whatever the caller left unset: preset first, then bare defaults.

    Every preset-controlled option parses with None as its default, so an
    explicit flag is distinguishable from an unset one and always wins over the
    preset. Returns the same namespace, mutated.
    """
    for key, value in {**DEFAULTS, **PRESETS.get(args.preset, {})}.items():
        if getattr(args, key, None) is None:
            setattr(args, key, value)
    if args.preset and not args.report:
        # A preset run is unattended by definition, so it gets the machine
        # readable record without the caller having to remember the flag.
        args.report = str(Path(args.output) / "report.json")
    return args


def write_report(path_report, ldoi, dresult):
    """Rewrite the whole report, in input order, one entry per DOI.

    Appending would put a retried DOI in the file twice, which silently breaks
    every count downstream of it.
    """
    if not path_report:
        return
    Path(path_report).parent.mkdir(parents=True, exist_ok=True)
    lordered = [dresult[doi] for doi in ldoi if doi in dresult]
    Path(path_report).write_text(
        json.dumps(lordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def download_doi(args, doi, out_dir, label):
    """Name, skip or download one DOI. Returns a status dict."""
    # Name before browsing: an unsupported record must be reported and skipped,
    # not downloaded and then discarded.
    name, reason, title = get_output_name(doi)
    if reason:
        print(f"\u23ed  {label} {doi}  ({reason})")
        return {"doi": doi, "status": "unsupported", "file": None,
                "state": "", "reason": reason}
    dst = out_dir / name
    if args.skip_existing and dst.exists():
        print(f"\u23ed  {label} {doi}  -> {name} (exists)")
        return {"doi": doi, "status": "skipped", "file": str(dst),
                "state": "", "reason": "already downloaded"}
    print(f"\u25b6\ufe0f  {label} {doi}  -> {name}")
    try:
        res = download_one(args.cdp, doi, out_dir, args.timeout,
                           args.human_wait, name, title)
    except Exception as exc:
        res = {"doi": doi, "status": "error", "file": None,
               "state": "", "reason": str(exc)[:200]}
    print(f"   {res['status']}: {res['reason']}")
    if res.get("warning"):
        print(f"   \u26a0\ufe0f  {res['warning']}")
    return res


def download_batch(args, ldoi, out_dir):
    """Run the list, then re-run only what failed. Results in input order.

    Off by default (--retries 0): under an agent the outer loop already is the
    retry, and doubling it wastes time and publisher goodwill. A person running
    this by hand has no outer loop, which is what --preset human turns it on
    for.
    """
    dresult = {}
    for attempt in range(max(0, args.retries) + 1):
        lpending = [doi for doi in ldoi
                    if dresult.get(doi, {}).get("status", "failed") in SRETRIABLE]
        if not lpending:
            break
        if attempt:
            print(f"\n\U0001f501 \u7b2c {attempt + 1} \u8f6e\uff0c\u91cd\u8bd5 "
                  f"{len(lpending)} \u7bc7\uff08\u5148\u9000\u907f {RETRY_BACKOFF}s\uff09")
            time.sleep(RETRY_BACKOFF)
        for i, doi in enumerate(lpending, 1):
            res = download_doi(args, doi, out_dir, f"[{i}/{len(lpending)}]")
            res["attempts"] = attempt + 1
            dresult[doi] = res
            write_report(args.report, ldoi, dresult)
    return [dresult[doi] for doi in ldoi]


def selftest():
    """Offline check of the orchestration and the two vendored modules."""
    # page-state classification
    assert get_page_state("<html>Just a moment...</html>", "https://x/") == "cloudflare"
    assert get_page_state("<html/>", "https://x/a/1.pdf") == "pdf_ready"
    assert get_page_state("<html>hcaptcha</html>", "https://x/") == "captcha"
    assert get_page_state("<html>citation_pdf_url</html>", "https://x/") == "article"

    # host rules: the publishers whose advertised link does not serve the file
    assert get_publisher_pdf_url(
        "https://journals.aps.org/prb/abstract/10.1103/PhysRevB.88.064104"
    ) == "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.88.064104"
    assert get_publisher_pdf_url("https://example.org/article") is None

    # candidate filtering: supplements and cited papers must never win
    assert check_supplement_url("https://pubs.acs.org/doi/suppl/10.1/x_si_001.pdf")
    page_url = "https://example.org/doi/10.1000/abc"
    assert filter_pdf_candidates(
        ["https://example.org/doi/suppl/10.1000/abc_si_001.pdf",
         "https://elsewhere.org/cited-paper.pdf",
         "https://example.org/doi/pdf/10.1000/abc"],
        "10.1000/abc", page_url) == ["https://example.org/doi/pdf/10.1000/abc"]

    # DOI parsing and naming
    assert normalize_doi("https://doi.org/10.1038/nature12373") == "10.1038/nature12373"
    dict_metadata = {
        "type": "journal-article",
        "title": ["Synthesis of bulk hexagonal diamond"],
        "container-title": ["Nature"],
        "published-print": {"date-parts": [[2013]]},
    }
    assert generate_pdf_filename(dict_metadata) == "2013-NATURE-Synthesis-o.pdf"
    assert check_journal_metadata({**dict_metadata, "type": "posted-content"})
    assert check_journal_metadata(
        {**dict_metadata, "container-title": ["Journal of Nowhere"]})

    # orchestration
    assert cdp_download("http://127.0.0.1:1", [], 1) == (None, "")
    assert DOWNLOAD_DIR == Path.home() / ".pj" / "p-literature-download" / "downloads"
    assert PROFILE_DIR.parent == DOWNLOAD_DIR.parent
    assert get_download_dir(Path("no/such/profile")) == DOWNLOAD_DIR

    # presets: an explicit flag always beats the preset
    def ns(**kw):
        base = dict(preset=None, output=".", report="", retries=None,
                    human_wait=None, skip_existing=None, timeout=None)
        return argparse.Namespace(**{**base, **kw})

    args = apply_preset(ns(preset="human"))
    assert (args.retries, args.human_wait, args.skip_existing) == (2, 120, True)
    assert args.report.endswith("report.json")
    args = apply_preset(ns(preset="agent"))
    assert (args.retries, args.human_wait, args.skip_existing) == (0, 0, True)
    args = apply_preset(ns(preset="human", retries=0, report="r.json"))
    assert args.retries == 0 and args.report == "r.json"
    args = apply_preset(ns())
    assert (args.retries, args.timeout, args.report) == (0, 300, "")

    # a settled verdict must never be retried
    assert not SRETRIABLE & {"unsupported", "skipped", "downloaded"}

    # the report keeps input order and one entry per DOI, however often retried
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path_report = Path(tmp) / "r.json"
        write_report(path_report, ["a", "b"], {"b": {"doi": "b"}, "a": {"doi": "a"}})
        assert [r["doi"] for r in json.loads(path_report.read_text())] == ["a", "b"]
    print("✅ selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dois", nargs="?", help="DOI list file")
    ap.add_argument("-o", "--output", default=".")
    ap.add_argument("--preset", choices=sorted(PRESETS),
                    help="agent: no in-script retry, no captcha prompt, because "
                         "the agent reruns on failure. human: 2 retries, 120s "
                         "captcha wait. An explicit flag overrides the preset.")
    ap.add_argument("--timeout", type=int, default=None,
                    help="seconds per stage per DOI (default 300); a 20MB+ review "
                         "needs well over 180")
    ap.add_argument("--retries", type=int, default=None,
                    help="extra passes over the DOIs that failed (default 0)")
    ap.add_argument("--human-wait", type=int, default=None,
                    help="extra seconds granted after surfacing the tab on a captcha")
    ap.add_argument("--cdp", default="http://127.0.0.1:9333",
                    help="CDP endpoint of the automation Edge")
    ap.add_argument("--profile-dir", default=str(PROFILE_DIR),
                    help="Edge profile dir to read the download folder from")
    ap.add_argument("--download-dir", default="",
                    help="override the folder watched for browser downloads")
    ap.add_argument("--skip-existing", action="store_true", default=None)
    ap.add_argument("--report", default="")
    ap.add_argument("--selftest", action="store_true")
    args = apply_preset(ap.parse_args())
    if args.selftest:
        return selftest()

    ldoi = parse_dois(Path(args.dois))
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    check_endpoint(args.cdp)

    # Edge decides where downloads land, so take the folder from its own
    # profile rather than assuming. Bound once here, before any worker reads it.
    global DOWNLOAD_DIR
    DOWNLOAD_DIR = (Path(args.download_dir) if args.download_dir
                    else get_download_dir(args.profile_dir))
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Get the window out of the way once; background tabs keep it there.
    set_window_state(args.cdp, "minimized")
    print(f"\U0001f4e1 {args.cdp}  \u00b7  {len(ldoi)} DOIs  ->  {out_dir}")
    print(f"\U0001f4e5 \u6d4f\u89c8\u5668\u4e0b\u8f7d\u76ee\u5f55\uff1a{DOWNLOAD_DIR}")
    if args.preset:
        print(f"\u2699\ufe0f  preset {args.preset}\uff1aretries={args.retries} "
              f"human-wait={args.human_wait} timeout={args.timeout}")

    results = download_batch(args, ldoi, out_dir)
    write_report(args.report, ldoi, {r["doi"]: r for r in results})

    ok = sum(1 for r in results if r["status"] in ("downloaded", "skipped"))
    print(f"\n\U0001f4ca {ok}/{len(results)}")
    lretried = [r for r in results if r.get("attempts", 1) > 1]
    if lretried:
        nfixed = sum(1 for r in lretried if r["status"] == "downloaded")
        print(f"\U0001f501 {len(lretried)} \u7bc7\u8d70\u4e86\u91cd\u8bd5\uff0c"
              f"\u5176\u4e2d {nfixed} \u7bc7\u91cd\u8bd5\u540e\u6210\u529f")
    # Advisory only - these files were kept. Collecting them here matters,
    # because a single line per DOI is lost in a long run.
    lwarn = [r for r in results if r.get("warning")]
    if lwarn:
        print(f"\n\u26a0\ufe0f  {len(lwarn)} \u7bc7\u5185\u5bb9\u6838\u5bf9\u672a"
              "\u901a\u8fc7\uff08\u6587\u4ef6\u5df2\u4fdd\u7559\uff0c\u8bf7\u81ea"
              "\u884c\u786e\u8ba4\uff09\uff1a")
        for r in lwarn:
            fname = Path(r["file"]).name if r["file"] else ""
            print(f"   {r['doi']}  {fname}  \u2014\u2014 {r['warning']}")
    raise SystemExit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
