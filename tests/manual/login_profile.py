#!/usr/bin/env python
"""打开 official-browser-profile 持久化浏览器，让用户完成关键登录。

状态自动保存在 profile 里，供 browser-get 自动下载复用。
用法: python login_profile.py [起始URL]
"""
import sys
from pathlib import Path

from scansci_pdf.config import load_config
from scansci_pdf.sources.browser_direct import _browser_launch_kwargs

start_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.nature.com/articles/nature12373"

config = load_config()
profile_dir = Path(config.get("cache_dir", Path.home() / ".scansci-pdf/cache")) / "official-browser-profile"

from cloakbrowser import launch_persistent_context

context = launch_persistent_context(str(profile_dir), **_browser_launch_kwargs(config, headless=False))
page = context.pages[0] if context.pages else context.new_page()
try:
    page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
except Exception as exc:
    print("goto warning:", exc)

print()
print("浏览器已打开:", start_url)
print("请在浏览器里完成关键登录（CARSI/SSO 等，可自由导航任意站点）。")
print("完成后回到终端按 Enter，浏览器将优雅关闭并把登录状态存入 profile。")
try:
    input()
except EOFError:
    print("(收到 EOF，直接关闭)")
context.close()
print("登录状态已保存:", profile_dir)
