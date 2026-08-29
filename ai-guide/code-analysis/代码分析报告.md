# browser_direct.py 模拟人类行为代码分析报告

日期：2026-08-28
分析对象：`scansci-pdf/src/scansci_pdf/sources/browser_direct.py`（修改后 ~790 行）
相关文件：`instsci.py`（`_construct_publisher_pdf_url` 和 `_find_pdf_link`）、`pdf_utils.py`（`is_suspicious_pdf`）

## 一、`_human_mouse_click` 函数分析（L228-271 修改后）

### 原实现问题
1. **起始点固定**：`sx = tx - random(130,260)`，永远从左侧出发，方向固定是机器人信号
2. **无过冲**：人类鼠标轨迹有 30% 概率过冲目标后修正，原实现直接到达
3. **无抖动**：仅有 `sin(pi*t)*bend` 的弧度，缺少垂直于路径的高频微抖动
4. **点击后冻结**：`mouse.up()` 后立即返回，人类点击后会有微小漂移
5. **固定步数**：32-48 步不随距离动态调整

### 修改后改进
- **随机角度起始**：`angle = random(0, 2*pi)`，方向每次不同
- **新增 Phase 2 过冲**：40% 概率过冲 8-20px 再修正回目标
- **新增垂直 wobble**：`sin(2*pi*step*freq)*amp` 垂直于路径的微抖动
- **新增 Phase 3 aim pause**：0.15-0.45s 瞄准犹豫
- **新增 Phase 5 post-click drift**：点击后随机漂移 5px

### 仍可改进
- **中**：利用 CloakBrowser 内置 `human.patch_page(page)`，它会用 `HumanConfig`（含 `mouse_overshoot_chance`、`mouse_wobble_max`、`mouse_burst_pause` 等）替换 `page.click()`。但当前 `humanize=True` 已自动 patch `page.click()`，问题是代码直接用 `page.mouse.move/down/up` 绕过了 patch。

## 二、`_click_turnstile_checkbox` 函数分析（L281-296 修改后）

### 原实现问题
1. **单一定位策略**：只查找 `input[name='cf-turnstile-response']`，不处理 iframe 式 Turnstile
2. **点击范围窄**：x 偏移 19-24px，太窄

### 修改后改进
- **新增 Strategy 2**：通过 `iframe[src*='challenges.cloudflare.com']` 定位
- **点击范围扩大**：19-30px

### 仍可改进
- **低**：Turnstile 的非交互式模式（managed challenge）不需要点击，只需等待。当前 `_wait_for_human` 的轮询逻辑已能处理这种情况。

## 三、`_wait_for_human` 函数分析（L362-398 修改后）

### 原实现问题
1. **固定 3s 轮询**：机器人特征明显
2. **固定 12s Turnstile 重试**：同样过于规律
3. **等待时无人类行为**：纯等待，不滚动不移动

### 修改后改进
- **jittered 轮询**：2.5-4.0s 随机间隔
- **jittered Turnstile 重试**：8-14s 随机间隔
- **新增随机滚动**：每 15-25s `page.mouse.wheel()`，模拟人类等待时的行为

## 四、`_grab_in_browser` 函数分析（L401-491 修改后）

### PDF 获取策略（优先级正确）
1. **同源 credentialed fetch**：最权威，使用 session cookies
2. **网络捕获匹配**：处理跨域 CDN 重定向
3. **内联 PDF viewer**：Chromium 扩展查看器
4. **trusted click + 等待**：Elsevier 等需要点击
5. **直接导航 PDF URL**：最后手段

### 修改后改进
- 等待循环的 `time.sleep(3)` → jittered 2.5-4.0s
- 新增每 20-30s 随机鼠标移动和滚动
- Turnstile 重试间隔也改为 jittered 8-14s

## 五、出版商覆盖分析

### `_construct_publisher_pdf_url` 覆盖（修改后）
| 出版商 | 原有 | 新增 | 状态 |
|---|---|---|---|
| ACS (pubs.acs.org) | ✅ | | 完整 |
| Wiley | ✅ | | 完整 |
| T&F | ✅ | | 完整 |
| Nature | ✅ | | 完整 |
| Springer | ✅ | | 完整 |
| RSC | ✅ | | 完整 |
| PNAS | ✅ | | 完整 |
| Science | ✅ | | 完整 |
| Elsevier/SD | ✅ | | 完整 |
| **AIP** | | ✅ | 新增 |
| **IOP** | | ✅ | 新增 |
| **MDPI** | | ✅ | 新增 |
| **PLOS** | | ✅ | 新增 |
| **Frontiers** | | ✅ | 新增 |
| **BMC** | | ✅ | 新增 |
| **Annual Reviews** | | ✅ | 新增 |
| **ACM** | | ✅ | 新增 |
| APS | ❌ | | 靠 `citation_pdf_url` meta 提取 |
| IEEE | ❌ | | 靠 `stamp.jsp` 特殊处理 |

### `_find_pdf_link` 同步新增
所有上述新增出版商在 `_find_pdf_link` 中也添加了对应的 HTML 解析规则，从 URL 路径提取 DOI/文章信息（不依赖函数参数中没有的 `doi` 变量）。

### `_SUPPL_MARKERS` 补充材料检测增强
新增 AIP、Elsevier/MMC、RSC、Wiley、Nature 的补充材料 URL 模式。

## 六、改进建议优先级

### 高优先级（已实施）
1. ✅ 修复导入路径断裂
2. ✅ 增强鼠标轨迹（过冲、抖动、随机方向、post-click drift）
3. ✅ Jittered 所有等待间隔（消除固定间隔的机器人特征）
4. ✅ 等待时添加随机滚动/鼠标移动
5. ✅ 补充 8 个出版商的 PDF URL 规则
6. ✅ 增强补充材料检测

### 中优先级（建议后续实施）
1. 尝试使用 `page.click(selector)` 替代直接 `page.mouse.move/down/up`，让 CloakBrowser 的 `humanize` 引擎接管
2. 添加 `_human_mouse_click` 的距离自适应步数（距离越远步数越多）
3. 考虑在 DOI 解析前添加随机延迟（避免连续 DOI 解析的速率限制）

### 低优先级
1. 添加 Cloudflare challenge 页面的更精细检测（不只看 title，还看 body 内容）
2. 考虑使用 CloakBrowser 的 `human_config` 参数自定义 `HumanConfig`
3. 添加下载成功后的 PDF 内容验证（首页是否包含 DOI 或标题关键词）
