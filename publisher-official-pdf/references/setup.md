# 安装与首次初始化

已在 Windows 10、Microsoft Edge 152、Python 3.14 上验证。

## 1. 安装依赖

```powershell
python -m pip install playwright websocket-client requests pypdf
python -m pip install -e "F:\BaiduSyncdisk\version20240608\main_code_space\pjvasp_package" --no-deps
```

`edge_download.py` 只用 Playwright 的 `connect_over_cdp` 去驱动**已经装好的 Edge**，
不需要 `playwright install` 下载浏览器二进制。

`mymetal.academic.search` 提供两块共享逻辑，脚本直接 import：

- `literature_download` —— DOI 解析、Crossref 元数据、期刊缩写表、文件命名、PDF 完整性；
- `publisher_pdf` —— 出版商站点知识：页面状态分类、PDF URL host 规则、候选过滤、注入的 JS。

改完这两个模块后，在 `pjvasp_package` 根目录跑 `python tests/test_literature.py` 回归。

## 2. 启动专用自动化 Edge

```powershell
powershell -NoProfile -File <skill目录>\scripts\start_edge.ps1
```

用独立 profile `%USERPROFILE%\edge-automation` 启动，带 `--remote-debugging-port=9333`
和 `--no-proxy-server`。换端口用 `-Port`，换 profile 用 `-ProfileDir`。

不要用日常 Edge 通过 `edge://inspect` 临时开的调试端口：它的 `/json/*` 全部 404，
且第一个客户端断开后就不再完成 WebSocket 握手。

## 3. 机构访问与持久 profile

- 在弹出的窗口里**手动登录一次**学校统一身份认证 / WebVPN / CARSI；
- cookie 落在该 profile，之后每次跑脚本自动复用，**脚本不接触任何凭据**；
- 验证：随便打开一篇订阅文献，页面上应出现「Access provided by 你的学校」；
- 不要把该 profile 复制给别人，它含 Cookie 与机构会话。每位使用者建立自己的 profile；
- 换学校要改 `scripts/edge_download.py` 顶部的 `INSTITUTION`；
- 遇到 hCaptcha 图片题时脚本过不了，由用户本人处理（`--human-wait N` 会把标签页弹到前台）。
  Cloudflare Turnstile 一律由脚本拟人化点击通过，不打扰用户。
- **跑批期间不要在这个自动化 Edge 窗口里打开无关 PDF**，会被当成当前这篇抓走。
  临时看文献用自己的日常 Edge。详见 SKILL.md 的「人工接管」小节。

## 4. 安装 skill

把整个 `publisher-official-pdf` 目录复制到 agent 的 skill 根目录：

```powershell
Copy-Item -Recurse .\publisher-official-pdf "$env:USERPROFILE\.claude\skills\publisher-official-pdf"
```

Codex 用 `$env:CODEX_HOME\skills`。重启会话后确认能被发现。

## 5. 第一次运行

`dois.txt` 每行一个 DOI，可在空白后附备注；空行和 `#` 开头的行忽略：

```text
10.1038/nature12373
10.1103/PhysRevB.88.064104
10.1016/j.commatsci.2018.12.013
```

先自检，确认能连上 Edge：

```powershell
python <skill目录>\scripts\edge_download.py --selftest
```

再跑下载与验收：

```powershell
python <skill目录>\scripts\edge_download.py .\dois.txt -o .\pdfs `
    --timeout 180 --skip-existing --report .\pdfs\report.json
python <skill目录>\scripts\verify_pdf.py .\pdfs --batch
```

元数据不是 journal-article、文章类型被排除（SnapShot 等）或期刊不在缩写表时，
脚本在开浏览器**之前**就报告并跳过，不下载。

## 6. 常见问题

| 现象 | 原因与处理 |
|---|---|
| 连不上 `127.0.0.1:9333` | 没跑 `start_edge.ps1`，或 Edge 被关了。代码里**永远不要**对 CDP 连接调 `browser.close()`，那会拆掉 DevTools 服务端 |
| 挑战永远停在 `Request Verification: In Progress` | 走了系统代理。Cloudflare 判的是出口 IP，`start_edge.ps1` 已带 `--no-proxy-server` |
| 全部 `no_pdf_link (state paywall)` | 机构会话过期，去自动化 Edge 里重新登录一次 |
| `state captcha` | hCaptcha 图片题，脚本过不了。加 `--human-wait 120` 由用户点，或跳过 |
| PDF 在内置阅读器里打开、拿不到文件 | 正常。**不要**改 `always_open_pdf_externally`，它是受保护偏好，会在启动时被还原；四级取件不依赖它 |
| 下载到 Supplementary Materials | 候选过滤器应拦掉。新出版商的补充材料命名不同时，往 `publisher_pdf.SUPPLEMENT_PATTERN` 补 |
| 下到了参考文献里别人的 PDF | 同上，检查 `filter_pdf_candidates`；候选必须含本文 DOI 后缀或页面 URL 里的 PII，都不匹配才回退到同域 |
| 期刊不在缩写表 | 在 `mymetal/academic/search/literature_download.py` 的 `JOURNAL_ABBREVIATIONS` 补充确认后的通用缩写 |
| 某出版商改版后取不到 | 先看 `get_page_state` 和 `filter_pdf_candidates` 的输出，再决定加 host 规则还是加取件级别 |

## 7. CloakBrowser 兜底

`scripts/cb_download.py` 保留作兜底，非主路径。用完必须彻底杀掉 chrome 根进程，
否则残留进程占住服务端座位（免费版单座位），下一次启动会被堵约 5 分钟。
