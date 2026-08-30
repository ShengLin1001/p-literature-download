# Python 官网文献 PDF 自动下载交接

## 结论先行

**当前总体结果：未通过。**

本任务中的 `passed` 只能表示：Python 自动流程从出版社官网实际取得目标正文 PDF，并完成文件完整性、文献身份和来源校验。单元测试、自检、成功启动浏览器、点击 Turnstile、进入机构登录页或复用登录状态，都不能单独称为 `passed`。

当前只有 Nature 样本实际下载成功；Cloudflare 样本没有自动放行，新的机构登录流程也没有完成后再下载 PDF。因此还没有满足用户要求的完整能力。

## 用户验收口径

至少需要用真实官网回归分别证明：

1. Cloudflare Turnstile 由程序自动通过，随后实际下载该 DOI 的出版社正文 PDF。
2. 需要机构权限的文章能自动进入机构入口、选择浙江大学、使用已有安全授权状态完成登录，并实际下载正文 PDF。
3. 自动调用过程不弹出浏览器窗口；`--manual` 和 `--initialize` 不计入自动成功。
4. 每个成功文件必须同时满足：
   - 来源为 DOI 对应出版社官网；
   - 文件头为 `%PDF-`，文件尾包含 `%%EOF`；
   - PDF 标题或正文 DOI 与请求 DOI 对应；
   - 不是补充材料、预印本或上一 DOI 遗留文件；
   - 报告不包含 Cookie、密码、Token 或带查询参数的 SSO URL。
5. 每次退出后必须同时确认：本地 CloakBrowser Chromium/Playwright 进程为零，服务端 active session 为零。否则不能开始下一次运行。

## 代码位置与仓库边界

- 编排仓库：`F:\BaiduSyncdisk\version20240608\main_code_space\other\temp\download_pdf`
- 浏览器底座：`F:\BaiduSyncdisk\version20240608\main_code_space\scansci-pdf`
- 通用文献元数据函数：`F:\BaiduSyncdisk\version20240608\main_code_space\pjvasp_package\mymetal\academic\search\literature_download.py`
- Python：`C:\Users\louis\mysoft\env\pyenv\scansci-pdf\Scripts\python.exe`
- CLI：`C:\Users\louis\mysoft\env\pyenv\scansci-pdf\Scripts\scansci-pdf.exe`

不要覆盖现有工作树。`scansci-pdf` 接手时已有未提交修改：

```text
M src/scansci_pdf/main.py
M src/scansci_pdf/pdf_utils.py
M src/scansci_pdf/sources/browser_direct.py
M src/scansci_pdf/sources/instsci.py
M tests/test_browser_direct_tabs.py
```

`download_pdf` 中还有用户已有的 `ai-guide/` 重命名变更，也必须保留。

## 找到的旧版本

### `tests/artifacts/pdf_download.py.bak`

这是此前 `scansci-pdf/mytest` 中保存的备份，但它始终调用：

```text
scansci-pdf browser-get ... --manual
```

Cloudflare 和机构登录都依赖人工操作，不能恢复为本次要求的自动版。

### `mymetal/academic/search/literature_download.py` 历史

Git 历史只有 DOI 元数据、期刊缩写、文件命名和 PDF 完整性逻辑，没有 CloakBrowser、Cloudflare 或机构登录实现。

### 旧 Cloudflare 手工测试

`tests/manual/test_cf_bypass.py` 曾把 APS 的 `Attention Required! | Cloudflare` HTML 页面误判为成功：页面响应是 `text/html`，不是 PDF。不要把这份旧输出当作恢复依据。

## 本轮实际修改

### 1. 修复无头配置类型

文件：`scansci-pdf/src/scansci_pdf/sources/browser_direct.py`

`config-cmd browser_headless true` 保存的是字符串，Playwright 要求布尔值，原先会报：

```text
BrowserType.launch_persistent_context: headless: expected boolean, got string
```

现在 `_browser_launch_kwargs()` 会把 `true/false/1/yes/on` 字符串转换为真正布尔值。

对应回归检查位于：

```text
scansci-pdf/tests/test_browser_direct_tabs.py
test_browser_launch_kwargs_normalizes_string_headless_config
```

### 2. 固定可启动的 CloakBrowser 版本

文件：`publisher-official-pdf/scripts/pdf_download.py`

子进程环境增加：

```python
child_env.setdefault("CLOAKBROWSER_VERSION", "151.0.7922.108.2")
```

原因：本机默认 `.108.3` 启动时发生 Chromium native `raw_ptr` FATAL；`.108.2` 已验证可以启动。显式环境变量仍可覆盖该默认值。

### 3. 当前用户配置

```text
browser_headless = true
```

自动模式不再弹窗。注意 `--manual`、`--initialize` 本来就是交互模式，不能用它们证明静默自动下载成功。

## 真实官网回归结果

| DOI | 场景 | 结果 | 是否算下载通过 |
|---|---|---|---|
| `10.1038/nature12373` | Nature，复用持久 profile 的已有授权状态 | 实际下载官方 PDF | 是，仅此 DOI |
| `10.1073/pnas.0507655102` | PNAS Cloudflare，真正 headless | 自动点击 Turnstile 多次，90 秒仍为 `Just a moment...` | 否 |
| `10.1073/pnas.0507655102` | PNAS Cloudflare，有头但最小化并移到屏幕外 | 90 秒仍为 `Just a moment...` | 否 |
| `10.1002/adma.73337` | Wiley Cloudflare | 自动点击 Turnstile，但未放行 | 否 |
| `10.1016/j.commatsci.2018.12.013` | Elsevier | hCaptcha/reCAPTCHA 类验证，状态 `verification_waiting_user` | 否 |
| `10.1109/tit.2026.3670320` | IEEE 机构访问 | 自动路由后仍为 `institution_access_failed` | 否 |

Nature 成功文件：

```text
tests/artifacts/20260830-codex-retest/institution-download-output/2013-NATURE-Nanometre-s.pdf
size: 1,017,677 bytes
SHA-256: 6A1EF2EDDAE851F88286824C8897E02B8F5410344CC0F3E039B52B903C634361
header: %PDF-
tail: contains %%EOF
DOI/title: 10.1038/nature12373 / Nanometre-scale thermometry in a living cell
```

报告：

```text
tests/artifacts/20260830-codex-retest/institution-download-output/browser-get-report.json
tests/artifacts/headless-pnas-20260830-report.json
```

Nature 只证明持久 profile 已有授权状态可被自动复用；它没有证明本轮重新执行了完整机构登录流程。

## 代码测试结果（不要称为文献下载 passed）

```text
scansci-pdf/tests/test_browser_direct_tabs.py: 21 tests passed
publisher-official-pdf/scripts/pdf_download.py --selftest: ok
publisher-official-pdf/scripts/auto_pdf_download.py --selftest: ok
compileall: ok
git diff --check: ok，只有既有 LF/CRLF 提示
```

这些结果只说明相关代码检查通过。

## 当前运行态

交接文档生成前最后一次检查：

```text
CloakBrowser server sessions: 0/1
本地 .cloakbrowser Chromium 进程: 0
browser_headless: true
```

此前出现过本地进程已经为零、服务端仍长期显示 `1/1` 的情况。不要在这种状态下反复启动；等待服务端恢复到 `0/1`。

## Claude 接手建议

1. 从当前 `browser_direct.py` 继续，不要恢复 `.bak`。
2. 首先只跑一个 Cloudflare DOI，必须看到挑战页离开并最终写出匹配 DOI 的 PDF，才记录成功。
3. 再只跑一个付费机构 DOI，记录安全的状态迁移：出版社访问墙 → 机构选择 → 浙江大学授权页或已有会话 → 出版社文章 → 正文 PDF。不要读取或输出凭据、Cookie、Token、MFA 内容。
4. Cloudflare 若仍失败，应检查 CloakBrowser `.108.2/.108.3` 与持久 profile 的真实组合；不要仅增加点击次数，也不要把“点击成功”当作“验证通过”。
5. 每次运行都必须在 `finally` 关闭 persistent context；运行后检查本地进程和服务端 session。
6. 最终报告按以下三类分别写：
   - `PDF 下载通过`：有真实、匹配 DOI 的官方 PDF；
   - `代码测试通过`：仅测试成功；
   - `失败/阻塞`：没有实际 PDF。

## 最小验证命令

```powershell
$env:CLOAKBROWSER_VERSION = '151.0.7922.108.2'
& 'C:\Users\louis\mysoft\env\pyenv\scansci-pdf\Scripts\scansci-pdf.exe' config-cmd browser_headless true
& 'C:\Users\louis\mysoft\env\pyenv\scansci-pdf\Scripts\python.exe' -m pytest tests/test_browser_direct_tabs.py -q
```

真实回归必须使用：

```powershell
scansci-pdf browser-get '<DOI>' --output '<isolated-artifact-dir>' --wait 90 --retries 0 --report '<report.json>'
```

只有命令最终生成并校验正确的出版社正文 PDF，才能把该 DOI 标为 `passed`。
