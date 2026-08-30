# PDF 官网下载修复交接文档

更新时间：2026-08-26（America/Los_Angeles）
当前工作目录：`F:\BaiduSyncdisk\version20240608\main_code_space\other\temp\download_pdf`

## 1. 用户目标与不可放宽的边界

目标是把 DOI 测试集中的常规期刊正文从出版商官网完整下载，并形成可复用流程。

必须遵守：

- 只使用 `scansci-pdf browser-get`，从 DOI 进入出版商官网；
- 不使用 `scansci-pdf get`、Elsevier API、OpenAlex、Unpaywall、仓储、预印本替代、Sci-Hub 或 LibGen；
- Supplementary Materials、预印本、Snapshot、采访不能计为期刊正文成功；
- 不读取、打印、复制或共享机构密码、MFA、Cookie、CloakBrowser key 或浏览器 profile；
- 使用新的隔离输出目录，不把旧目录文件计入本轮成功；
- 不批量删除文件或目录。

## 2. 测试集与正确统计口径

DOI 列表：

`F:\BaiduSyncdisk\version20240608\main_code_space\scansci-pdf\mytest\test-doi.txt`

共 22 条。元数据预检后有 4 条必须跳过：

| DOI | 原因 |
|---|---|
| `10.1016/j.cell.2016.03.044` | Cell `SnapShot`，不是所需常规论文 |
| `10.1101/2020.03.22.20041079` | medRxiv 预印本 |
| `10.48550/arXiv.1706.03762` | arXiv 预印本 |
| `10.1145/3806644` | ACM Turing Interview；期刊也不在缩写表 |

剩余 18 条进入官网下载。Annual Reviews `10.1146/annurev.psych.52.1.1` 以前已确认机构无订阅，若仍无权限应报告失败，不绕过付费墙。因此本批预期最多有 17 篇可访问的合格期刊正文，实际数量必须以本轮隔离下载为准。

旧目录：

`F:\BaiduSyncdisk\version20240608\main_code_space\scansci-pdf\mytest\codex_official_22_v151_20260826`

旧“21/21”结论已撤回，至少包含以下误收：

- `5.0316442.pdf`：27 页 Supplementary Materials；
- `2020.03.22.20041079.pdf`：medRxiv；
- `arXiv.1706.03762.pdf`：arXiv；
- `j.cell.2016.03.044.pdf`：Cell Snapshot；
- `3806644.pdf`：ACM Turing Interview。

不要删除旧文件；只在新隔离目录验收。

## 3. 新输出目录与当前运行状态

新输出目录：

`F:\BaiduSyncdisk\version20240608\main_code_space\scansci-pdf\mytest\codex_official_fixed_20260826`

交接时该目录为空，尚无一篇新 PDF 落盘。

用户已在可见浏览器确认：

- Nature 页面已显示“浙江大学图书馆”，无需再次验证；
- Wiley 页面无需验证；
- 切换到 Science 时曾被 Wiley 延迟跳转打断，该导航竞争已修复。

随后用户要求直接开始自动下载。第一次启动因免费 CloakBrowser 席位仍为 `1/1 in use` 而停止。交接时：

- 没有 `official-browser-profile` 对应的本地 Chromium 进程；
- 已结束本 session 自己创建的席位轮询进程；
- `python -m cloakbrowser info` 仍显示 `Sessions: 1/1 in use`；
- 这是异常中止后的服务端租约未释放，需等待变为 `0/1`，不要反复并发启动。

## 4. 已完成代码修复

### mymetal

仓库：

`F:\BaiduSyncdisk\version20240608\main_code_space\pjvasp_package`

新增：

- `mymetal/academic/search/literature_download.py`
- `tests/test_literature.py`

共享功能：

- DOI 规范化与列表解析；
- Crossref 元数据获取，仅用于验证和命名，不下载 PDF；
- `JOURNAL_ABBREVIATIONS` 通用期刊缩写表；
- 预印本、Snapshot、未知期刊等元数据预检；
- 文件名：`年份-期刊缩写-标题前十个有效字符.pdf`；
- PDF 头、尾部 `%%EOF` 和最小尺寸检查。

`mymetal-pkg` 已用 editable 方式安装到：

`C:\Users\louis\mysoft\env\pyenv\scansci-pdf`

### scansci-pdf

仓库：

`F:\BaiduSyncdisk\version20240608\main_code_space\scansci-pdf`

已修改：

- `src/scansci_pdf/main.py`
- `src/scansci_pdf/pdf_utils.py`
- `src/scansci_pdf/sources/browser_direct.py`
- `tests/test_browser_direct_tabs.py`

修复内容：

- 新增 `browser-get --initialize`；
- 新增 `--retries 0..3`，默认在同一浏览器会话内重试 1 次；
- DOI 跳到 arXiv、medRxiv 等预印本域时直接拒绝且不重试；
- 保存候选 PDF 前执行内容检查，拒绝并删除 Supplementary Materials/Information；
- 真实旧文件 `5.0316442.pdf` 已验证被新规则判为 suspicious；
- 初始化和下载自动继承 `HTTPS_PROXY` 或 `HTTP_PROXY`；
- 当前环境代理为本地 `http://127.0.0.1:7897`，无凭据；
- 不再打开不必要的 `geoip=True`，避免缺少 `geoip2` 时启动失败；
- 初始化页面启动失败会返回错误，不再错误提示用户按 Enter；
- 切换出版社前先进入 `about:blank`，导航被旧页面重定向打断时重试一次。

### 当前目录 skill

已更新：

- `publisher-official-pdf/scripts/pdf_download.py`
- `publisher-official-pdf/SKILL.md`
- `publisher-official-pdf/references/setup.md`
- `自动下载文献PDF流程汇总报告.md`

包装脚本先用 mymetal 做元数据预检，再调用官网浏览器下载，最后统一命名。

## 5. 测试结果

已通过：

```text
mymetal tests/test_literature.py: 6 passed
scansci-pdf tests/test_browser_direct_tabs.py: 11 passed
publisher-official-pdf pdf_download.py --selftest: passed
scansci-pdf browser-get --help: --initialize 与 --retries 参数正常
```

完整 `scansci-pdf` 测试曾得到 `26 passed, 3 failed`。3 个失败不是本次路径引入：

- 测试环境缺少 `mcp`；
- `test_polite_delay_is_disabled_unless_fixed_delay_is_enabled` 与旧实现不一致；
- `test_fetch_json_reuses_in_memory_probe_cache` 要求当前实现不存在的 `_json_cache`。

## 6. 下一 session 的准确续跑步骤

### 第一步：等待免费席位释放

在 Git Bash：

```bash
source ~/.bashrc
scanscipy
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
python -m cloakbrowser info
```

只有看到 `Sessions: 0/1 in use` 后才继续。不要购买 Pro，也不要把 Pro 描述成验证码解决方案。

### 第二步：启动整批自动下载

```bash
python 'F:/BaiduSyncdisk/version20240608/main_code_space/other/temp/download_pdf/publisher-official-pdf/scripts/auto_pdf_download.py' \
  mytest/test-doi.txt \
  -o mytest/codex_official_fixed_20260826 \
  --retries 1 \
  --wait 180
```

工作目录必须是：

`F:\BaiduSyncdisk\version20240608\main_code_space\scansci-pdf`

不要使用 `--manual`，用户已经离开。若某篇要求新的 hCaptcha、SSO 或 MFA，让自动流程失败并记录，等用户回来后只初始化失败的出版社。

### 第三步：重点调试 AIP 正文选择

`10.1063/5.0316442` 旧流程抓到的是补充材料。新流程必须：

1. 拒绝 Supplementary Materials 候选；
2. 继续寻找 AIP 主文章 PDF；
3. 只有正文通过内容检查后才成功；
4. 若仍只捕获 SI，修复 PDF 链接选择，不得放宽 suspicious 检查。

### 第四步：逐文件严格验收

对新目录中的每个 PDF 检查：

- 本轮修改时间；
- `%PDF-` 文件头；
- 尾部 `%%EOF`；
- 合理大小；
- 首页标题和文章类型；
- 不是 Supplementary Materials/Information；
- SHA-256 在批次内唯一；
- DOI/题名与文件内容一致；
- 来源日志为 `Publisher(Browser)`；
- 文件名符合 mymetal 规则。

不要只用“文件完整、摘要唯一”推断它是正文。

### 第五步：验证初始化可跨文献复用

Nature 当前 DOI 本来就已登录，不能用同一 DOI 二次下载证明复用。完成主批次后，用同一 Nature profile 自动下载另一篇 DOI，例如本地已有测试 DOI：

`10.1038/s41598-017-03877-5`

放入另一隔离目录并确认无人操作成功，才能记录“同一出版商的其他文献可复用”。其他出版社也应按同样方法验证，不要把 Nature 的结果外推到 Wiley、Elsevier 等不同认证域。

## 7. Git 与提交状态

两个仓库的改动均未提交、未推送。用户本轮只要求修复和交接，没有授权 commit/push。

`pjvasp_package`：

```text
?? mymetal/academic/search/literature_download.py
?? tests/test_literature.py
```

`scansci-pdf`：

```text
 M src/scansci_pdf/main.py
 M src/scansci_pdf/pdf_utils.py
 M src/scansci_pdf/sources/browser_direct.py
 M tests/test_browser_direct_tabs.py
```

不要覆盖或回退这些改动。继续修改前先查看 `git diff`。

## 8. 关键说明

- `--initialize` 使用包装脚本默认等待提示 180 秒；
- `--initialize --wait 600` 把提示改成 600 秒；
- 当前初始化实际以终端收到 Enter 为准，`600` 不是强制倒计时；
- 自动下载模式下 `--wait 180` 才是每篇等待挑战/登录/正文抓取的实际最长时间；
- 用户已明确授权：席位恢复后继续自动下载、调试并完成严格验收；
- 不要把被元数据预检跳过的 4 条重新纳入“全部期刊正文”分母。
