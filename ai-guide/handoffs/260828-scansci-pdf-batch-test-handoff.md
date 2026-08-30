# scansci-pdf 批量下载测试 · 交接报告（2026-08-28）

## 任务目标

测试 `pdf_download.py`（出版商官网直连批量下载）能否成功下载 `test-doi.txt` 全部 22 篇文献。

**用户指定的策略（必须遵守）**：用户只完成关键的机构登录（CARSI/SSO，一次性），agent 拿登录态直接跑批量自动下载测试。**不要**让用户逐篇初始化 22 个出版商。

## 当前状态（均已实测验证）

- ✅ 环境干净：无 CloakBrowser chrome 进程，服务端座位 `Sessions: 0/1 in use`（`python -m cloakbrowser info` 确认）
- ✅ `mytest/pdf_download.py` 已更新为最新版（8458 B，权威源：`codex-config/skills/p-pdf-download/scripts/pdf_download.py`）；`pdf_download.py.bak`（旧版）未动
- ✅ `--selftest` 通过；`--dry-run` 通过（22/22 DOI 解析成功、arXiv URL 归一化 ✅、短命名规则 ✅）
- ⏸️ 尚无任何 PDF 落盘（`mytest/test_run_20260828/` 为空）
- ⏸️ 初始化进行到第 2 篇被叫停：#1 Nature 用户已完成验证（登录态已存入持久 profile），#2 Cell/Elsevier 页面打不开 → 用户改策略为"关键登录 + 直接测试"

## 关键陷阱（必读，全部实测踩过）

1. **CloakBrowser 免费版 1 座位，座位记在服务端**：强杀进程树后，"session limit reached for your plan" 会持续 ~5-6 分钟，与本地进程无关（本地明明无 chrome 进程）。启动任何浏览器前先 `python -m cloakbrowser info` 确认 `Sessions: 0/1 in use`；不是 0/1 就轮询等待（45s 间隔，实测 ~5 分钟释放），**不要反复重试启动**。
2. **杀进程顺序**：先杀 python 父进程（Playwright 会自动回收 chrome 子树，服务端也能正常注销）；仍有残留时只杀 chrome **根进程**（父进程不是 chrome 的那个），子进程随之回收。辅助脚本：`C:/Users/louis/mysoft/env/pyenv/scansci-pdf/check_cb.ps1`（检测 + 杀根，可复用）。
3. **`browser-get --file` 的 bug**：不剥行内 TAB 后缀，把 `10.1038/nature12373<TAB>test1` 整行当 DOI → URL 变 `%09test1`。绕过：用 `mytest/test-doi-init.txt`（已清洗的 22 个纯 DOI）；`pdf_download.py` 本身传参数列表，无此问题。
4. **交互流程必须 PTY**：`--initialize` / `login_profile.py` 要 `terminal(background=true, pty=true)` 启动 + `process(submit)` 发 Enter；`process(close)` 发 EOF 无效（input() 不退出）。
5. **bash 内联 PowerShell 会被 MSYS 破坏**：`$_`、`$cb` 会被 shell 吃掉 → PowerShell 逻辑一律写成 `.ps1` 文件再 `-File` 执行。
6. **未初始化直接自动下载会卡死**：Nature 页面能打开但 in-page fetch 持续 `not_pdf` 死循环（无权限/验证未过）→ 登录态是自动下载的前置条件。
7. **curl 探测结果不可信**：出版商域名对 curl 大多 403（CF 挡脚本流量），iopscience/frontiersin/annualreviews/arxiv 200。这只说明 curl 被挡，不代表 CloakBrowser 路径不通，别据此下结论。

## 执行计划（下一个 session 按此做）

```bash
# Step 0: 激活环境 + 座位检查（必须 0/1）
source ~/mysoft/env/pyenv/scansci-pdf/Scripts/activate
export PATH="/c/Users/louis/mysoft/env/pyenv/scansci-pdf/Scripts:$PATH" PYTHONUTF8=1 PYTHONIOENCODING=utf-8
python -m cloakbrowser info   # Sessions: 0/1 in use 才继续

# Step 1: 用户关键登录（一次性，产出持久登录态；PTY 后台 + submit 发 Enter）
cd F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf/mytest
python login_profile.py
# 浏览器打开持久 profile（official-browser-profile），用户完成 CARSI/SSO 登录，
# 可自由导航任意站点（Nature 登录态已在 profile 里）。完成后终端按 Enter，自动保存关闭。

# Step 2: 批量自动下载（后台运行 + notify_on_complete=true）
cd F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf/mytest
python pdf_download.py test-doi.txt -o test_run_<日期> --wait 180
# 结束打印 成功/失败 summary；部分失败时补跑：
python pdf_download.py test-doi.txt -o test_run_<日期> --skip-existing

# Step 3: 验收
# 逐文件验 %PDF 头 / EOF 尾 / 大小 / 页数；对照 22 篇输出成功失败矩阵；
# 仍失败的出版商用 --manual 人工兜底（需用户明确同意）。
```

若登录态覆盖不足导致多.publisher 401/403：回 Step 1 补对应出版商登录（用户在浏览器窗口内操作），**不要强杀进程树**（见陷阱 1/2）。

## 文件清单

| 文件 | 说明 |
|---|---|
| `F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf/mytest/pdf_download.py` | 最新版测试脚本（8458 B，本轮已复制） |
| `.../mytest/pdf_download.py.bak` | 旧版备份，**不要覆盖** |
| `.../mytest/auto_pdf_download.py` | 旧 wrapper（指向 codex-config skill scripts） |
| `.../mytest/test-doi.txt` | 原始 22 DOI（TAB 后缀名；供 pdf_download.py 用） |
| `.../mytest/test-doi-init.txt` | 清洗后的 22 纯 DOI（供 --file 用） |
| `.../mytest/login_profile.py` | 本轮新写：打开持久 profile 让用户登录，Enter 保存关闭 |
| `.../mytest/test_run_20260828/` | 输出目录（空） |
| `F:/BaiduSyncdisk/version20240608/main_code_space/codex-config/skills/p-pdf-download/scripts/pdf_download.py` | 脚本权威源 |
| `C:/Users/louis/mysoft/env/pyenv/scansci-pdf/check_cb.ps1` | CloakBrowser chrome 检测/杀根辅助脚本 |

## 相关事实

- scansci-pdf 源码仓：`F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf`
  - `browser-get` 实现：`src/scansci_pdf/sources/browser_direct.py`（`initialize_browser_session` / `run_browser_session`）
  - 持久 profile 目录：`<cache_dir>/official-browser-profile`（默认 `~/.scansci-pdf/cache/`）
- venv：`~/mysoft/env/pyenv/scansci-pdf`（bashrc alias `scanscipy`）
- CloakBrowser 0.5.9 free（1 并发），chromium-151.0.7922.108.3-pro 已安装，license.key 在 `~/.cloakbrowser/`
- 22 篇覆盖：Nature / Elsevier×2 / Wiley / Science / PNAS / Oxford / ACS / Springer / APS / IOP / bioRxiv / MDPI / PLOS / Frontiers / BMC / RSC / AIP / ACM / IEEE / Annual Reviews / arXiv
