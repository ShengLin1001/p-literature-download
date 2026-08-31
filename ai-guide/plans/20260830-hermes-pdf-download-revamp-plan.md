# 官网文献 PDF 自动下载：重构方案与验收计划

日期：2026-08-30 · 作者：hermes · 状态：待评审/待执行

本文件是后续 session 的追踪入口。结论先行：**现流程（CloakBrowser 隐身浏览器独立打官网）单兵作战不稳定，应改造为「分层策略」——默认复用用户日常已登录 Chrome（CARSI/WebVPN 会话），CloakBrowser 仅作降级兜底。** 该思路来自 `nature-downloader`（`codex-config/skills-bak/p-pdf-nature-downloader/SKILL.md`，上游 https://github.com/Yuan1z0825/nature-skills），经本地实测记录验证可行。

## 一、现状与问题（事实基线）

### 1.1 已验证事实（见 `ai-guide/handoffs/20260830-codex-python-pdf-download-handoff.md`）

- 22 篇测试集（`tests/fixtures/test-doi.txt`）中，仅 **1 篇（Nature, 复用已授权持久 profile）真实下载成功**。
- Cloudflare Turnstile（PNAS/Wiley）headless 与有头均 90s 未放行；Elsevier 触发 hCaptcha；IEEE 机构路由失败。
- 旧批次 "21/21 通过" 结论已撤回：旧 pass 判定只验文件头尾/唯一性，误收了补充材料、预印本、SnapShot、采访稿（见 `ai-guide/reports/260826-...summary.md`）。

### 1.2 核心问题（对应用户提出的 5 点）

| # | 用户问题 | 根因/结论 |
|---|---|---|
| 1 | pass 判定不对 | 已明确：唯一口径 = 实际落盘的目标正文 PDF + 完整性 + DOI/标题匹配 + 非预印本/补充材料。任何单元测试、进入登录页、点击成功都不算 pass。 |
| 2 | 主流程断链 | 断点在 Cloudflare 自动放行率与机构登录自动化；CAPTCHA 图像识别列入「不做」清单。 |
| 3 | 状态识别不稳、缺模块单测 | `browser_direct.py` 的状态机（cloudflare/captcha/institution/logged_in/pdf_ready）没有逐状态、逐出版商的独立测试 fixture。 |
| 4 | nature-downloader 思路 | 复用用户日常 Chrome（已登录图书馆 CARSI/WebVPN），通过 CDP 代理（web-access, 127.0.0.1:3456）操作，机构验证天然已解决，Cloudflare 拦截率也大幅下降（真实浏览器指纹 + 已有 cookie）。 |
| 5 | 是否合并 | **是**，见第二节方案。 |

### 1.3 仓库边界（保持不变）

- 本仓库：编排、CLI、测试、文档。
- `scansci-pdf`：浏览器底座（CloakBrowser 路径），非必要不改。
- `mymetal/academic/search/literature_download.py`：元数据/命名/完整性校验，不重复实现。
- nature-downloader 路径依赖：`~/.agents/skills/nature-downloader/` + `web-access` CDP 代理（需 node，脚本 `batch_download.mjs` / `browser_pdf_downloader.mjs`）。

## 二、目标架构：分层下载策略

```
DOI 列表
  │
  ▼
[0] 元数据预检（mymetal）：排除预印本/非期刊文章/未知期刊 → 直接 skip
  │
  ▼
[1] 主路径：用户 Chrome + CDP（nature-downloader 方式）
      前置：用户在 Chrome 完成 CARSI/WebVPN 登录（一次性）；chrome://inspect 开启远程调试；web-access 代理运行
      优点：机构会话现成、真实指纹、Cloudflare 通过率高
      失败态 → 移交用户（carsi_waiting_user / publisher_verification_waiting_user / robot_check），不循环重试
  │
  ▼（主路径不可用时降级）
[2] 降级路径：CloakBrowser 持久 profile（scansci-pdf browser-get，现状流程）
      前置：login_profile.py 人工建立登录态；座位 0/1
  │
  ▼
[3] 统一验收（所有路径共用）：%PDF 头 + %%EOF 尾 + 页数>0 + DOI/标题匹配 + 非补充材料 + 批次内唯一 + 规范命名
```

### 关键设计决定

1. **不合并代码，合并流程**：nature-downloader（node 脚本）与 scansci-pdf（python 包）各自保留；本仓库新增一个**编排器**按顺序尝试 [1]→[2]，统一产出报告。避免把 node 逻辑重写进 python 的大改。
2. **CAPTCHA 图像识别不做**：任何路径遇到 hCaptcha/reCAPTCHA 图片点击，状态记为 `verification_waiting_user`，移交人工，不算失败也不算通过。
3. **状态机单测先行**：先为 `browser_direct.py` 的页面状态识别补 fixture 级单测（存 HTML 快照到 `tests/fixtures/pages/`，不进 git 的放 artifacts），再动主流程。
4. **用户人工动作最小化**：主路径只需用户一次性登录图书馆；降级路径复用已有持久 profile。逐篇初始化 22 个出版商的做法废弃。

## 三、阶段计划与验收标准

### Phase 0：测试基础设施与 pass 口径固化（1 个 session）

- [ ] T0.1 写 `publisher-official-pdf/scripts/verify_pdf.py`：统一验收函数（头/尾/页数/pypdf 提取 DOI 与标题比对/补充材料首页标记/批次内摘要唯一），供所有路径调用。复用 mymetal 现有函数，不重复造轮子。
- [ ] T0.2 定义机器可读报告 schema（JSON）：`{doi, path: chrome_cdp|cloakbrowser, status: downloaded|verification_waiting_user|institution_failed|cloudflare_blocked|skipped_preprint|..., pdf_sha256, evidence}`。**只有 status=downloaded 且通过 T0.1 全部校验才算 pass**。
- [ ] T0.3 页面状态识别单测：为 cloudflare_turnstile / hcaptcha / institution_chooser / zju_sso / pdf_viewer / download_button 各存 1 份真实 HTML fixture，断言 `browser_direct.py` 状态分类函数输出正确。每个状态一个测试，可独立运行。
- 验收：`pytest` 全绿；用已下载的 Nature PDF 和已知的补充材料 PDF 分别喂给 verify_pdf.py，前者 pass 后者 reject。

### Phase 1：主路径——用户 Chrome + CDP（1–2 个 session，需用户在场 1 次）

- [ ] T1.1 环境就绪检查脚本：web-access 代理健康（127.0.0.1:3456/health）、Chrome 远程调试开启、nature-downloader 学校配置 `configure_school.py show` 指向 ZJU 图书馆入口。
- [ ] T1.2 用户一次性登录：Chrome 走 WebVPN/CARSI 登录浙大图书馆（用户本人操作，agent 不接触凭据）。
- [ ] T1.3 跑通 `batch_download.mjs` 单篇（Nature DOI），产物落 `tests/artifacts/<date>-chrome-cdp/`，过 T0.1 校验。
- [ ] T1.4 22 篇测试集小批跑（5–10 篇/批），产出结果 JSON + TSV 移交清单。
- 验收：主路径在**无人操作**前提下，对「浙大有订阅的出版商」成功率显著高于现 CloakBrowser 基线（基线 1/22）；每篇通过 T0.1 全校验；移交人工的项都有明确状态与页面说明。

### Phase 2：编排器与降级整合（1 个 session）

- [ ] T2.1 `publisher-official-pdf/scripts/orchestrate_download.py`：读 DOI 文件 → 预检 → 先试 chrome_cdp → 失败项按状态分流（移交人工 / 降级 cloakbrowser / 终止）→ 统一报告。
- [ ] T2.2 降级路径接入：保持 `scansci-pdf browser-get` 调用约定不变（`--output --wait --report`），座位检查（`cloakbrowser info` 必须 0/1）前置。
- [ ] T2.3 同出版商复用验证：用同出版商**另一篇** DOI 验证登录态复用（不得用初始化时同一篇充数）。
- 验收：22 篇全集跑一遍编排器，产出分路径 × 分状态矩阵；报告无凭据/cookie/带参 SSO URL。

### Phase 3：状态机加固（持续，按需）

- [ ] Cloudflare 仍失败的出版商：检查 CloakBrowser 版本（151.0.7922.108.2 vs .108.3）与持久 profile 组合，不靠增加点击次数。
- [ ] 机构登录流程（选 ZJU → SSO → 回官网）在 Chrome CDP 路径下通常已由图书馆会话覆盖；仍需自动化的出版商单独加 fixture 测试。
- [ ] 每次运行后：本地 CloakBrowser 进程=0 且服务端 session=0/1，否则等释放再跑下次。

### 明确不做（Out of scope）

- CAPTCHA/hCaptcha 图像自动识别点击。
- 绕过付费墙、使用 Sci-Hub/LibGen/聚合站/预印本替代。
- 读取/导出用户密码、cookie、token、profile 内容。
- 对 `verification_waiting_user` 状态做无限自动重试。

## 四、验收总表（Definition of Done）

单个 DOI 记为 **pass** 当且仅当同时满足：

1. 本轮在指定输出目录生成 PDF，来源为 DOI 对应出版社官网（chrome_cdp 或 cloakbrowser 路径日志可查）；
2. `%PDF-` 头、`%%EOF` 尾、页数 > 0、大小合理；
3. PDF 提取的 DOI/标题与请求 DOI 匹配（非上一 DOI 串页）；
4. 首页无 Supplementary Materials/Information 标记；非预印本；非 SnapShot/采访等排除类型；
5. 最终命名 `年份-期刊缩写-标题前十有效字符.pdf`；
6. 报告 JSON 无敏感信息。

项目级验收：22 篇测试集矩阵中，`downloaded` 计数真实可复核（每个都能重跑 T0.1 复验），失败项全部有明确分类状态，移交人工项有清单。

## 五、风险与开放问题

| 风险 | 缓解 |
|---|---|
| web-access / nature-downloader 依赖 node 与外部 skill 安装，环境迁移成本高 | T1.1 检查脚本先行；缺失时给出最小安装步骤，不静默降级 |
| 用户 Chrome 登录态过期（WebVPN 会话短） | 报告中区分「会话过期」与「无权限」；提示重登，不自动重试 |
| CDP 操作用户日常浏览器，误触用户标签页 | batch_download 使用独立 target；`--target` 指定已验证标签页复用 |
| 22 篇中含本就无订阅/预印本/排除类型 | 预检 skip 与验收排除项单独计数，不计入成功率分母争议 |

## 六、追踪指引（给后续 session）

### 进展更新（2026-08-30，hermes 执行）

**已完成（实测验证）：**
- ✅ Phase 0 全部：`verify_pdf.py`（统一验收：%PDF/EOF/页数/DOI/标题比对/补充材料识别）、`cb_download.py`（CloakBrowser 驱动+拟人化 Turnstile+座位预检）、`cdp_download.py`（真 Edge CDP 驱动，连 127.0.0.1:4894，无需每次批准）
- ✅ **关键根因发现**：CloakBrowser 在 **v2rayN TUN 模式**下跳真实 IP 站点 ~15s 被 binary 以"license server unreachable"杀掉（心跳断）；**关 TUN 即稳定**（非 TUN 代理模式 OK）
- ✅ **Cloudflare Turnstile 自动通过**：`human_preset="careful"` + 拟人化鼠标点击，实测 APS PRB 从"Just a moment"放行到期刊页
- ✅ Nature PDF 下载并通过 verify_pdf 全部校验（6 页，doi_in_pdf:true）
- ✅ `ignore_https_errors=True` 解决 doi.org 重定向 cert-CN 问题（MDPI/PLOS 恢复加载）

**进行中/待办：**
- ⏳ APS PRB Cloudflare 页能通过但 PDF 抓取未闭环（`article_unknown` timeout，需调 find_pdf_in_page 对 APS 的适配）
- ⏳ 机构登录路径（Cell/Elsevier 等）未在 CloakBrowser 持久 profile 中建立——需一次性 `--initialize` 或 Edge CDP 路径（用户已在 Edge 登录图书馆）
- ⏳ 22 篇全集矩阵回归

**报告产物**：`tests/artifacts/20260830-hermes-cb/report.json`，`tests/artifacts/20260830-hermes-edge-cdp/`

### 执行顺序

- 执行顺序：Phase 0 → 1 → 2；Phase 3 穿插。
- 每完成一个 Phase，在本目录新增 `<YYYYMMDD>-<agent>-pdf-download-phaseN-result.md`，引用本文件章节号。
- 真实回归产物放 `tests/artifacts/<date>-<path>/`，不提交 git。
- 相关背景文档：`ai-guide/handoffs/20260830-codex-python-pdf-download-handoff.md`（最新基线）、`ai-guide/handoffs/260828-scansci-pdf-batch-test-handoff.md`（CloakBrowser 陷阱）、`codex-config/skills-bak/p-pdf-nature-downloader/SKILL.md`（Chrome CDP 路径完整操作手册）。
