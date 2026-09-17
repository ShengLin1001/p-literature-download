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
4. Detach Playwright entirely, then open the URL in a bare CDP tab.

Elsevier is the awkward one, and not for the reason it looks. Its PDF link
opens a Cloudflare challenge on pdf.sciencedirectassets.com in a *new* tab,
where it sits at "Request Verification: In Progress" until something clicks
the Turnstile - which nothing did, because the driven tab still reads as the
article. Measured: foreground or background, with or without a Referer, from
a real click or a bare navigation, it hangs the same; one human-shaped click
on that tab clears it every time. Hence clear_sibling_challenges.

Every tab is created in the background and the window is minimized once per
run, so a batch does not keep raising Edge onto the user's desktop. Only
-human_wait restores it, because a captcha has to be visible to be solved.

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

All local state lives under one -data_dir (default ~/.pj/p-literature-download):
profile/ for the logged-in Edge session, download/ for what Edge drops.

--no-proxy-server matters as much as the profile: through the system proxy,
Cloudflare scores the exit IP badly enough to stall the same downloads.

The daily Edge's runtime-enabled port (edge://inspect) is not usable here: it
serves no /json/* endpoints and stops accepting WebSocket handshakes after
the first client disconnects.

Two presets cover the callers. -preset agent turns in-script retries and the
captcha prompt off, because an agent reruns the script itself on failure and
cannot solve an image captcha either way; -preset human turns both on, because
a person running this by hand has no outer loop. An explicit flag beats both.

The folder watched for browser downloads is read from the Edge profile rather
than assumed: Edge decides where a file lands, and watching the wrong folder
makes tier 4 and the manual-download takeover fail without saying anything.

Usage:
    python edge_download.py dois.txt -output outdir -preset agent
    python edge_download.py dois.txt -output outdir -preset human
    python edge_download.py -selftest
"""

import argparse
import base64
import json
import random
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

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
    get_article_entry_url, get_page_state, get_publisher_pdf_url,
    get_url_origin)
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

    Turnstile only, deliberately. The hCaptcha checkbox Radware puts in front
    of IOP looks clickable, but ticking it escalates to an image challenge,
    so clicking it just burns time and hardens the score - that one goes to a
    human through ``-human_wait``.
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

WEBVPN_HOME = "https://webvpn.zju.edu.cn/"
WEBVPN_HOST = "webvpn.zju.edu.cn"
WEBVPN_SEARCH = 'input[placeholder="输入网址直接访问内网或图书馆资源"]'
WEBVPN_LOGIN_ATTEMPTED = False


def check_webvpn_url(url: str) -> bool:
    """Return whether URL is a publisher route generated by ZJU WebVPN."""
    return bool(re.match(
        r"^https://webvpn\.zju\.edu\.cn/(?:https?|http)/[^/]+/", url or "", re.I))


def normalize_webvpn_candidate(page_url: str, url: str) -> str:
    """Restore the current proxy origin when page markup omits its route prefix."""
    if check_webvpn_url(url) or urlsplit(url).netloc.lower() != WEBVPN_HOST:
        return url
    match = re.match(r"^/(https?|http)/([^/]+)", urlsplit(page_url).path, re.I)
    if not match:
        return url
    parsed = urlsplit(url)
    prefix = f"{WEBVPN_HOME}{match.group(1)}/{match.group(2)}"
    return prefix + parsed.path + (("?" + parsed.query) if parsed.query else "")


def pdf_candidates(page, doi="", webvpn=False):
    """PDF URLs to try, best first.

    A host rule outranks the page's own citation_pdf_url, because some
    publishers advertise a link that only redirects back to the abstract.
    """
    ldom = []
    try:
        ldom = page.evaluate(JS_FIND_PDF_URLS) or []
    except Exception:
        pass
    # Direct host rules cannot be applied to an opaque WebVPN hostname. Its DOM
    # links are already rewritten; discard any metadata URL that escaped rewrite.
    lurl = ([] if webvpn else [get_publisher_pdf_url(page.url)]) + list(ldom)
    if webvpn:
        lurl = [normalize_webvpn_candidate(page.url, url) for url in lurl]
        lurl = [url for url in lurl if check_webvpn_url(url)]
    return filter_pdf_candidates([u for u in lurl if u], doi, page.url)


# --- human takeover -----------------------------------------------------

def check_pdf_tab(page) -> bool:
    """Return whether this tab is currently displaying a PDF."""
    try:
        return bool(page.evaluate(JS_IS_PDF_DOCUMENT))
    except Exception:
        return False


def check_takeover_pdf(data: bytes, doi: str, title: str,
                       source: str, srejected: set) -> bool:
    """Accept an arbitrary takeover PDF only when its identity is verified."""
    warning = check_pdf_identity(data, doi, title)
    if not warning:
        return True
    srejected.add(source)
    print(f"   ⚠️  忽略与当前文献不匹配的接管 PDF：{warning}（{source[:60]}）")
    return False


def grab_takeover_pdf(page, doi, title="", srejected=None):
    """Capture the requested PDF the user opened in this or another tab.

    Takeover needs no flag and never blocks: the resolve loop re-reads the
    tabs every few seconds, so clearing a challenge, signing in, or opening
    the PDF yourself is simply noticed on the next pass. Publishers like
    Nature and IEEE open the PDF in a *new* tab, which is why every tab is
    scanned rather than just the one the script drives.

    Unlike a publisher candidate URL, an arbitrary open tab is not tied to
    the current DOI. Reject it unless its text identifies this article; this
    prevents a stale PDF from being renamed as the next one.

    Returns (pdf_bytes_or_None, source_url).
    """
    srejected = srejected if srejected is not None else set()
    lpage = [page] + [pg for pg in page.context.pages if pg is not page]
    for pg in lpage:
        try:
            if (pg.url in srejected or not check_pdf_tab(pg)
                    or check_supplement_url(pg.url)):
                continue
            data = fetch_in_page(pg, pg.url)
            if data and check_takeover_pdf(data, doi, title, pg.url, srejected):
                return data, pg.url
        except Exception:
            pass
    return None, ""


def clear_sibling_challenges(page) -> bool:
    """Click Turnstile on challenge tabs sitting beside the one we drive.

    Elsevier serves the file through a challenge on
    pdf.sciencedirectassets.com that opens in a *new* tab. The driven tab still
    reads as the article, so the loop's own cloudflare branch never fires and
    the challenge sits at "Request Verification: In Progress" until the
    deadline. One human-shaped click there clears it and the tab lands on the
    real asset, which grab_takeover_pdf then reads same-origin on the next
    pass - the same reason that helper scans every tab rather than just this
    one.

    Returns whether a challenge tab was found and clicked.
    """
    clicked = False
    for pg in page.context.pages:
        if pg is page:
            continue
        try:
            if get_page_state(pg.content(), pg.url) != "cloudflare":
                continue
            if click_turnstile_human(pg):
                clicked = True
                print("   🖱  cloudflare: 拟人化点击邻接标签页的 Turnstile"
                      + f"（{pg.url[:60]}）")
        except Exception:
            pass
    return clicked


def close_stale_pdf_tabs(page) -> None:
    """Close PDF and challenge tabs left over from an earlier DOI.

    Takeover scans every tab and a PDF tab outlives the article that opened
    it, so without this the next DOI captures the previous article's PDF as
    its own. Challenge tabs leak the same way - a publisher opens them with
    target=_blank and nothing closes them - and they pile up until every pass
    re-reads a dozen dead challenges. Only these two kinds are touched; the
    user's own tabs are left alone.
    """
    for pg in page.context.pages:
        if pg is page:
            continue
        try:
            if check_pdf_tab(pg) or get_page_state(
                    pg.content(), pg.url) in ("cloudflare", "captcha"):
                pg.close()
        except Exception:
            pass


def get_challenge_state(page, state: str) -> str:
    """Report a challenge still standing as the state, wherever its tab is.

    Two things depend on this. Every candidate failing reads as "links not
    retrievable", which points at the links; if a tab is in fact sitting on a
    challenge, that is the real reason - a captcha means ``-human_wait`` is
    the lever, and Cloudflare means the loop should go round again and click
    it rather than give up with the challenge left standing.
    """
    for pg in [page] + [pg for pg in page.context.pages if pg is not page]:
        try:
            found = get_page_state(pg.content(), pg.url)
            if found in ("cloudflare", "captcha"):
                return found
        except Exception:
            pass
    return state


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
    Restoring is only for the ``-human_wait`` path, where the user has to see
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


def find_webvpn_home(context):
    """Return the WebVPN portal tab (home or login), never a proxied page.

    An expired session leaves the launcher's tab on /login. Matching only the
    bare root made every run skip that tab and log in from a second one.
    """
    lportal = [page for page in context.pages
               if urlsplit(page.url).netloc.lower() == WEBVPN_HOST
               and not check_webvpn_url(page.url)]
    # A logged-in home beats a stale login tab left beside it.
    lportal.sort(key=lambda page: page.url.rstrip("/") != WEBVPN_HOME.rstrip("/"))
    return lportal[0] if lportal else None


def get_webvpn_credential(data_dir=None) -> tuple[str, str]:
    """Read this Windows user's DPAPI-protected credential for the profile."""
    path_credential = Path(data_dir or DATA_DIR) / "profile" / "webvpn-credential.clixml"
    if not path_credential.is_file():
        raise RuntimeError("WebVPN 凭据未初始化；请重新运行 scripts/start_edge.ps1")
    script = (
        "& { param($path);$c=Import-Clixml -LiteralPath $path;"
        "$b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($c.Password);"
        "try {[Console]::Out.Write($c.UserName+[char]0+"
        "[Runtime.InteropServices.Marshal]::PtrToStringBSTR($b))}"
        "finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b)} }")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script, str(path_credential)],
        capture_output=True, text=True, encoding="utf-8", check=True)
    username, separator, password = done.stdout.partition("\0")
    if not separator or not username or not password:
        raise RuntimeError("WebVPN 凭据无法读取；请重新运行 start_edge.ps1 -initialize_credentials")
    return username, password


def login_webvpn(page, endpoint: str, human_wait: int) -> bool:
    """Log in once when the persistent WebVPN session has expired."""
    global WEBVPN_LOGIN_ATTEMPTED
    if WEBVPN_LOGIN_ATTEMPTED:
        raise RuntimeError("WebVPN 自动登录已失败；请人工确认或更新 profile 凭据")
    WEBVPN_LOGIN_ATTEMPTED = True
    username, password = get_webvpn_credential()
    page.locator("#user_name").fill(username)
    page.locator('input[name="password"]').first.fill(password)
    page.locator("#login").click()
    # A server-side session left by an earlier run (or another device) makes
    # the portal ask "该账号已经登录，继续登录将踢掉其他已登录账号" and wait
    # forever. This profile is the one that has to work, so take the seat.
    deadline = time.time() + 20
    while time.time() < deadline:
        if page.locator(WEBVPN_SEARCH).is_visible():
            return True
        kick = page.locator(".layui-layer-btn0")
        if kick.is_visible() and "踢掉" in page.inner_text("body"):
            print("   🔑 WebVPN：账号已在别处登录，点「继续」顶掉旧会话")
            kick.click()
        time.sleep(1)
    try:
        page.locator(WEBVPN_SEARCH).wait_for(state="visible", timeout=1000)
        return True
    except Exception:
        if not human_wait:
            raise RuntimeError("WebVPN 登录需要验证码或二次确认，请用 -preset human")
        set_window_state(endpoint, "normal")
        page.bring_to_front()
        print(f"   🖐  WebVPN：请完成验证码或二次确认，最多等 {human_wait}s")
        page.locator(WEBVPN_SEARCH).wait_for(
            state="visible", timeout=human_wait * 1000)
        return True


def ensure_webvpn_home(context, endpoint: str, human_wait: int):
    """Reuse or open the authenticated WebVPN homepage."""
    home = find_webvpn_home(context) or context.new_page()
    if home.url.rstrip("/") != WEBVPN_HOME.rstrip("/"):
        home.goto(WEBVPN_HOME, wait_until="domcontentloaded", timeout=90000)
    try:
        home.locator(WEBVPN_SEARCH).wait_for(state="visible", timeout=10000)
    except Exception:
        if get_page_state(home.content(), home.url) != "webvpn_login":
            raise RuntimeError("WebVPN 首页未出现网址输入框")
        login_webvpn(home, endpoint, human_wait)
    return home


def get_page_list(endpoint: str) -> list:
    """Return ``(target_id, url)`` for every open page target."""
    with urllib.request.urlopen(endpoint.rstrip("/") + "/json/list", timeout=10) as fh:
        return [(t["id"], t.get("url", "")) for t in json.load(fh)
                if t.get("type") == "page"]


def open_via_webvpn(endpoint: str, home, page, target_url: str) -> str:
    """Submit one URL through the portal and leave its proxied page in ``page``.

    The portal opens the proxied page in a *new* tab, and Playwright only
    adopts targets that existed when connect_over_cdp ran, so
    ``context.pages`` never shows it - waiting there always timed out with
    "WebVPN 未生成代理网址" although the tab was open. Read raw CDP instead,
    move the URL into the driven tab, and close the portal's copy.
    """
    home.bring_to_front()
    home.locator(WEBVPN_SEARCH).fill(target_url)
    target_path = urlsplit(target_url).path.strip("/")
    target_doi = re.search(r"10\.\d{4,9}/[^?#]+", target_url, re.I)
    home.locator(".portal-search__button").click()
    deadline = time.time() + 90
    while time.time() < deadline:
        for tid, url in get_page_list(endpoint):
            same_target = bool(target_path) and target_path in urlsplit(url).path
            if target_doi and target_doi.group(0).lower() in url.lower():
                same_target = True
            if not check_webvpn_url(url) or not same_target or url == page.url:
                continue
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            if url == home.url:
                home.goto(WEBVPN_HOME, wait_until="domcontentloaded", timeout=90000)
            else:
                try:
                    urllib.request.urlopen(urllib.request.Request(
                        endpoint.rstrip("/") + "/json/close/" + tid,
                        method="PUT"), timeout=10).close()
                except OSError:
                    pass
            return page.url
        time.sleep(1)
    raise RuntimeError("WebVPN 未生成代理网址")


# One knob for every bit of local state this skill keeps: -data_dir, holding
# profile/ (the logged-in Edge session) and download/ (where Edge drops files).
# start_edge.ps1 takes the same -data_dir and lays out the same two names.
DATA_DIR = Path.home() / ".pj" / "p-literature-download"
PROFILE_DIR = DATA_DIR / "profile"
DOWNLOAD_DIR = DATA_DIR / "download"


def get_download_dir(data_dir=DATA_DIR) -> Path:
    """Read the download folder out of the Edge profile that will serve us.

    Edge - not this script - decides where a file lands, and start_edge.ps1
    writes the folder into the profile, so the profile is the source of truth.
    Watching the wrong folder makes tier 4 and the manual-download takeover
    fail silently, which reads like a publisher problem rather than a wrong
    path. Falls back to <data_dir>/download when the profile does not exist yet.
    """
    data_dir = Path(data_dir)
    try:
        # utf-8-sig, not utf-8: a byte-order mark is a JSON parse error, and
        # anything that writes this file from PowerShell can leave one behind.
        prefs = json.loads((data_dir / "profile" / "Default" / "Preferences")
                           .read_text(encoding="utf-8-sig"))
        directory = (prefs.get("download") or {}).get("default_directory")
        if directory:
            return Path(directory)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return data_dir / "download"


def snapshot_downloads(watch_dir: Path = None) -> set:
    """Names already in the browser's download folder."""
    try:
        return {f.name for f in (watch_dir or DOWNLOAD_DIR).iterdir()}
    except OSError:
        return set()


def grab_downloaded_pdf(sbefore, doi, title="", watch_dir: Path = None,
                        srejected=None):
    """Pick up the requested PDF that the user's click downloaded.

    A publisher answering with Content-Disposition: attachment never shows the
    file in a tab, so scanning tabs cannot see it. The baseline is taken once
    when the article opens and every poll diffs against it. Because a user can
    still save another tab after that baseline, accept only a file whose text
    identifies the current article.

    Returns (pdf_bytes_or_None, source_label).
    """
    watch_dir = watch_dir or DOWNLOAD_DIR
    srejected = srejected if srejected is not None else set()
    try:
        lnew = [f for f in watch_dir.iterdir()
                if f.name not in sbefore and f.is_file()
                and not f.name.endswith(".crdownload")]
    except OSError:
        return None, ""
    for path_new in lnew:
        source = "下载目录/" + path_new.name
        if source in srejected:
            continue
        try:
            data = path_new.read_bytes()
        except OSError:
            continue
        if not data.startswith(b"%PDF-"):
            continue
        if not check_takeover_pdf(data, doi, title, source, srejected):
            continue
        try:
            path_new.unlink()   # consumed; the copy that matters goes to out_dir
        except OSError:
            pass
        return data, source
    return None, ""


TAKEOVER_POLL_INTERVAL = 5
TAKEOVER_POLL_TIMEOUT = 60


def poll_takeover_pdf(page, sbefore, doi, title, srejected,
                      timeout=TAKEOVER_POLL_TIMEOUT):
    """Rescan at 5/10/.../60s while a PDF navigation settles."""
    next_click = 0.0
    for elapsed in range(TAKEOVER_POLL_INTERVAL, timeout + 1,
                         TAKEOVER_POLL_INTERVAL):
        # The caller already spent the first 5s waiting for a download event.
        if elapsed > TAKEOVER_POLL_INTERVAL:
            time.sleep(TAKEOVER_POLL_INTERVAL)
        data, src = grab_takeover_pdf(page, doi, title, srejected)
        if not data:
            data, src = grab_downloaded_pdf(
                sbefore, doi, title, srejected=srejected)
        if data:
            return data, src

        # A PDF navigation may first land on Turnstile. Keep the same 20s click
        # cadence as the outer loop; otherwise polling would only watch a wall.
        if time.time() >= next_click:
            hit = False
            try:
                if get_page_state(page.content(), page.url) == "cloudflare":
                    hit = click_turnstile_human(page)
            except Exception:
                pass
            if clear_sibling_challenges(page) or hit:
                next_click = time.time() + 20
    return None, ""


def check_pdf_identity(data: bytes, doi: str, title: str) -> str:
    """Report when a PDF does not look like the requested article.

    For a PDF fetched from a publisher candidate URL this remains advisory:
    old papers may omit their DOI and scans extract poorly. Arbitrary takeover
    tabs and new download-folder files use the same result as a strict gate,
    because accepting an unverified file there can silently rename another
    article as this one.

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
    with page.expect_download(timeout=min(TAKEOVER_POLL_INTERVAL, timeout) * 1000) as info:
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
    if not check_pdf_tab(page):
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

def resolve_candidates(endpoint, page, doi, title, timeout, human_wait,
                       publisher_url="", webvpn=False):
    """Open an article directly or through WebVPN, then resolve its PDF."""
    asked_human = False
    tried_institution = False
    accepted_consent = False
    next_click = 0.0
    lost_since = 0.0
    relanded = 0
    state = "navigating"
    sbefore = snapshot_downloads()
    srejected = set()
    try:
        home = None
        if webvpn:
            home = ensure_webvpn_home(page.context, endpoint, human_wait)
            open_via_webvpn(endpoint, home, page, publisher_url or "https://doi.org/" + doi)
        else:
            goto_article(page, doi)
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
            data, src = grab_takeover_pdf(page, doi, title, srejected)
            if not data:
                data, src = grab_downloaded_pdf(
                    sbefore, doi, title, srejected=srejected)
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
                    print(f"   ↩️  偏离到 {page.url[:60]}，退回文章入口重来")
                    if webvpn:
                        open_via_webvpn(
                            endpoint, home, page, publisher_url or "https://doi.org/" + doi)
                    else:
                        goto_article(page, doi)
                    continue
            else:
                lost_since = 0.0

            # Cloudflare is the script's job: keep re-clicking the Turnstile
            # checkbox with human-shaped motion until it lets go.
            if state == "cloudflare":
                if time.time() >= next_click:
                    next_click = time.time() + 20
                    hit = click_turnstile_human(page)
                    print("   🖱  cloudflare: "
                          + ("拟人化点击 Turnstile" if hit else "没找到 Turnstile 框，等它自己过")
                          + f"（{page.url[:60]}）")
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

            # A Cloudflare challenge can also be one tab over (Elsevier opens
            # it there), in which case this tab still reads as the article.
            if time.time() >= next_click and clear_sibling_challenges(page):
                next_click = time.time() + 20
                time.sleep(random.uniform(6, 10))
                continue

            if not accepted_consent:
                accepted_consent = True
                try:
                    if page.evaluate(JS_ACCEPT_CONSENT):
                        page.wait_for_timeout(2500)
                        continue
                except Exception:
                    pass

            urls = pdf_candidates(page, doi, webvpn)
            if urls:
                data, src = fetch_any_in_page(page, urls)
                if not data:
                    # Escalate: force a download, then - for hosts that render
                    # the PDF inline instead - fetch it same-origin.
                    for grab in (fetch_by_download, fetch_after_navigate):
                        for url in urls:
                            # Look at the tabs between short attempts so a PDF
                            # that just opened is accepted without waiting for
                            # every remaining candidate and fetch tier.
                            data, src = grab_takeover_pdf(
                                page, doi, title, srejected)
                            if data:
                                break
                            try:
                                data = grab(
                                    page, url,
                                    min(TAKEOVER_POLL_INTERVAL, timeout))
                            except Exception:
                                data = None
                            if data:
                                src = url
                                break
                            # The navigation may render a PDF viewer or a
                            # Turnstile tab instead of firing a download event.
                            # Keep this route alive and inspect it at
                            # 5/10/.../60s before moving to the next one.
                            data, src = poll_takeover_pdf(
                                page, sbefore, doi, title, srejected,
                                min(TAKEOVER_POLL_TIMEOUT, timeout))
                            if data:
                                break
                        if data:
                            break
                if data:
                    return urls, state, data, src

                # The escalation usually *leaves a challenge standing* - that
                # is what navigating to an Elsevier PDF does. Returning here
                # reports "links not retrievable" with the challenge still up
                # and nothing ever clicking it, so go round again and let the
                # click branches above have it. The deadline bounds the loop.
                challenge = get_challenge_state(page, state)
                if challenge == "cloudflare":
                    continue
                if tried_institution:
                    return urls, challenge, data, src
                # Links are there but unreadable: usually the institution
                # is not signed in yet on this publisher. Sign in and retry.
                tried_institution = True
                if not webvpn and try_institution_login(page):
                    continue
                return urls, challenge, None, ""

            # No PDF link at all: publishers hide it until access is granted.
            if not tried_institution:
                tried_institution = True
                if not webvpn and try_institution_login(page):
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


def goto_article(page, doi):
    """Open a DOI and land on the article host, not a stalling landing host."""
    page.goto("https://doi.org/" + doi, wait_until="domcontentloaded", timeout=90000)
    entry = get_article_entry_url(page.url)
    if entry != page.url:
        page.goto(entry, wait_until="domcontentloaded", timeout=90000)


def get_output_name(doi):
    """Resolve naming metadata and the official publisher entry URL."""
    dict_metadata = fetch_doi_metadata(doi)
    reason = check_journal_metadata(dict_metadata)
    if reason:
        return None, reason, "", ""
    ltitle = (dict_metadata or {}).get("title") or [""]
    publisher_url = (((dict_metadata or {}).get("resource") or {})
                     .get("primary") or {}).get("URL", "")
    if not publisher_url:
        url = (dict_metadata or {}).get("URL", "")
        if url and urlsplit(url).netloc.lower() != "doi.org":
            publisher_url = url
    if not re.match(r"^https?://", publisher_url, re.I):
        publisher_url = "https://doi.org/" + doi
    publisher_url = get_article_entry_url(publisher_url)
    name = generate_pdf_filename(
        dict_metadata, doi=doi, path_cache=DATA_DIR / "journal_abbreviations.json")
    return (name, None, ltitle[0],
            publisher_url)


def download_one(endpoint, doi, out_dir, timeout, human_wait, name, title="",
                 publisher_url=""):
    """Try the direct publisher path, then WebVPN once if it fails."""
    from playwright.sync_api import sync_playwright

    res = {"doi": doi, "status": "failed", "file": None, "state": "",
           "reason": "", "warning": "", "access_via": "direct"}
    token = open_background_tab(endpoint)  # must exist before Playwright connects
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint, timeout=30000)
        page = get_tab_by_token(browser.contexts[0], token)
        close_stale_pdf_tabs(page)
        urls, state, data, src = resolve_candidates(
            endpoint, page, doi, title, timeout, human_wait)
        # Never browser.close(): on a CDP attachment that tears the DevTools
        # server down and Edge stops accepting clients.
    if not data and urls:
        data, src = cdp_download(endpoint, urls, min(120, timeout))

    direct_state = state
    if not data:
        print("   ↪️  直连未取到 PDF，改走浙江大学 WebVPN")
        token = open_background_tab(endpoint)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(endpoint, timeout=30000)
            page = get_tab_by_token(browser.contexts[0], token)
            close_stale_pdf_tabs(page)
            urls, state, data, src = resolve_candidates(
                endpoint, page, doi, title, timeout, human_wait,
                publisher_url=publisher_url, webvpn=True)
        if not data and urls:
            data, src = cdp_download(endpoint, urls, min(120, timeout))
        res["access_via"] = WEBVPN_HOST

    res["state"] = state
    if not data:
        if state == "captcha":
            res.update(status="captcha",
                       reason="图形验证未通过，用 -human_wait 120 自己点，或手动接管")
        else:
            res.update(
                status="fetch_failed" if urls else "no_pdf_link",
                reason=f"direct state {direct_state}; webvpn state {state}")
        return res
    dst = Path(out_dir) / name
    dst.write_bytes(data)
    res.update(status="downloaded", file=str(dst),
               reason=f"{len(data)} bytes via {res['access_via']}",
               warning=check_pdf_identity(data, doi, title))
    return res


# --- presets and the retry loop -----------------------------------------

# Only these statuses are worth another attempt. "unsupported" and "skipped"
# are settled facts (supplementary material, already on disk); retrying them
# just asks the metadata service the same question again. "captcha" is settled
# for a different reason: an image challenge needs a person, and re-running it
# only feeds the bot score - it needs -human_wait or a manual takeover.
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


def write_report(path_report, ldoi, dict_result):
    """Rewrite the whole report, in input order, one entry per DOI.

    Appending would put a retried DOI in the file twice, which silently breaks
    every count downstream of it.
    """
    if not path_report:
        return
    Path(path_report).parent.mkdir(parents=True, exist_ok=True)
    lordered = [dict_result[doi] for doi in ldoi if doi in dict_result]
    Path(path_report).write_text(
        json.dumps(lordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def download_doi(args, doi, out_dir, label):
    """Name, skip or download one DOI. Returns a status dict."""
    # Name before browsing: an unsupported record must be reported and skipped,
    # not downloaded and then discarded.
    try:
        name, reason, title, publisher_url = get_output_name(doi)
    except OSError as exc:
        # The journal lookup could not be reached. Naming it some other way
        # would give this DOI a second filename, so report and retry later.
        print(f"\u274c {label} {doi}  (journal lookup failed: {exc})")
        return {"doi": doi, "status": "error", "file": None,
                "state": "", "reason": "journal lookup failed: " + str(exc)[:120]}
    if reason:
        print(f"\u23ed  {label} {doi}  ({reason})")
        return {"doi": doi, "status": "unsupported", "file": None,
                "state": "", "reason": reason}
    dst = out_dir / name
    # The DOI is part of the name, so the path alone answers "already here".
    if args.skip_existing and dst.exists():
        print(f"\u23ed  {label} {doi}  -> {name} (exists)")
        return {"doi": doi, "status": "skipped", "file": str(dst),
                "state": "", "reason": "already downloaded"}
    print(f"\u25b6\ufe0f  {label} {doi}  -> {name}")
    try:
        res = download_one(args.cdp, doi, out_dir, args.timeout,
                           args.human_wait, name, title, publisher_url)
    except Exception as exc:
        res = {"doi": doi, "status": "error", "file": None,
               "state": "", "reason": str(exc)[:200]}
    print(f"   {res['status']}: {res['reason']}")
    if res.get("warning"):
        print(f"   \u26a0\ufe0f  {res['warning']}")
    return res


def download_batch(args, ldoi, out_dir):
    """Run the list, then re-run only what failed. Results in input order.

    Off by default (-retries 0): under an agent the outer loop already is the
    retry, and doubling it wastes time and publisher goodwill. A person running
    this by hand has no outer loop, which is what -preset human turns it on
    for.
    """
    dict_result = {}
    for attempt in range(max(0, args.retries) + 1):
        lpending = [doi for doi in ldoi
                    if dict_result.get(doi, {}).get("status", "failed") in SRETRIABLE]
        if not lpending:
            break
        if attempt:
            print(f"\n\U0001f501 \u7b2c {attempt + 1} \u8f6e\uff0c\u91cd\u8bd5 "
                  f"{len(lpending)} \u7bc7\uff08\u5148\u9000\u907f {RETRY_BACKOFF}s\uff09")
            time.sleep(RETRY_BACKOFF)
        for i, doi in enumerate(lpending, 1):
            res = download_doi(args, doi, out_dir, f"[{i}/{len(lpending)}]")
            res["attempts"] = attempt + 1
            dict_result[doi] = res
            write_report(args.report, ldoi, dict_result)
    return [dict_result[doi] for doi in ldoi]


def selftest():
    """Offline check of the orchestration and the two vendored modules."""
    # page-state classification
    assert get_page_state("<html>Just a moment...</html>", "https://x/") == "cloudflare"
    assert get_page_state("<html/>", "https://x/a/1.pdf") == "pdf_ready"
    assert get_page_state("<html>hcaptcha</html>", "https://x/") == "captcha"
    assert get_page_state("<html>citation_pdf_url</html>", "https://x/") == "article"
    assert get_page_state(
        '<input id="user_name"><input name="password">',
        WEBVPN_HOME + "https/token/file.pdf") == "webvpn_login"
    assert check_webvpn_url(WEBVPN_HOME + "https/token/article")
    assert not check_webvpn_url(WEBVPN_HOME)

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
    webvpn_page = WEBVPN_HOME + "https/token-a/article"
    assert get_url_origin(webvpn_page) == "webvpn:token-a"
    assert filter_pdf_candidates(
        [WEBVPN_HOME + "https/token-b/cited.pdf",
         WEBVPN_HOME + "https/token-a/article.pdf"],
        "", webvpn_page) == [WEBVPN_HOME + "https/token-a/article.pdf"]

    # DOI parsing and naming
    assert normalize_doi("https://doi.org/10.1038/nature12373") == "10.1038/nature12373"
    dict_metadata = {
        "type": "journal-article",
        "title": ["Synthesis of bulk hexagonal diamond"],
        "container-title": ["Nature"],
        "published-print": {"date-parts": [[2013]]},
        "DOI": "10.1038/nature12373",
    }
    assert generate_pdf_filename(dict_metadata) == "2013-NATURE-Synthesis-o-nature12373.pdf"
    # Same title prefix, different DOI: the names must differ.
    assert generate_pdf_filename(dict_metadata, doi="10.1021/JACS.4c17739") == \
        "2013-NATURE-Synthesis-o-jacs.4c17739.pdf"
    assert generate_pdf_filename(dict_metadata, doi="10.31083/j.jin2206152/pdf") == \
        "2013-NATURE-Synthesis-o-j.jin2206152_pdf.pdf"
    # Preprints and journals outside the curated index are named, not refused.
    assert check_journal_metadata({**dict_metadata, "type": "posted-content"}) is None
    assert generate_pdf_filename(
        {**dict_metadata, "container-title": ["Journal of Nowhere"]}
    ) == "2013-JOURNAL-NOWHERE-Synthesis-o-nature12373.pdf"
    assert generate_pdf_filename(
        {**dict_metadata, "container-title": ["npj Computational Materials"],
         "short-container-title": ["npj Comput Mater"]}
    ) == "2013-NPJ-COMPUT-MATER-Synthesis-o-nature12373.pdf"
    assert generate_pdf_filename(
        {**dict_metadata, "type": "article", "container-title": [],
         "publisher": "arXiv"}) == "2013-ARXIV-Synthesis-o-nature12373.pdf"
    assert check_journal_metadata({**dict_metadata, "type": "component"})

    # Journal labels: a cached label is reused as-is and never looked up again;
    # NLM-style abbreviations keep one-letter words and drop "(Basel)".
    import tempfile
    import literature_download
    with tempfile.TemporaryDirectory() as tmp:
        path_cache = Path(tmp) / "journal_abbreviations.json"
        path_cache.write_text('{"0749-6419": "INT-J-PLAST"}', encoding="utf-8")
        original_nlm = literature_download.get_nlm_abbreviation
        literature_download.get_nlm_abbreviation = lambda issn, timeout=20: (
            {"0921-5093": "Mater Sci Eng A Struct Mater",
             "2075-4701": "Metals (Basel)"}.get(issn, ""))
        try:
            dict_plast = {**dict_metadata, "container-title": ["International Journal of Plasticity"],
                          "ISSN": ["0749-6419"]}
            assert generate_pdf_filename(dict_plast, path_cache=path_cache) == \
                "2013-INT-J-PLAST-Synthesis-o-nature12373.pdf"
            assert literature_download.get_journal_label(
                {"container-title": ["Materials Science and Engineering: A"],
                 "ISSN": ["0921-5093"]}, path_cache=path_cache) == "MATER-SCI-ENG-A-STRUCT-MATER"
            assert literature_download.get_journal_label(
                {"container-title": ["Metals"], "ISSN": ["2075-4701"]},
                path_cache=path_cache) == "METALS"
            # Unknown to NLM: Crossref's short title, then pinned in the cache.
            assert literature_download.get_journal_label(
                {"container-title": ["Nowhere Letters"], "short-container-title": ["Nowh. Lett."],
                 "ISSN": ["0000-0000"]}, path_cache=path_cache) == "NOWH-LETT"
            assert json.loads(path_cache.read_text(encoding="utf-8"))["0000-0000"] == "NOWH-LETT"
        finally:
            literature_download.get_nlm_abbreviation = original_nlm

    assert get_article_entry_url(
        "https://linkinghub.elsevier.com/retrieve/pii/S1359645425001234?via%3Dihub"
    ) == "https://www.sciencedirect.com/science/article/pii/S1359645425001234"
    assert get_article_entry_url("https://www.nature.com/articles/x") ==         "https://www.nature.com/articles/x"

    # orchestration
    assert cdp_download("http://127.0.0.1:1", [], 1) == (None, "")
    assert (PROFILE_DIR, DOWNLOAD_DIR) == (DATA_DIR / "profile", DATA_DIR / "download")
    assert get_download_dir(Path("no/such/dir")) == Path("no/such/dir") / "download"
    assert list(range(TAKEOVER_POLL_INTERVAL, TAKEOVER_POLL_TIMEOUT + 1,
                      TAKEOVER_POLL_INTERVAL)) == list(range(5, 61, 5))

    # Takeover sources are arbitrary; an identity mismatch must not be consumed.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path_download = Path(tmp)
        path_wrong = path_download / "previous.pdf"
        path_wrong.write_bytes(b"%PDF-wrong article")
        original_check = globals()["check_pdf_identity"]
        globals()["check_pdf_identity"] = lambda data, doi, title: "wrong article"
        try:
            srejected = set()
            assert grab_downloaded_pdf(
                set(), "10.1/current", "Current title", path_download,
                srejected) == (None, "")
            assert path_wrong.exists()
            assert srejected == {"下载目录/previous.pdf"}
        finally:
            globals()["check_pdf_identity"] = original_check

    # A rerun finds this DOI's file by name alone, no PDF reading.
    with tempfile.TemporaryDirectory() as tmp:
        path_dir = Path(tmp)
        (path_dir / "2025-JACS-Machine-Lea-jacs.4c17739.pdf").write_bytes(b"%PDF-")
        original_output = globals()["get_output_name"]
        globals()["get_output_name"] = lambda doi: (
            "2025-JACS-Machine-Lea-" + doi.split("/", 1)[1] + ".pdf", None, "", "")
        try:
            res = download_doi(argparse.Namespace(skip_existing=True),
                               "10.1021/jacs.4c17739", path_dir, "[1/1]")
        finally:
            globals()["get_output_name"] = original_output
        assert res["status"] == "skipped"

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
    assert not SRETRIABLE & {"unsupported", "skipped", "downloaded", "captcha"}

    # the report keeps input order and one entry per DOI, however often retried
    with tempfile.TemporaryDirectory() as tmp:
        path_report = Path(tmp) / "r.json"
        write_report(path_report, ["a", "b"], {"b": {"doi": "b"}, "a": {"doi": "a"}})
        assert [r["doi"] for r in json.loads(path_report.read_text())] == ["a", "b"]
    print("✅ selftest ok")


def main():
    global DATA_DIR, PROFILE_DIR, DOWNLOAD_DIR

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dois", nargs="?", help="DOI list file")
    ap.add_argument("-output", default=".")
    ap.add_argument("-preset", choices=sorted(PRESETS),
                    help="agent: no in-script retry, no captcha prompt, because "
                         "the agent reruns on failure. human: 2 retries, 120s "
                         "captcha wait. An explicit flag overrides the preset.")
    ap.add_argument("-timeout", type=int, default=None,
                    help="seconds per stage per DOI (default 300); a 20MB+ review "
                         "needs well over 180")
    ap.add_argument("-retries", type=int, default=None,
                    help="extra passes over the DOIs that failed (default 0)")
    ap.add_argument("-human_wait", type=int, default=None,
                    help="extra seconds granted after surfacing the tab on a captcha")
    ap.add_argument("-cdp", default="http://127.0.0.1:9333",
                    help="CDP endpoint of the automation Edge")
    ap.add_argument("-data_dir", default=str(DATA_DIR),
                    help="local state root; holds profile/ and download/ "
                         f"(default {DATA_DIR})")
    ap.add_argument("-skip_existing", action="store_true", default=None)
    ap.add_argument("-report", default="")
    ap.add_argument("-selftest", action="store_true")
    args = apply_preset(ap.parse_args())
    if args.selftest:
        return selftest()

    ldoi = parse_dois(Path(args.dois))
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    check_endpoint(args.cdp)

    # Edge decides where downloads land, so take the folder from its own
    # profile rather than assuming. Bound once here, before any worker reads it.
    DATA_DIR = Path(args.data_dir)
    PROFILE_DIR = DATA_DIR / "profile"
    DOWNLOAD_DIR = get_download_dir(DATA_DIR)
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
