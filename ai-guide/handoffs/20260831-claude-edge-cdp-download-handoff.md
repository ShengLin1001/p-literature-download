# 官网文献 PDF 自动下载 · Edge CDP 路径交接

日期：2026-08-31 · 作者：claude · 状态：**单次全量回归完成，19/19 期刊正文通过验收，下载失败 0**

替代前序方案 `ai-guide/handoffs/20260830-hermes-pdf-download-execution-handoff.md` 中的
CloakBrowser 主路径与 `cdp_download.py`。

---

## 一、结论

下载主路径是**一个专用的、已登录机构账号的真实 Edge**，脚本
`publisher-official-pdf/scripts/edge_download.py` 通过 CDP 驱动它。

每篇 DOI 先 **resolve**（Playwright over CDP：打开 doi.org、拟人化点过 Cloudflare、
点掉 cookie 弹窗、必要时走机构登录、读出 PDF 候选链接），再 **fetch**。
取件不是单一方法，而是四级逐次升级，详见「二之二」。

---

## 二、三个实测出来的根因（都不是猜的）

### 2.1 系统代理会让 Cloudflare 永远不放行

浏览器走系统代理（`127.0.0.1:7897`）时，Elsevier 的
`pdf.sciencedirectassets.com` 停在 `Request Verification: In Progress`，等 100s 也不动。
加 `--no-proxy-server` 直连后，**同一个 URL、同一个 md5 token**，5 秒内下完 14.9 MB。

Cloudflare 判的是代理出口 IP，不是指纹。这条对 APS / Elsevier / MDPI 都成立。

### 2.2 Playwright attach 本身会被检测

Playwright 挂上任何 page 都会 `Runtime.enable`，严格的出版商 CF 配置以此识别 CDP 客户端，
把挑战永久挂在 "In Progress"。同一个 URL 用裸 CDP `Target.createTarget` 且全程不 attach，
立刻下载成功。所以取文件那一步必须先把 Playwright 完全断开
（`sync_playwright()` 上下文退出），再用 `RawCdp` 开标签页。

### 2.3 base64 分块拼接会损坏文件

之前把每个 4 MB 分块各自 base64 后**拼接编码串**再解码。每块自带 padding，
4194304 不是 3 的倍数，于是 5,699,993 B 的 PDF 落盘成 5,699,994 B，`%%EOF` 校验失败。
必须逐块解码再 `b"".join`。当前实现已改用浏览器下载，不再走这条路，但同类代码要注意。

### 2.4 日常 Edge 的调试端口不可用

`edge://inspect` 运行时启用的端口（本机 4894）`/json/*` 全部 404，
且**第一个客户端断开后就不再完成 WebSocket 握手**。不要依赖它。
另外 Playwright 对 CDP 连接调 `browser.close()` 会把 DevTools 服务端拆掉——代码里永远不要调。

### 2.5 Cloudflare Turnstile 要拟人化点击

指纹不够。定位用 `input[name='cf-turnstile-response']` 的**父元素** bounding box
（iframe 自身的 box 有偏移），点击要有贝塞尔式移动、瞄准停顿和 0.09–0.19s 的按压时长。
逻辑从 `cb_download.py` 移植，见 `click_turnstile_human`。

---

## 二之二、取件的四级策略（关键）

没有单一方法能覆盖所有出版商，按顺序试，先命中先返回：

| 级别 | 方法 | 谁需要它 | 为什么别人不行 |
|---|---|---|---|
| 1 | 页内 `fetch()` + 分块 base64 回传 | Nature、Springer、BMC、PLOS、APS、Science、PNAS、Wiley、ACS、IOP、Frontiers、Annual Reviews、ACM | 最快，不落盘，不依赖任何浏览器设置 |
| 2 | Playwright 导航 + `expect_download` | MDPI | 页内 fetch 被 Akamai 拦（`TypeError: Failed to fetch`），但真实导航正常 |
| 3 | 导航到 PDF 后，在该页 `fetch(location.href)` | AIP、RSC、OUP（Silverchair） | 服务端发 inline PDF，不触发下载事件；但标签页此时已在 PDF 同源，跨域限制消失 |
| 4 | 断开 Playwright，裸 CDP 开标签页下载 | Elsevier / ScienceDirect | attach 本身被 CF 检测，必须全程不 attach |

`always_open_pdf_externally` **不要指望**：它是 Edge 的受保护偏好，直接改 `Preferences` 会在启动时被还原。上面四级都不依赖它。

## 三、出版商 PDF 链接怎么找

优先级：**host 规则 > `<meta name="citation_pdf_url">` > 带标签的按钮 href > 通用 href 扫描**，
返回候选列表逐个试。

`citation_pdf_url` 是 Google Scholar 要求的标签，Nature / MDPI / PLOS / BMC / Springer /
Wiley / OUP / IOP / AIP / ACS / PNAS / Science / Annual Reviews 都发，一条规则顶掉大半张表。
只有三家需要 host 规则，且 APS 是因为它**发的那个链接本身是错的**：

| host | 规则 | 原因 |
|---|---|---|
| sciencedirect.com | `/pii/<PII>` → `/pii/<PII>/pdfft?isDTMRedir=true&download=true` | 不发 citation_pdf_url |
| journals.aps.org | `/<jrnl>/abstract/<doi>` → `/<jrnl>/pdf/<doi>` | 它发的 `link.aps.org/pdf/…` 只会跳回摘要页 |
| dl.acm.org | `/doi/<doi>` → `/doi/pdf/<doi>` | 不发 citation_pdf_url |
| onlinelibrary.wiley.com | `/doi/<doi>` → `/doi/pdfdirect/<doi>?download=true` | `/doi/pdf/` 是阅读器包装页 |
| pubs.acs.org | `/doi/<doi>` → `/doi/pdf/<doi>` | 不发 citation_pdf_url |
| annualreviews.org | `/content/journals/<doi>` → 加 `?crawler=true&mimetype=application/pdf` | DOM 里根本没有 PDF 链接 |
| ieeexplore（DOM 层） | `stamp/stamp.jsp` → `stampPDF/getPDF.jsp` | stamp.jsp 只是外壳，真文件在其 iframe 里 |

### 两个必须的候选过滤

1. **补充材料**：ACS 的 `article-supplement/…_si_001`、Springer 的 `/esm/`、OUP 的
   `…_supplemental_file.pdf`。不过滤会把补充材料当正文下载（实测发生过）。
2. **别人的文章**：文章页会链出所有参考文献的 PDF。Elsevier 一篇抓到 5 篇引文 PDF，
   AIP 抓到一份产品说明书。规则：候选必须包含本文 DOI 后缀或页面 URL 里的 PII；
   都不匹配时只回退到**同域名**候选，绝不跨域。

### Cookie 同意弹窗

AIP 和 IEEE 的文章页有 consent 遮罩，挡住链接和请求，需先点掉（`CONSENT_JS`）。

---

## 四、操作手册

### 一次性准备

```powershell
# 1. 启动专用自动化 Edge（独立 profile + 调试端口 + 直连）
powershell -NoProfile -File publisher-official-pdf\scripts\start_edge.ps1

# 2. 在弹出的窗口里手动登录一次统一身份认证 / WebVPN
#    cookie 落在 %USERPROFILE%\edge-automation，之后永久复用，脚本不接触任何凭据
```

`start_edge.ps1` 只固定下载目录（`%USERPROFILE%\edge-automation\downloads`）。
**不要试图关掉内置 PDF 阅读器**：`always_open_pdf_externally` 是受保护偏好，
改了会被启动时还原，四级取件策略也不依赖它。

### 跑下载

```bash
PY=/c/Users/louis/mysoft/env/pyenv/scansci-pdf/Scripts/python.exe
$PY publisher-official-pdf/scripts/edge_download.py dois.txt \
    -o tests/artifacts/<date>-edge --timeout 180 --skip-existing \
    --report tests/artifacts/<date>-edge/report.json
```

`--timeout` 默认 300s：RSC 那篇 21 MB 综述在 180s 下必失败。
`--report` 每篇写一次，长跑过程中可随时查看。`--human-wait N` 只在遇到
hCaptcha / reCAPTCHA 图形验证时把标签页弹到前台等 N 秒；Cloudflare 一律由脚本自己点。

### 验收

```bash
$PY publisher-official-pdf/scripts/verify_pdf.py <dir> --batch
```

单个 DOI 记为 pass 当且仅当：真实落盘 + `%PDF` 头 / `%%EOF` 尾 / 页数 > 0 +
DOI 或标题与 Crossref 元数据匹配 + 非补充材料。进入登录页、点击成功、单元测试通过都不算。

---

## 四之二、单次全量回归结果（2026-08-31）

`dois.txt` 22 篇，产物 `tests/artifacts/20260831-edge-singlepass/`，
**一次跑完、中途无人工干预、无重试**：

| 结果 | 数量 | 说明 |
|---|---|---|
| 下载成功 | 18 | 全部通过 `verify_pdf.py --batch` |
| 元数据预检跳过 | 4 | 见下 |
| 下载失败 | **0** | — |

四篇跳过都发生在**开浏览器之前**的 Crossref 预检：

| DOI | 报告 | 是否正确 |
|---|---|---|
| `10.1016/j.cell.2016.03.044` | excluded article type | 是，Cell SnapShot 非正文 |
| `10.1101/2020.03.22.20041079` | not a journal article | 是，medRxiv 预印本 |
| `10.48550/arXiv.1706.03762` | metadata unavailable | 是，arXiv 不在 Crossref |
| `10.1145/3806644` | journal abbreviation missing | **否**，Commun. ACM 未收录 |

最后一条是真实缺口：`JOURNAL_ABBREVIATIONS` 里没有 Communications of the ACM，
预检直接跳过，与下载能力无关。补上 `"Communications of the ACM": "COMMUN-ACM"` 后
单独重跑该 DOI，一次成功（`2026-COMMUN-ACM-Establishi.pdf`，2,147,494 B）。

合计 **19 篇期刊正文全部下载成功并通过验收**，覆盖出版商：
Nature、Elsevier、Wiley、Science/AAAS、PNAS、OUP、ACS、Springer、APS、IOP、MDPI、
PLOS、Frontiers、BMC、RSC、AIP、ACM、IEEE、Annual Reviews。

结论：**下载路径本身一次通过，不需要重试**。会让"一次跑不完"的只有缩写表缺项，
遇到新期刊需要先补 `JOURNAL_ABBREVIATIONS` 再跑。

不要把这个结果表述为「所有出版商、所有时间、全新 profile 下 100% 成功」：
它依赖该 profile 已建立的机构会话，且出版商随时可能改版。

## 四之三、人工接管与走丢恢复（2026-08-31 补）

### 接管常开，无需开关

resolve 循环每轮先扫一遍所有标签页：`document.contentType == 'application/pdf'`
即认定为正文，同源 `fetch(location.href)` 完整取回。所以你随时可以把窗口拉出来
自己过验证、自己开 PDF，脚本下一轮就接住，全程不阻塞等你。

判据**不能用 URL 后缀**：PNAS `/doi/pdf/`、IEEE `getPDF.jsp`、Annual Reviews
`?mimetype=application/pdf` 都没有 `.pdf`，按后缀判会全漏。实测 PNAS 页按后缀判为
`unknown`，按 contentType 判正确并取回 267052 B。

每篇开始前 `close_stale_pdf_tabs`：Nature / IEEE 在新标签页开 PDF，那个标签页会活过
本篇，不清理下一篇会把上一篇的 PDF 认成自己的（旧 scansci-pdf 踩过同样的坑）。

接管认三条路：手动开 PDF（扫标签页）、手动过验证后交回脚本（状态机继续）、
**手动点下载**（每篇入口给 `DOWNLOAD_DIR` 拍快照，之后每轮轮询比对新增的完整 PDF）。
快照没有时机问题：基线是每篇一张，比对是每轮一次，文件何时落地下一轮就发现。

**没抄旧路径的网络响应嗅探**：它要求 Playwright 全程 attach 在 context 上听 response，
而 attach 会被 Elsevier 的 CF 检测挂死（正是第 4 级存在的原因）。下载目录快照用更少的
代价覆盖了嗅探的主要价值，且不引入 attach。

### 内容核对只警告，不拦截

落盘后抽前 3 页文本核对 DOI / 标题 / 是否补充材料，不通过只打印并在末尾汇总，
**文件一律保留**。硬判据必然误杀：`10.1103/PhysRevB.4.2406`（1971）PDF 里没印 DOI，
且是 OCR 扫描件，`PHYSICAL REVIEW` 抽成 `PH YSICA L BEVI EUV`，首页开头还是上一篇的
参考文献尾巴。实测该文靠标题过，错配样本（IEEE 的 PDF 冒充 Nature 那篇）能报出来。

### 使用纪律

跑批期间**不要在自动化 Edge 里打开无关 PDF**。`close_stale_pdf_tabs` 只清理上一篇的
残留，防不住本篇进行中新开的，那会被当成本篇正文抓走——文件名对、内容错。

### 走丢恢复

`try_institution_login` 会在任何 `unknown` 状态页面上找 "Sign in / Access" 点下去。
实测 APS：页面落到 `journals.aps.org/prb/accepted`（不是本文），机构流程误点，
跳到 `wayfinder.openathens.net` 后再也回不来，循环空转到超时。

现在：`state == unknown` 且 URL 不含本文 DOI/PII 持续 25s，就退回 `doi.org/<doi>`
重来，最多两次。实测两次连跑都命中恢复并成功取回 1044934 B。

这个 bug 早就存在，只是之前几轮没撞上那个落点——「一次跑完 19/19」是真的，但它
掩盖了一个概率性故障。

## 五、注意事项

- **不要开系统代理跑这个脚本**。`start_edge.ps1` 已带 `--no-proxy-server`，
  但如果哪天需要代理访问某个出版商，那篇要单独处理，别全局改回去。
- **不要用 CloakBrowser 作为主路径**。若要兜底，用完必须彻底杀 chrome 根进程，
  否则残留进程占住服务端座位（单座位授权），下一次启动会被堵约 5 分钟。
- WebVPN 页面自己声明「本系统与部分数据库存在兼容性问题，已发现受影响的数据库包括
  cell、APS 等」。当前方案不经 WebVPN 转发，直连 + 机构 cookie，两家都能下。
- 预印本（medRxiv `10.1101/*`、arXiv `10.48550/*`）按 AGENTS.md 不计入正文下载成功，
  出矩阵时单独计数。

---

## 六、产物

- 主脚本：`publisher-official-pdf/scripts/edge_download.py`（只负责驱动浏览器与编排）
- 出版商站点知识：`mymetal/academic/search/publisher_pdf.py`（页面状态、host 规则、候选过滤、注入 JS）
- 命名与元数据：`mymetal/academic/search/literature_download.py`（缩写表、文件名、Crossref 预检）
- 启动器：`publisher-official-pdf/scripts/start_edge.ps1`
- 验收器：`publisher-official-pdf/scripts/verify_pdf.py`（沿用，未改）
- DOI 全集：`dois.txt`（= `tests/fixtures/test-doi-init.txt`，22 篇）
- 回归产物：`tests/artifacts/20260831-warn/`（19/19 下载并通过验收，零内容警告）

已删除：`cdp_download.py`（手写 CDP，握手不稳）、`edge_cdp_patch.mjs`（早期探索）。
`cb_download.py` 保留作 CloakBrowser 兜底。
