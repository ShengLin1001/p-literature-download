# PDF 下载脚本修复汇总报告

日期：2026-08-28
工作目录：`F:\BaiduSyncdisk\version20240608\main_code_space\other\temp\download_pdf`

## 一、问题概述

用户反映 PDF 下载脚本"还不是百分之百可以下载"。经排查发现两类问题：

1. **阻塞性 bug**：`mymetal` 包中的函数从 `mymetal/universal/literature.py` 重构到 `mymetal/academic/search/literature_download.py`，但 `pdf_download.py` 仍从旧路径导入，导致脚本完全无法运行。
2. **模拟人类行为不足**：`browser_direct.py` 中的鼠标轨迹、等待间隔、Turnstile 处理等代码过于机械，容易被 Cloudflare 检测为机器人。

## 二、修复内容

### 2.1 导入路径修复

| 文件 | 修改 |
|---|---|
| `publisher-official-pdf/scripts/pdf_download.py` | `mymetal.universal.literature` → `mymetal.academic.search.literature_download` |
| `publisher-official-pdf/SKILL.md` | 环境检查命令、缩写表引用 |
| `publisher-official-pdf/references/setup.md` | 模块说明、路径引用 |
| `PDF官网下载修复交接文档.md` | 代码位置、git 状态 |
| `自动下载文献PDF流程汇总报告.md` | 代码位置引用 |

### 2.2 模拟人类行为增强（browser_direct.py）

| 函数 | 改进 |
|---|---|
| `_human_mouse_click` | 随机角度起始、过冲修正(40%)、垂直wobble抖动、aim pause、post-click drift |
| `_click_turnstile_checkbox` | 新增 iframe 式 Turnstile 定位、扩大点击范围 |
| `_wait_for_human` | jittered 轮询(2.5-4.0s)、jittered Turnstile 重试(8-14s)、随机滚动 |
| `_grab_in_browser` | jittered 等待、随机鼠标移动/滚动(每20-30s) |
| `_browser_launch_kwargs` | `human_preset="careful"`、`--disable-blink-features=AutomationControlled` |
| `_download_one` | DOI 导航前先 about:blank、ACM/IOP fallback PDF URL |

### 2.3 出版商覆盖增强（instsci.py）

新增 8 个出版商的 PDF URL 规则：AIP、IOP、MDPI、PLOS、Frontiers、BMC、Annual Reviews、ACM。

同时在 `_find_pdf_link` 中添加了对应的 HTML 解析规则（从 URL 路径提取信息，不依赖函数参数中没有的 `doi` 变量）。

### 2.4 补充材料检测增强（browser_direct.py + pdf_utils.py）

- `_SUPPL_MARKERS` 新增 AIP/Elsevier/RSC/Wiley/Nature 补充材料 URL 模式
- `is_suspicious_pdf` 新增 "Supplemental"/"Supporting Information" 开头检测

## 三、测试验证

```text
pdf_download.py --selftest: ✅ passed
mymetal tests/test_literature.py: 6/6 passed
scansci-pdf tests/test_browser_direct_tabs.py: 11/11 passed
scansci-pdf 全部测试: 28 passed, 2 failed (均为已知旧问题，非本次引入)
```

## 四、交付文件清单

所有交付文档在 `ai-guide/` 子目录下：

```
ai-guide/
├── pdf-download-fix-20260828/
│   ├── 阶段报告.md          # 详细修复阶段报告
│   ├── 汇总报告.md          # 本文件
│   └── scansci-pdf-diff.patch  # 完整 git diff
├── code-analysis/
│   └── 代码分析报告.md       # browser_direct.py 深度技术分析
└── pdf-download-research/
    └── 调研报告.md           # 社区/学术界自动化下载最佳实践调研
```

## 五、后续建议

### 高优先级
1. 实际下载回归测试（需 CloakBrowser 席位 + 机构网络）
2. 利用 `page.click(selector)` 替代直接 `page.mouse` 操作（让 CloakBrowser humanize 引擎接管）

### 中优先级
3. 添加 Unpaywall OA 预检（OA 论文不需要过 Cloudflare）
4. DOI 之间添加随机间隔（降低速率限制风险）
5. 鼠标步数距离自适应

### 低优先级
6. Camoufox 备选（Firefox 路线）
7. 多 profile 轮换
8. 代理出口 IP 轮换

## 六、Git 状态

两个仓库的改动均未提交（用户未授权 commit）：
- `pjvasp_package`：clean（mymetal/academic/search/literature_download.py 已在 main 分支）
- `scansci-pdf`：5 个文件修改（438 insertions, 48 deletions）
- `publisher-official-pdf`：pdf_download.py + SKILL.md + setup.md 修改
