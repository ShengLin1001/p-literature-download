# PDF 下载脚本修复审阅报告

日期：2026-08-28
审阅范围：`download_pdf/ai-guide/pdf-download-fix-20260828/` 下的三项修复（导入路径、模拟人类行为增强、出版商规则补充）
审阅方式：源码检查 + AST/compile 校验 + 真实测试执行（`source ~/.bashrc; scanscipy` 激活后运行）

---

## 一、导入路径修复 ✅ 通过

**文件**：`publisher-official-pdf/scripts/pdf_download.py`（第 31 行）

```python
from mymetal.academic.search.literature_download import (
    check_journal_metadata,
    fetch_doi_metadata,
    generate_pdf_filename,
    is_complete_pdf,
    normalize_doi,
    parse_dois,
)
```

- 已正确从新路径 `mymetal.academic.search.literature_download` 导入，不再使用旧的 `mymetal.universal.literature`。
- 该文件内无任何 `mymetal.universal.literature` 残留引用。

---

## 二、文档更新 ✅ 通过

逐一检查 SKILL.md、references/setup.md、PDF官网下载修复交接文档.md、自动下载文献PDF流程汇总报告.md，全部已引用新路径 `mymetal/academic/search/literature_download.py`：

| 文档 | 关键引用 | 状态 |
|---|---|---|
| `publisher-official-pdf/SKILL.md` | `python -c "from mymetal.academic.search.literature_download import ..."` | ✅ 新路径 |
| `publisher-official-pdf/references/setup.md` | `mymetal.academic.search.literature_download 提供 …`；`mymental/academic/search/literature_download.py` | ✅ 新路径 |
| `PDF官网下载修复交接文档.md` | `mymetal/academic/search/literature_download.py` | ✅ 新路径 |
| `自动下载文献PDF流程汇总报告.md` | `pjvasp_package/mymetal/academic/search/literature_download.py` | ✅ 新路径 |

**说明**：在文档中出现旧路径字符串的 5 处均为"问题/修复描述"性质的历史性叙述（例如"从 `mymetal/universal/literature.py` 重构到 ..."），属于对修复过程的说明，不是仍在生效的代码引用，可接受保留。可执行代码（.py）中已无任何旧路径引用。

---

## 三、模拟人类行为增强 ✅ 通过

**文件**：`scansci-pdf/src/scansci_pdf/sources/browser_direct.py`

### 3.1 `_human_mouse_click`（第 238–288 行）

| 阶段 | 增强 | 验证 |
|---|---|---|
| 起始点 | 随机角度 `angle = random.uniform(0, 2π)`，距离 130–260px（非固定从左侧） | ✅ |
| Phase 1 移动 | smoothstep 缓动 + 垂直 sinusoidal wobble（amp 1.5–4.0，32–48 步） | ✅ |
| Phase 2 过冲 | 40% 概率过冲 8–20px 再 6–12 步回正 | ✅ |
| Phase 3 瞄准暂停 | 点击前 0.15–0.45s 犹豫 | ✅ |
| Phase 4 可信点击 | mouse.down/up，hold 0.09–0.19s | ✅ |
| Phase 5 空闲漂移 | 点击后 0.2–0.6s + 目标附近 ±5px 漂移 | ✅ |

### 3.2 `_wait_for_human`（第 371–398 行）

- 轮询间隔改为 jittered `random.uniform(2.5, 4.0)` s ✅
- Turnstile 重试间隔改为 jittered `random.uniform(8, 14)` s ✅
- 新增每 `random.uniform(15, 25)` s 的随机滚动 `page.mouse.wheel(0, random.uniform(100, 300))` ✅

### 3.3 `_click_turnstile_checkbox`（第 291–314 行）

- Strategy 1：`input[name='cf-turnstile-response']` → 父级 bounding box（原逻辑） ✅
- Strategy 2：新增 `iframe[src*='challenges.cloudflare.com']` 定位 iframe 式 Turnstile ✅
- 点击 x 坐标范围扩为 `random.uniform(19, 30)`，y 居中 ±0.05 ✅

### 3.4 附带增强（`_grab_in_browser`、`_download_one` 等）

- `_grab_in_browser` PDF 等待循环 `time.sleep` 改为 jittered 2.5–4.0s；新增每 20–30s 随机滚动+鼠标移动 ✅
- `_SUPPL_MARKERS` 新增 AIP / Elsevier / RSC / Wiley / Nature 补充材料标记 ✅

---

## 四、出版商规则补充 ✅ 通过

**文件**：`scansci-pdf/src/scansci_pdf/sources/instsci.py`

### 4.1 `_construct_publisher_pdf_url(doi, resolved_url)`（第 303–352 行）

| 出版商 | 规则 | 状态 |
|---|---|---|
| AIP | `https://pubs.aip.org/aip/pdf/doi/{doi}` | ✅ |
| IOP | `https://iopscience.iop.org/article/{doi}/pdf` | ✅ |
| MDPI | `https://www.mdpi.com/{doi_suffix}/pdf` | ✅ |
| PLOS | `https://journals.plos.org/plosone/article/file?id={doi}&type=printable` | ✅ |
| Frontiers | `https://www.frontiersin.org/articles/{doi}/pdf` | ✅ |
| BMC | `https://www.biomedcentral.com/counter/pdf/{doi}` | ✅ |
| Annual Reviews | `https://www.annualreviews.org/doi/pdf/{doi}` | ✅ |
| ACM | `https://dl.acm.org/doi/pdf/{doi}` | ✅ |

8/8 全部新增 ✅

### 4.2 `_find_pdf_link(html, base_url)`（第 355–466 行）

出版商 HTML 解析规则：AIP / IOP / MDPI / PLOS / Frontiers / BMC / Annual Reviews 均新增 ✅
ACM 未单独写分支，但其 PDF 链接形如 `/doi/pdf/...`，已被通用的 Strategy 2 `/doi/pdf/` 匹配覆盖（功能等价，非缺陷）。

### 4.3 NameError 风险校验 ✅ 无风险

- 函数签名仅 `(html, base_url)`，**不含 `doi` / `doi_suffix` 参数**。
- AST 分析：`_find_pdf_link` 内使用的 Name 标识符为 `doi_part`、`doi_val` 等局部变量（在函数体内本地定义后使用），无任何对 `doi` / `doi_suffix` 的裸引用。
- `compile(tree, "instsci.py", "exec")` 成功，无语法错误。
- 结论：不存在 `_find_pdf_link` 引用 `doi`/`doi_suffix` 导致的 NameError。

---

## 五、测试验证 ✅ 全部通过

在 `source ~/.bashrc; scanscipy` 激活 Python 环境后依次运行：

| 测试 | 命令 | 结果 |
|---|---|---|
| publisher-official-pdf 自检 | `cd publisher-official-pdf/scripts && python auto_pdf_download.py --selftest` | ✅ `✅ selftest ok` |
| scansci-pdf 浏览器标签测试 | `cd scansci-pdf && python -m pytest tests/test_browser_direct_tabs.py -v` | ✅ **11 passed in 2.68s** |
| pjvasp_package 文献函数测试 | `cd pjvasp_package && python -m unittest tests.test_literature -v` | ✅ **Ran 6 tests … OK** |

三项测试全部通过，exit code 均为 0。

---

## 六、残留旧路径引用检查 ✅ 通过

对整个 `download_pdf/` 目录树扫描 `mymetal.universal.literature` 与 `mymetal/universal/literature` 两类字面量：

- **可执行代码（.py）**：0 处残留 ✅
- **文档（.md）**：5 处，均为对修复过程的描述性叙述（"从旧路径重构到新路径"），属历史性说明，非生效代码引用，可接受保留：
  - `ai-guide/pdf-download-fix-20260828/阶段报告.md`（2 处）
  - `ai-guide/pdf-download-fix-20260828/汇总报告.md`（2 处）
  - `ai-guide/pdf-download-research/调研报告.md`（1 处）

---

## 七、总结

| 项目 | 结论 |
|---|---|
| 1. 导入路径修复 | ✅ 通过 |
| 2. 文档更新 | ✅ 通过（残留均为描述性叙述） |
| 3. 模拟人类行为增强 | ✅ 通过（五阶段全实现 + jittered + iframe Turnstile） |
| 4. 出版商规则补充 | ✅ 通过（8/8 + 无 NameError） |
| 5. 测试验证 | ✅ 三套测试全过（1+11+6） |
| 6. 残留旧路径引用 | ✅ 通过（.py 零残留） |

**总判定：所有修复正确完成，无阻塞性问题。** 唯一可优化点（非缺陷）：`_find_pdf_link` 中 ACM 可单独加一条分支使覆盖与 `_construct_publisher_pdf_url` 完全对齐，但现有通用 `/doi/pdf/` 规则已覆盖其链接格式，不影响功能。
