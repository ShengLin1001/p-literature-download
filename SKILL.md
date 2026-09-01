---
name: p-literature-download
description: "按 DOI 列表从出版商官网批量下载学术正文 PDF，驱动一个已登录机构账号的专用 Microsoft Edge。不要因为对话里出现了 DOI、论文、PDF、下载等字样就自动触发；也绝不用 API、聚合站、仓储、预印本、Sci-Hub 或 LibGen 替代官网正文。"
---

# 出版商官网 PDF 批量下载

从 DOI 进入出版商官网，过 Cloudflare 与机构登录，取回期刊正文 PDF。

## 触发条件

**只在用户显式点名时执行**，例如 `$p-literature-download`、"用 p-literature-download 下这批 DOI"。

用户只是提到某篇文献、贴了个 DOI、问某篇论文讲什么，都**不要**启动本流程——
它会打开浏览器、发真实网络请求、动用机构账号会话，误触发的代价由用户承担。
不确定时先问一句，不要先跑。

## 边界

- 只从出版商官网取正文。不用 Elsevier API、Unpaywall、OpenAlex、CORE、DOAJ、Sci-Hub、LibGen，也不用预印本替代。
- 补充材料、预印本、SnapShot、采访、旧缓存都不算下载成功。
- 只处理 `scripts/literature_download.py` 的 `JOURNAL_ABBREVIATIONS` 中有缩写的期刊；无匹配项报告并跳过，不下载。
- 不读取、复制或转发用户的机构密码、Cookie 或浏览器 profile。**脚本不接触任何凭据**，登录态来自用户自己在专用 profile 里登录一次留下的 cookie。

## 依赖

Python 3.11+、本机已装 Microsoft Edge，加三个 pip 包：

```bash
python -m pip install playwright websocket-client pypdf
```

不需要 `playwright install`：脚本用 `connect_over_cdp` 驱动本机已装的 Edge，不下载浏览器二进制。
除此之外不依赖任何第三方包，`scripts/` 下的模块都是纯标准库，直接可跑。

## 一、一次性准备

### 1. 启动专用自动化 Edge

```powershell
powershell -NoProfile -File <skill目录>\scripts\start_edge.ps1
```

会用独立 profile `%USERPROFILE%\edge-automation` 启动 Edge，带三个必需参数：

| 参数 | 为什么必需 |
|---|---|
| `--remote-debugging-port=9333` | 脚本的唯一入口 |
| `--user-data-dir=%USERPROFILE%\edge-automation` | 与日常浏览器隔离，登录态持久 |
| `--no-proxy-server` | **载荷性参数**。走系统代理时 Cloudflare 会因出口 IP 判定，把出版商挑战永久挂在 "Request Verification: In Progress"；直连后同一 URL 立刻成功 |

不要用日常 Edge 通过 `edge://inspect` 临时开的调试端口：它的 `/json/*` 全部 404，且第一个客户端断开后就不再完成 WebSocket 握手。

### 2. 在弹出的窗口里手动登录一次机构账号

登录 WebVPN / CARSI / 统一身份认证。cookie 落在该 profile，之后每次跑脚本自动复用。

**验证登录成功**：随便打开一篇订阅文献，页面上应出现「Access provided by / Brought to you by 你的学校」。

### 3. 换一个学校

改 `scripts/edge_download.py` 顶部的 `INSTITUTION`（默认 `"Zhejiang University"`），
它用于出版商「Access through your institution」下拉框里的机构名匹配。

## 二、跑下载

DOI 文件每行一个 DOI，可在空白后附备注；空行和 `#` 开头的行忽略。

**agent 跑批一律加 `--preset agent`**，它把该关的都关了：

```bash
python <skill目录>/scripts/edge_download.py <DOI列表> -o pdfs --preset agent
```

先用自带的开放获取样例确认环境正常（六篇、六家出版社，不需要机构订阅，应当 6/6）：

```bash
python <skill目录>/scripts/edge_download.py <skill目录>/examples/dois-sample.txt -o pdfs --preset agent
```

### preset

| | `--preset agent` | `--preset human` |
|---|---|---|
| `--retries` | **0** —— agent 看到失败自己重跑，脚本再轮询就是双重重试 | **2** —— 人跑没有外层循环，得自己兜 |
| `--human-wait` | **0** —— agent 过不了图形验证码，弹窗口没意义 | **120** —— 人在旁边，能点 |
| `--skip-existing` | 开 | 开 |
| `--report` | 自动写到 `<输出目录>/report.json` | 同左 |
| `--timeout` | 300 | 300 |

显式写在命令行上的开关**永远压过 preset**，例如 `--preset human --retries 0`。

### 全部开关

| 开关 | 含义 |
|---|---|
| `-o/--output` | PDF 输出目录 |
| `--preset` | `agent` / `human`，见上表 |
| `--retries N` | 第一遍跑完后，把失败的再走 N 轮（默认 0）。轮次之间退避 45s |
| `--timeout` | 每篇每阶段秒数上限（默认 300）。20 MB 以上的综述在 180s 下会失败 |
| `--skip-existing` | 已有同名文件就跳过，用于补跑 |
| `--report` | 每篇写一次 JSON，长跑过程中可随时查看 |
| `--cdp` | CDP 端点（默认 `http://127.0.0.1:9333`） |
| `--human-wait N` | **只**在遇到 hCaptcha / reCAPTCHA 图形验证时把标签页弹到前台等 N 秒。Cloudflare 一律由脚本自己拟人化点击通过，不打扰用户 |
| `--profile-dir` | 从哪个 Edge profile 读下载目录（默认 `~/edge-automation`） |
| `--download-dir` | 直接指定要监视的浏览器下载目录，覆盖上面读出来的值 |
| `--selftest` | 只跑离线自检，不联网、不下载 |

### 重试的口径

只有 `failed` / `no_pdf_link` / `fetch_failed` / `error` 会重试。
`unsupported`（不是 journal-article、期刊没缩写）和 `skipped`（已落盘）是确定性结论，
重试只是再问 Crossref 一遍同样的问题，不会有不同答案。

报告始终按输入顺序、每个 DOI 一条，重试**就地覆盖**而不是追加——否则同一个 DOI
出现两条，下游所有计数都会串。重试过的条目带 `attempts` 字段，末尾也会汇总
「几篇走了重试、其中几篇重试后成功」。

脚本启动时先检查 Edge 是否可连；连不上直接报错退出，不会白跑整个列表。

跑批时窗口会被最小化，且每个标签页都以后台方式创建，不会反复弹到桌面上挡住你手头的事。
只有 `--human-wait` 遇到图形验证码时才会把窗口恢复出来让你操作。

**失败重跑**：`--preset agent` 下脚本只跑一遍。agent 看到失败自己重跑即可
（`--skip-existing` 已经开着，成功的不会重下）；偶发失败多半是 Cloudflare 抖动或超时。

### 人工接管（常开，不需要任何开关）

你想接管就直接把 Edge 窗口拉出来自己操作，脚本不会把它压回去，也从不阻塞等你。
resolve 循环每几秒重读一次所有标签页，所以：

- 你手动过掉 Cloudflare / 验证码 / 机构登录 —— 下一轮轮询自动接着往下走；
- 你手动打开 PDF（本标签页或新开标签页都行）—— 直接被捕捉为该篇正文，记为下载成功。

判据是 `document.contentType == "application/pdf"`，不是 URL 后缀：PNAS 的
`/doi/pdf/`、IEEE 的 `getPDF.jsp`、Annual Reviews 的 `?mimetype=application/pdf`
都没有 `.pdf` 后缀，按后缀判会全部漏掉。

还有第三条：你点的按钮如果是**直接触发下载**（PDF 从不显示在标签页里），
脚本每篇开始时给下载目录拍一张快照，之后每轮轮询比对，新出现的完整 PDF 同样算捕捉到。
所以三种接管动作都认：手动开 PDF、手动过验证后交回脚本、手动点下载。

监视的是哪个目录？**以 Edge profile 里写的为准，不是脚本里的常量。**
`start_edge.ps1` 把下载目录写进 `<profile>/Default/Preferences`（默认
`~/.pj/p-literature-download`），`edge_download.py` 启动时再从同一处读回来并打印出来。
落地是 Edge 干的，所以只能问 Edge；脚本这边写死一个常量，别人一改 `-DownloadDir`
就对不上，而对不上的表现是第 4 级取件和手动下载捕捉**静默失效**，看起来像出版商的问题。

> ⚠️ **跑批期间不要在这个自动化 Edge 窗口里打开与本次任务无关的 PDF。**
> 接管捕捉会扫描所有标签页，一篇处理途中出现的任何 PDF 都可能被当成该篇正文抓走，
> 结果是文件名对、内容错。临时看文献请用你自己的日常 Edge，两个 profile 本来就是隔离的。
> 每篇开始前脚本会关掉遗留的 PDF 标签页（Nature / IEEE 在新标签页开 PDF，不清理会串篇），
> 但这只防得住**上一篇**的残留，防不住**本篇进行中**你新开的。

### 内容核对（只警告，不拦截）

每篇落盘后抽取前 3 页文本，核对是否含本篇 DOI 或标题、是否像补充材料。
不通过**只打印警告并保留文件**，末尾汇总，绝不删除或拒收。

因为硬判据一定会误杀：1971 年的 PRB 文章 PDF 里根本没印 DOI，而且是 OCR 扫描件——
`PHYSICAL REVIEW` 抽出来是 `PH YSICA L BEVI EUV`，首页开头还是上一篇文章的参考文献尾巴。
实测该文靠标题匹配通过，但换一篇 OCR 毁掉标题的就会误报。所以它是提示，不是判决。

## 三、文件命名

命名规则和期刊缩写表在 `scripts/literature_download.py`，
格式为 `年份-期刊缩写-标题前十个有效字符.pdf`：

```text
2013-NATURE-Nanometre-s.pdf
2021-SENSORS-Matheuristi.pdf
```

脚本**在开浏览器之前**先查 Crossref 定名。定不了名的记录直接报告并跳过，不下载：

- `not a journal article` —— 不是 journal-article 类型（预印本、会议录等）
- `excluded article type` —— SnapShot 之类的非正文条目
- `journal abbreviation missing` —— 期刊不在缩写表里，需要先往 `JOURNAL_ABBREVIATIONS` 里加

## 四、验收

```bash
python <skill目录>/scripts/verify_pdf.py <目录> --batch
```

单个 DOI 记为 **pass** 当且仅当全部满足：

- 本轮真实落盘；
- `%PDF-` 开头、`%%EOF` 结尾、页数 > 0；
- 提取文本中的 DOI 或标题与 Crossref 元数据匹配；
- 首页不是补充材料；
- 文件名符合上面的命名规则。

进入登录页、点击成功、`--selftest` 通过，都**不算** pass。

## 五、原理：为什么是这个结构

每篇 DOI 分两步。第一步 **resolve**：Playwright 通过 CDP 驱动 Edge，打开 `doi.org`，
拟人化点击过 Cloudflare Turnstile，点掉 cookie 同意弹窗，必要时走机构登录，
读出 PDF 候选链接。第二步 **fetch**：没有单一方法能覆盖所有出版商，四级逐次升级，先命中先返回。

| 级别 | 方法 | 谁需要它 |
|---|---|---|
| 1 | 页内 `fetch()` + 分块 base64 回传 | 绝大多数（Nature、Springer、PLOS、APS、Science、PNAS、Wiley、ACS、IOP、Frontiers、Annual Reviews、ACM） |
| 2 | 导航 + Playwright `expect_download` | MDPI —— Akamai 拦跨域 fetch，但放行真实导航 |
| 3 | 导航到 PDF 后，在该页 `fetch(location.href)` | AIP、RSC、OUP（Silverchair）—— 发 inline PDF 不触发下载事件，但标签页此时已与 PDF 同源 |
| 4 | 断开 Playwright，裸 CDP 开标签页下载 | Elsevier —— attach 的 DevTools 会话本身会被 Cloudflare 检测 |

候选链接必须过滤两类噪声，否则会下错文件（都实际发生过）：
补充材料（ACS `article-supplement/_si_`、Springer `/esm/`、OUP `_supplemental_file`），
以及参考文献里别人的 PDF（Elsevier 一篇抓到 5 篇引文，AIP 抓到一份产品说明书）。

## 六、常见故障

| 现象 | 原因与处理 |
|---|---|
| 连不上 Edge | 没跑 `start_edge.ps1`，或 Edge 被关了。**永远不要**对 CDP 连接调 `browser.close()`，那会拆掉 DevTools 服务端 |
| 挑战永远停在 "Request Verification: In Progress" | 开了系统代理。`start_edge.ps1` 已带 `--no-proxy-server`，确认没被绕过 |
| 全部 `no_pdf_link (state paywall)` | 机构登录掉了，去自动化 Edge 里重新登录一次 |
| `state captcha` | hCaptcha 图形验证，脚本过不了。加 `--human-wait 120` 由用户点，或直接拉出窗口自己过——接管常开 |
| 我手动开了 PDF 但没被认到 | 确认开在同一个自动化 Edge 里；补充材料链接会被故意忽略 |
| 末尾报「内容核对未通过」 | 只是提示，文件已保留。老文献扫描件、OCR 失真的标题都会触发，自己打开确认即可 |
| 跑批时 Edge 一直弹到桌面上 | 该版本已修复：标签页用 `Target.createTarget` 的 `background` 标志创建，窗口每轮最小化一次。注意 Windows 会把负窗口坐标夹回 (0,0)，离屏摆放没用 |
| PDF 在内置阅读器里打开、拿不到文件 | 正常，级别 1 和 3 不依赖下载。**不要**去改 `always_open_pdf_externally`，它是受保护偏好，改了会被启动时还原 |
| 日志出现 `↩️ 偏离到 …，退回 DOI 重来` | 正常自愈。页面跑到了非本文页（APS 的 `/prb/accepted`、SSO wayfinder 等），脚本退回 DOI 重来，最多两次 |
| 大文件（20 MB 以上）报 `fetch_failed` | 超时不够。`--timeout 240` 起步，RSC 综述这类要走第 3 级取件 |
| 偶发一两篇失败 | Cloudflare 抖动或超时。agent 直接重跑（`--preset agent` 已带 `--skip-existing`）；人跑用 `--preset human`，自带 2 轮重试 |
| Elsevier 一直 `fetch_failed`，或手动点的下载没被认到 | 多半是下载目录对不上。看启动时打印的「浏览器下载目录」，跟 Edge 里 `edge://settings/downloads` 显示的是不是同一个；不是就重跑一次 `start_edge.ps1` |
| 某出版商改版后取不到 | 先跑诊断：打开文章页看 `get_page_state` 和 `filter_pdf_candidates` 的输出，再决定是加 host 规则还是加取件级别 |

## 七、报告口径

区分三种结论，不要混为一谈：

- `自动成功`：本轮无人操作完成；
- `初始化后自动成功`：曾由用户建立机构会话，随后无人操作回归成功；
- `失败`：验证码未放行、会话过期或机构无权限。

不得把「当前测试集成功」表述为所有出版商、所有时间、全新 profile 下的 100% 保证。
结果依赖该 profile 已建立的机构会话，且出版商随时可能改版。

## 八、代码边界

`scripts/` 下四个 Python 文件，全部自包含，无需安装本仓库：

| 文件 | 职责 |
|---|---|
| `edge_download.py` | 浏览器驱动与编排：Turnstile 拟人化点击、四级取件、人工接管、CLI |
| `verify_pdf.py` | 验收：头尾标、页数、补充材料判定、DOI / 标题比对 |
| `literature_download.py` | DOI 解析、Crossref 元数据、期刊缩写表、文件命名、PDF 完整性 |
| `publisher_pdf.py` | 出版商站点知识：页面状态分类、PDF URL host 规则、候选过滤、注入的 JS。与浏览器无关 |

改完任意一个，跑离线自检：

```bash
python <skill目录>/scripts/edge_download.py --selftest
python <skill目录>/scripts/verify_pdf.py --selftest
```

自检不联网、不开浏览器，覆盖页面状态分类、host 规则、候选过滤、DOI 解析和命名。
