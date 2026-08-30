# PDF 下载脚本修复阶段报告

日期：2026-08-28
状态：导入路径已修复、模拟人类行为代码已增强、单元测试全部通过。等待 subagent 调研报告和代码分析报告完成。

## 一、核心问题修复

### 1.1 导入路径断裂（阻塞性 bug）

**问题**：`mymetal/universal/literature.py` 已被重构到 `mymetal/academic/search/literature_download.py`，但 `pdf_download.py` 仍从旧路径导入，导致脚本完全无法运行。

**修复**：
- `publisher-official-pdf/scripts/pdf_download.py`：`from mymetal.universal.literature import ...` → `from mymetal.academic.search.literature_download import ...`
- `publisher-official-pdf/SKILL.md`：环境检查命令和缩写表引用
- `publisher-official-pdf/references/setup.md`：模块说明和路径引用
- `PDF官网下载修复交接文档.md`：代码位置和 git 状态
- `自动下载文献PDF流程汇总报告.md`：代码位置引用

**验证**：`python auto_pdf_download.py --selftest` → ✅ passed
**验证**：`python -m unittest tests.test_literature -v` → 6/6 passed

### 1.2 模拟人类行为增强

**改进 1：`_human_mouse_click`（browser_direct.py）**
- 起始点改为随机角度（原来固定从左侧），避免固定方向被检测为机器人
- 新增 Phase 2：40% 概率过冲并修正（人类特征）
- 新增垂直于路径的 sinusoidal wobble（微抖动）
- 新增 Phase 3：点击前的 aim pause（瞄准犹豫）
- 新增 Phase 5：点击后的 idle drift（人类不会点击后冻结）
- 点击前等待从 0.3-0.7s 改为 0.15-0.45s（更自然的瞄准时间）

**改进 2：`_click_turnstile_checkbox`（browser_direct.py）**
- 新增 Strategy 2：通过 `iframe[src*='challenges.cloudflare.com']` 定位 iframe 式 Turnstile
- 点击坐标范围扩大：x 从 19-24 改为 19-30（更自然的偏移）

**改进 3：`_wait_for_human`（browser_direct.py）**
- 轮询间隔从固定 3s 改为 jittered 2.5-4.0s
- Turnstile 重试间隔从固定 12s 改为 jittered 8-14s
- 新增随机滚动行为（每 15-25s），模拟人类等待时的滚动

**改进 4：`_grab_in_browser`（browser_direct.py）**
- PDF 等待循环的 `time.sleep(3)` 改为 jittered 2.5-4.0s
- 新增每 20-30s 的随机鼠标移动和滚动（模拟人类阅读行为）
- Turnstile 重试间隔也改为 jittered 8-14s

**改进 5：`_browser_launch_kwargs`（browser_direct.py）**
- 新增 `human_preset="careful"`（CloakBrowser 的仔细模式预设）
- 新增 `--disable-blink-features=AutomationControlled` 浏览器参数

**改进 6：`_download_one`（browser_direct.py）**
- DOI 导航前先进入 `about:blank`，避免前一页面的 JS/重定向干扰
- 新增 ACM 和 IOP 的 fallback PDF URL 规则

### 1.3 出版商覆盖增强

**`_construct_publisher_pdf_url`（instsci.py）新增**：
- AIP: `https://pubs.aip.org/aip/pdf/doi/{doi}`
- IOP: `https://iopscience.iop.org/article/{doi}/pdf`
- MDPI: `https://www.mdpi.com/{doi_suffix}/pdf`
- PLOS: `https://journals.plos.org/plosone/article/file?id={doi}&type=printable`
- Frontiers: `https://www.frontiersin.org/articles/{doi}/pdf`
- BMC: `https://www.biomedcentral.com/counter/pdf/{doi}`
- Annual Reviews: `https://www.annualreviews.org/doi/pdf/{doi}`
- ACM: `https://dl.acm.org/doi/pdf/{doi}`

**`_find_pdf_link`（instsci.py）新增同样出版商的 HTML 解析规则**。

**`_SUPPL_MARKERS`（browser_direct.py）新增**：
- AIP: `suppl.pdf`, `_suppl`, `epdf_sup`, `supportinginfo`
- Elsevier: `/mmc/`, `mmc1`, `mmc2`, `s0196`, `s1043`
- RSC: `/articlepdfsupplement`, `/articleimagesupplement`
- Wiley: `suppinfo`, `suppinf`
- Nature: `_supp_info`

## 二、测试验证

```text
pdf_download.py --selftest: ✅ passed
mymetal tests/test_literature.py: 6/6 passed
scansci-pdf tests/test_browser_direct_tabs.py: 11/11 passed
scansci-pdf 全部测试: 28 passed, 2 failed (均为已知旧问题，非本次引入)
```

scansci-pdf diff 统计：
```text
 src/scansci_pdf/main.py                   |  18 +-
 src/scansci_pdf/pdf_utils.py              |   6 +-
 src/scansci_pdf/sources/browser_direct.py | 266 +++++++++++++++++++++++++-----
 src/scansci_pdf/sources/instsci.py        |  54 ++++++
 tests/test_browser_direct_tabs.py         | 142 +++++++++++++++-
 5 files changed, 438 insertions(+), 48 deletions(-)
```

## 三、未完成项

- [ ] 等待调研 subagent 完成：社区/学术界自动化下载 PDF 最佳实践
- [ ] 等待代码分析 subagent 完成：browser_direct.py 深度分析报告
- [ ] 独立审阅 subagent 审阅所有修复
- [ ] 实际下载测试（需要 CloakBrowser 席位和机构网络）
- [ ] Git commit（用户未授权，不做）

## 四、文件变更清单

| 文件 | 变更类型 |
|---|---|
| `publisher-official-pdf/scripts/pdf_download.py` | 修复导入路径 |
| `publisher-official-pdf/SKILL.md` | 更新路径引用 |
| `publisher-official-pdf/references/setup.md` | 更新路径引用 |
| `PDF官网下载修复交接文档.md` | 更新路径引用 |
| `自动下载文献PDF流程汇总报告.md` | 更新路径引用 |
| `scansci-pdf/src/scansci_pdf/sources/browser_direct.py` | 增强模拟人类行为 |
| `scansci-pdf/src/scansci_pdf/sources/instsci.py` | 新增出版商 PDF URL 规则 |
