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
- 不用预印本替代正式期刊版本；但 DOI 本身就指向 arXiv 等预印本时照常下载，那就是用户要的那一篇。
- 补充材料、SnapShot、采访、旧缓存都不算下载成功。
- **不限期刊**。缩写表只是给常用刊固定叫法，表外的期刊照常下载，缩写从元数据里自动生成。
- 不读取、复制或转发 Cookie / profile。WebVPN 账号和密码保存在各自 profile 下、由 Windows DPAPI 加密；不得写源码、命令行、日志或报告。

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

本机状态全部收在一个 `-data_dir` 下（默认 `%USERPROFILE%\.pj\p-literature-download`）：

```text
~/.pj/p-literature-download/     # -data_dir，一个参数管住全部本机状态
├── profile/     # Edge 的 --user-data-dir，你的机构登录态在这里
└── download/    # 浏览器下载落地处
```

Edge 带三个必需参数启动：

| 参数 | 为什么必需 |
|---|---|
| `--remote-debugging-port=9333` | 脚本的唯一入口 |
| `--user-data-dir=…\.pj\p-literature-download\profile` | 与日常浏览器隔离，登录态持久 |
| `--no-proxy-server` | **载荷性参数**。走系统代理时 Cloudflare 会因出口 IP 判定，把出版商挑战永久挂在 "Request Verification: In Progress"；直连后同一 URL 立刻成功 |

不要用日常 Edge 通过 `edge://inspect` 临时开的调试端口：它的 `/json/*` 全部 404，且第一个客户端断开后就不再完成 WebSocket 握手。

### 2. 准备机构登录

启动器会确保 ZJU WebVPN 首页存在并复用 profile 登录态。首次启动用系统凭据窗口把该使用者
的账号和密码以 DPAPI 密文保存在 profile；会话失效时才临时解密并填入官方登录页。
换凭据用 `start_edge.ps1 -initialize_credentials`。

WebVPN 会话过期是常态，脚本会自动填表登录，**不要找用户代登**。登录后若弹出
「该账号已经登录，继续登录将踢掉其他已登录账号」，脚本自动点「继续」（会顶掉该账号在别处的
WebVPN 会话）；只有出现验证码或短信/TOTP 二次验证才需要人，且仅在 `-preset human` 下等待。

启动器用 `Start-Process` 脱离调用方，CDP 就绪即返回。不要改回 `& msedge`：那样 Edge 是调用
shell 的子进程，shell 调用一结束 Edge 随之退出，批量下载只成功第一篇，后面全是
`WinError 10061` connection refused。

**验证登录成功**：直连订阅文献应出现「Access provided by / Brought to you by 你的学校」；
WebVPN 首页应显示“输入网址直接访问内网或图书馆资源”。

### 3. 换一个学校

改 `scripts/edge_download.py` 顶部的 `INSTITUTION`（默认 `"Zhejiang University"`），
它用于出版商「Access through your institution」下拉框里的机构名匹配。

## 二、跑下载

DOI 文件每行一个 DOI，可在空白后附备注；空行和 `#` 开头的行忽略。

**agent 跑批一律加 `-preset agent`**，它把该关的都关了：

```bash
python <skill目录>/scripts/edge_download.py <DOI列表> -output pdfs -preset agent
```

先用自带的开放获取样例确认环境正常（六篇、六家出版社，不需要机构订阅，应当 6/6）：

```bash
python <skill目录>/scripts/edge_download.py <skill目录>/examples/dois-sample.txt -output pdfs -preset agent
```

### preset

| | `-preset agent` | `-preset human` |
|---|---|---|
| `-retries` | **0** —— agent 看到失败自己重跑，脚本再轮询就是双重重试 | **2** —— 人跑没有外层循环，得自己兜 |
| `-human_wait` | **0** —— agent 过不了图形验证码，弹窗口没意义 | **120** —— 人在旁边，能点 |
| `-skip_existing` | 开 | 开 |
| `-report` | 自动写到 `<输出目录>/report.json` | 同左 |
| `-timeout` | 300 | 300 |

显式写在命令行上的开关**永远压过 preset**，例如 `-preset human -retries 0`。

### 全部开关

| 开关 | 含义 |
|---|---|
| `-output` | PDF 输出目录 |
| `-preset` | `agent` / `human`，见上表 |
| `-retries N` | 第一遍跑完后，把失败的再走 N 轮（默认 0）。轮次之间退避 45s |
| `-timeout` | 每篇每阶段秒数上限（默认 300）。20 MB 以上的综述在 180s 下会失败 |
| `-skip_existing` | 已有同名文件就跳过，用于补跑 |
| `-report` | 每篇写一次 JSON，长跑过程中可随时查看 |
| `-cdp` | CDP 端点（默认 `http://127.0.0.1:9333`） |
| `-human_wait N` | **只**在遇到 hCaptcha / reCAPTCHA 图形验证时把标签页弹到前台等 N 秒。Cloudflare 一律由脚本自己拟人化点击通过，不打扰用户 |
| `-data_dir` | 本机状态根目录（默认 `~/.pj/p-literature-download`），下辖 `profile/` 与 `download/` |
| `-selftest` | 只跑离线自检，不联网、不下载 |

### 重试的口径

只有 `failed` / `no_pdf_link` / `fetch_failed` / `error` 会重试。
`unsupported`（补充材料、SnapShot、元数据里没有年份或标题）和 `skipped`（已落盘）
是确定性结论，重试只是再问一遍同样的问题，不会有不同答案。
`captcha` 也不重试，但理由不同：图形验证要人过，脚本重跑只会把 bot 评分越喂越高。

报告始终按输入顺序、每个 DOI 一条，重试**就地覆盖**而不是追加——否则同一个 DOI
出现两条，下游所有计数都会串。重试过的条目带 `attempts` 字段，末尾也会汇总
「几篇走了重试、其中几篇重试后成功」。

脚本启动时先检查 Edge 是否可连；连不上直接报错退出，不会白跑整个列表。

跑批时窗口会被最小化，且每个标签页都以后台方式创建，不会反复弹到桌面上挡住你手头的事。
只有 `-human_wait` 遇到图形验证码时才会把窗口恢复出来让你操作。

**失败重跑**：`-preset agent` 下脚本只跑一遍。agent 看到失败自己重跑即可
（`-skip_existing` 已经开着，成功的不会重下）；偶发失败多半是 Cloudflare 抖动或超时。

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

接管来源不天然属于当前 DOI。脚本会先从 PDF 前 3 页核对当前 DOI 或标题；不匹配时忽略，
且不删除下载目录中的源文件，避免把上一篇或无关 PDF 改名成当前文献。

监视的是哪个目录？**以 Edge profile 里写的为准，不是脚本里的常量。**
`start_edge.ps1` 把下载目录写进 `<data-dir>/profile/Default/Preferences`（默认
`~/.pj/p-literature-download/download`），`edge_download.py` 启动时再从同一处读回来并打印出来。
落地是 Edge 干的，所以只能问 Edge；脚本这边写死一个常量，别人一改 `-data_dir`
就对不上，而对不上的表现是第 4 级取件和手动下载捕捉**静默失效**，看起来像出版商的问题。

### 内容核对

普通出版社候选链接下载的 PDF 落盘后也会核对 DOI / 标题与补充材料，但不匹配只警告：
老文献可能没印 DOI，扫描件的 OCR 也可能毁掉标题，硬拦截会误杀。只有来源不确定的人工接管
标签页和下载目录新文件必须核对通过才接收。

## 三、文件命名

命名规则和期刊缩写表在 `scripts/literature_download.py`，
格式为 `年份-期刊缩写-标题前十个有效字符-DOI后缀.pdf`：

```text
2025-JACS-Machine-Lea-jacs.4c17739.pdf
2023-SCRIPTA-MATERIALIA-Molecular-d-j.scriptamat.2023.115309.pdf
```

DOI 后缀 = DOI 去掉 `10.xxxx/` 前缀、转小写、`/` 等非法字符换成 `_`。它是必需的：
标题前十个字符经常撞（`Machine Lea…`），而老文献扫描件印不出 DOI，没法靠读正文区分。
带上 DOI 后一个 DOI 恒对应一个文件名，`-skip_existing` 只看路径即可，不读 PDF。

期刊缩写按以下顺序取第一个命中的，**不会**因为期刊不在表里就拒绝下载：

1. `JOURNAL_ABBREVIATIONS` 里的固定叫法（`Nature` → `NATURE`，`Physical Review B` → `PRB`）。只放要钉死的约定叫法，**不要**为了覆盖新期刊往里扩写；
2. 本地缓存 `<data_dir>/journal_abbreviations.json`（ISSN → 缩写）；
3. NLM Catalog 按 ISSN 在线查 `MedlineTA`（ISO 4 去句点，`Int J Plast` → `INT-J-PLAST`）。首批 217 个材料/物理 DOI 的期刊全部命中；
4. Crossref 的 `short-container-title`；
5. 期刊全名（去掉 of/and/the 等虚词）；
6. 出版商名（arXiv 之类没有期刊名的 → `ARXIV`）。

第 3–6 步得到的缩写**首次就写入缓存**，之后永远复用：文件名是判断「已下载」的唯一依据，同一本刊必须
始终同一个缩写。所以 NLM 连不上时该 DOI 记 `error`（可重试），**不**退到 Crossref 凑一个不同的名字；
只有 NLM 明确查无此 ISSN 才往下退。想改某本刊的叫法：加一条 `JOURNAL_ABBREVIATIONS`
（或改缓存里那一项），注意已下载文件不会随之改名。

元数据先问 Crossref，Crossref 没有的 DOI（arXiv 等 DataCite 注册的）退到 doi.org 内容协商。

脚本**在开浏览器之前**先查元数据定名。只有这几类会报告并跳过，不下载：

- `metadata unavailable` —— Crossref 和 doi.org 都查不到，多半 DOI 本身有问题
- `supplementary component` —— 补充材料条目
- `excluded article type` —— SnapShot 之类的非正文条目
- `publication year missing` / `title missing` —— 元数据缺字段，凑不出文件名

## 四、验收

```bash
python <skill目录>/scripts/verify_pdf.py <目录> -batch
```

单个 DOI 记为 **pass** 当且仅当全部满足：

- 本轮真实落盘；
- `%PDF-` 开头、`%%EOF` 结尾、页数 > 0；
- 提取文本中的 DOI 或标题与 Crossref 元数据匹配；
- 首页不是补充材料；
- 文件名符合上面的命名规则。

进入登录页、点击成功、`-selftest` 通过，都**不算** pass。

## 五、原理：为什么是这个结构

每篇先走原直连流程：Playwright 从 `doi.org` 进入出版社，Elsevier 跳过 linkinghub，
过 Turnstile、cookie 与机构登录并读出候选；随后四级取件，先命中先返回。只有整篇直连最终失败，
才把官方文章 URL 填入 ZJU WebVPN 首页搜索框，再从代理后的官方页面重复取件。不要让 WebVPN
替代主路径：它能补 AIP / PNAS 的机构权限，但已知与 APS、Cell 等站点不兼容。

| 级别 | 方法 | 谁需要它 |
|---|---|---|
| 1 | 页内 `fetch()` + 分块 base64 回传 | 绝大多数（Nature、Springer、PLOS、APS、Science、PNAS、Wiley、ACS、IOP、Frontiers、Annual Reviews、ACM） |
| 2 | 导航 + Playwright `expect_download` | MDPI —— Akamai 拦跨域 fetch，但放行真实导航 |
| 3 | 导航到 PDF 后，在该页 `fetch(location.href)` | AIP、RSC、OUP（Silverchair）—— 发 inline PDF 不触发下载事件，但标签页此时已与 PDF 同源 |
| 4 | 断开 Playwright，裸 CDP 开标签页下载 | 前三级都取不到时的兜底 |

Elsevier 单独说一句，因为它看起来像 attach 被检测，其实不是。它的 PDF 链接会在
**新标签页**里打开 `pdf.sciencedirectassets.com` 的 Cloudflare 挑战，停在
「Request Verification: In Progress」不动——因为驱动的那个标签页读出来仍然是文章页，
主循环的 cloudflare 分支根本不触发。实测：前台后台、带不带 Referer、真实点击还是裸导航，
一样卡死；对那个标签页拟人化点一次 Turnstile 就过。这就是 `clear_sibling_challenges` 的由来。

候选链接必须过滤两类噪声，否则会下错文件（都实际发生过）：
补充材料（ACS `article-supplement/_si_`、Springer `/esm/`、OUP `_supplemental_file`），
以及参考文献里别人的 PDF（Elsevier 一篇抓到 5 篇引文，AIP 抓到一份产品说明书）。

## 六、常见故障

| 现象 | 原因与处理 |
|---|---|
| 连不上 Edge | 没跑 `start_edge.ps1`，或 Edge 被关了。**永远不要**对 CDP 连接调 `browser.close()`，那会拆掉 DevTools 服务端 |
| 挑战永远停在 "Request Verification: In Progress" | 开了系统代理。`start_edge.ps1` 已带 `--no-proxy-server`，确认没被绕过 |
| 全部 `no_pdf_link (state paywall)` | 直连机构登录掉了；脚本会尝试 WebVPN，仍失败时检查 WebVPN 登录态，必要时用 `start_edge.ps1 -initialize_credentials` 更新凭据 |
| `state captcha` / 状态 `captcha` | 图形验证，脚本过不了。加 `-human_wait 120` 由用户点，或直接拉出窗口自己过——接管常开。IOP 走的是 Radware Bot Manager，勾选框是 hCaptcha，**勾完还要点图**，所以脚本不去点它：点了只是喂高 bot 评分 |
| 我手动开了 PDF 但没被认到 | 确认开在同一个自动化 Edge 里；补充材料链接会被故意忽略 |
| 末尾报「内容核对未通过」 | 只是提示，文件已保留。老文献扫描件、OCR 失真的标题都会触发，自己打开确认即可 |
| 跑批时 Edge 一直弹到桌面上 | 该版本已修复：标签页用 `Target.createTarget` 的 `background` 标志创建，窗口每轮最小化一次。注意 Windows 会把负窗口坐标夹回 (0,0)，离屏摆放没用 |
| PDF 在内置阅读器里打开、拿不到文件 | 正常，级别 1 和 3 不依赖下载。**不要**去改 `always_open_pdf_externally`，它是受保护偏好，改了会被启动时还原 |
| 日志出现 `↩️ 偏离到 …，退回 DOI 重来` | 正常自愈。页面跑到了非本文页（APS 的 `/prb/accepted`、SSO wayfinder 等），脚本退回 DOI 重来，最多两次 |
| 大文件（20 MB 以上）报 `fetch_failed` | 超时不够。`-timeout 240` 起步，RSC 综述这类要走第 3 级取件 |
| 偶发一两篇失败 | Cloudflare 抖动或超时。agent 直接重跑（`-preset agent` 已带 `-skip_existing`）；人跑用 `-preset human`，自带 2 轮重试 |
| Elsevier 卡在 linkinghub 打不开文章页 | 入口 URL 改写没生效，见 `publisher_pdf.py` 的 `LHOST_ENTRY_RULES` |
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
python <skill目录>/scripts/edge_download.py -selftest
python <skill目录>/scripts/verify_pdf.py -selftest
```

自检不联网、不开浏览器，覆盖页面状态分类、host 规则、候选过滤、DOI 解析和命名。
