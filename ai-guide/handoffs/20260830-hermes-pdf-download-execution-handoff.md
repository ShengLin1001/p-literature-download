# 官网文献 PDF 自动下载 · 执行交接文档

日期：2026-08-30 · 作者：hermes · 状态：**部分完成，阻塞待用户决策**

本文档是当前任务的可执行交接，供后续 session 直接接手。配套方案文档：
`ai-guide/plans/20260830-hermes-pdf-download-revamp-plan.md`（含完整架构与验收口径）。

---

## 一、当前真实状态（实测，非推测）

### 1.1 已交付脚本（`publisher-official-pdf/scripts/`）

| 脚本 | 作用 | 状态 |
|---|---|---|
| `verify_pdf.py` | **统一验收器**：%PDF 头/EOF 尾/页数>0/pypdf 提取文本/DOI+标题比对/补充材料首页识别/SHA-256 | ✅ selftest 过，真 PDF 复验过 |
| `cb_download.py` | **CloakBrowser 驱动**：座位预检 + 拟人化 Turnstile 点击 + `ignore_https_errors` + 崩溃分类重试 | ✅ selftest 过，实测下载成功 |
| `cdp_download.py` | **真 Edge CDP 驱动**：连 `127.0.0.1:4894`（用户已批准远程调试），复用用户已登录图书馆会话 | ✅ 连接通，未跑完下载 |
| `pdf_download.py` | 原有编排器（调 `scansci-pdf browser-get`） | 未改动 |
| `edge_cdp_patch.mjs` | DevToolsActivePort 补丁（早期探索，可忽略） | 废弃 |

### 1.2 6 篇冒烟集实测结果（`tests/artifacts/20260830-hermes-cb/report.json`）

| DOI | 出版商 | 状态 | 验收 |
|---|---|---|---|
| 10.1038/nature12373 | Nature | ✅ downloaded 1017677 B | ✅ verify_pdf 全过 |
| 10.1186/1471-2105-15-135 | BMC | ✅ downloaded 5699993 B | ✅ verify_pdf 全过 |
| 10.1103/PhysRevB.88.064104 | APS/PRB | ❌ Cloudflare 过了但 `article_unknown` | — |
| 10.3390/s21051705 | MDPI | ❌ `article_with_pdf_button` 但抓取未闭环 | — |
| 10.1371/journal.pone.0000308 | PLOS | ❌ `article_with_pdf_button` 但抓取未闭环 | — |
| 10.3389/fnins.2013.00071 | Frontiers | ❌ `captcha_waiting_user`（hCaptcha） | 不做 |

**通过率：2/6（均通过统一验收）**

---

## 二、关键技术发现（必读，全部实测）

### 2.1 CloakBrowser 稳定性的 root cause

**v2rayN TUN 模式会杀掉 CloakBrowser**。机制：CloakBrowser binary 持有到 `cloakbrowser.dev` 的 license 心跳；TUN 模式（myruleset）在跳转真实 IP 站点（doi.org/aps.org 等）时断开该连接，~15s 后 binary 以 "license server unreachable" 自杀，并残留服务端座位 ~5-6min。

**解法**：关闭 TUN（用户实测非 TUN 代理模式 OK）。这是此前 Codex 能跑通而现在不行的最可能原因。

### 2.2 Cloudflare Turnstile 自动通过

- 定位：必须用 `input[name='cf-turnstile-response']` 的**父元素 bounding box**（不是 iframe）。
- 点击：`human_preset="careful"` + 拟人化鼠标（移动/按压时长）。
- 实测：APS PRB 从 "Just a moment" 成功放行到 `journals.aps.org/prb/abstract/...`。

### 2.3 doi.org 重定向 cert 问题

`launch_persistent_context(..., ignore_https_errors=True)` 解决 MDPI/PLOS 的 `ERR_CERT_COMMON_NAME_INVALID`。

### 2.4 座位管理（防堵死）

- 关闭必须彻底杀 chrome 根进程：`check_cb.ps1`（只杀父进程非 chrome 的）。
- 启动前必须 `python -m cloakbrowser info` 显示 `Sessions: 0/1 in use`。
- 本地无 chrome 进程 ≠ 座位释放（服务端可能仍 1/1，需等 ~5min）。
- 已写入 memory（CloakBrowser 座位管理规则）。

---

## 三、下一步任务（按优先级）

### T1（最高）：打通 Edge CDP 路径（机构文献主路径）

**为什么**：用户已在真 Edge 登录浙大图书馆（CARSI/WebVPN），实测 Cell/PRB 能下。这条路径天然解决机构验证 + 大部分 Cloudflare。

**做法**：
```bash
# 确认 Edge 远程调试仍活着（用户已批准）
curl -s http://127.0.0.1:4894/json/list

# 跑 cdp_download.py（需补 PDF 抓取逻辑，参照 cb_download.py）
python publisher-official-pdf/scripts/cdp_download.py tests/fixtures/cdp-smoke.txt -o tests/artifacts/<date>-edge --timeout 240
```

**已知问题**：`cdp_download.py` 的 WebSocket 握手会超时（之前测过），需调试 reader 线程。可先修这个，或换 `chrome-devtools-mcp`（`npx -y chrome-devtools-mcp@latest --browserUrl=http://127.0.0.1:4894`）。

**验收**：Cell/Elsevier 文献下载成功 + verify_pdf 全过。

### T2：修 CloakBrowser 剩余 3 篇选择器

- **APS PRB**：Cloudflare 过了，需调 `find_pdf_in_page` 识别 APS 的 PDF 按钮（或直接用 `journals.aps.org` 的 PDF URL 模式）。
- **MDPI/PLOS**：`article_with_pdf_button` 识别到了，但点击后 PDF 没抓到。需：(a) 点击后等新 tab 弹出 PDF viewer，或 (b) 从 DOM 提取 direct PDF href 再 fetch。
- 每篇用隔离 `--timeout 150 --retries 1` 测，座位占用时等待。

### T3：22 篇全集矩阵回归

用 `tests/fixtures/test-doi.txt`，分路径（cloakbrowser / edge_cdp）× 分状态出矩阵。预印本/排除类型单独计数。

### T4：机构登录路径（若 Edge 不通）

CloakBrowser 持久 profile 需一次性 `--initialize` 建立机构登录态（用户操作）。命令：
```bash
python publisher-official-pdf/scripts/auto_pdf_download.py tests/fixtures/test-doi-init.txt -o tests/artifacts/init --initialize --wait 600
```

---

## 四、操作手册（后续 session 直接抄）

### 环境检查
```bash
# CloakBrowser 路径
/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -File C:/Users/louis/mysoft/env/pyenv/scansci-pdf/check_cb.ps1
/c/Users/louis/mysoft/env/pyenv/scansci-pdf/Scripts/python.exe -m cloakbrowser info  # 必须 0/1

# Edge CDP 路径
curl -s http://127.0.0.1:4894/json/list
```

### 跑下载
```bash
cd /f/BaiduSyncdisk/version20240608/main_code_space/other/temp/download_pdf

# CloakBrowser（后台跑，避免终端超时中断）
/c/Users/louis/mysoft/env/pyenv/scansci-pdf/Scripts/python.exe publisher-official-pdf/scripts/cb_download.py tests/fixtures/cb-smoke.txt -o tests/artifacts/<date>-cb --timeout 150 --retries 1 --report tests/artifacts/<date>-cb/report.json

# Edge CDP
/c/Users/louis/mysoft/env/pyenv/scansci-pdf/Scripts/python.exe publisher-official-pdf/scripts/cdp_download.py tests/fixtures/cdp-smoke.txt -o tests/artifacts/<date>-edge --timeout 240
```

### 验收（所有路径共用）
```bash
/c/Users/louis/mysoft/env/pyenv/scansci-pdf/Scripts/python.exe publisher-official-pdf/scripts/verify_pdf.py <pdf> --doi <doi>
# 或批量
/c/Users/louis/mysoft/env/pyenv/scansci-pdf/Scripts/python.exe publisher-official-pdf/scripts/verify_pdf.py <dir> --batch --json
```

---

## 五、验收口径（复用计划文档）

单个 DOI 记为 **pass** 当且仅当：真实落盘 PDF + `%PDF` 头/`%%EOF` 尾/页数>0 + DOI/标题匹配 + 非补充材料/预印本 + 规范命名。任何单元测试、进入登录页、点击成功都不算 pass。

---

## 六、产物清单

- 脚本：`publisher-official-pdf/scripts/{verify_pdf,cb_download,cdp_download}.py`
- 报告：`tests/artifacts/20260830-hermes-cb/report.json`（6 篇冒烟集）
- PDF：`tests/artifacts/20260830-hermes-cb/{10.1038_nature12373,10.1186_1471-2105-15-135}_Official.pdf`（均过验收）
- 计划：`ai-guide/plans/20260830-hermes-pdf-download-revamp-plan.md`
- 本文档：`ai-guide/handoffs/20260830-hermes-pdf-download-execution-handoff.md`
