# p-literature-download

按 DOI 列表，从**出版商官网**批量下载学术文献正文 PDF。

流程是：DOI → 出版商官网直连 → 失败时经 ZJU WebVPN 兜底 → 取回正文 PDF →
按 `年份-期刊缩写-标题-DOI后缀.pdf` 统一命名 → 验收。驱动专用 Microsoft Edge；Cookie
只保留在 profile，WebVPN 会话失效时才读取该 profile 内由 Windows DPAPI 加密的凭据。

本仓库同时是一个 agent skill（Claude Code / Codex 等），仓库根目录就是 skill 根目录。
也可以完全不用 agent，直接当命令行工具跑。

这个 skill 已经并入配置仓库 `codex-config`，在那边以 git submodule 的形式挂在
`skills-using/root/p-literature-download`。**改动仍然提交到本仓库**，下游用
`git submodule update --remote` 拉取。

## 不做什么

只从出版商官网取正文。**不用** Elsevier API、Unpaywall、OpenAlex、CORE、DOAJ、
Sci-Hub、LibGen，也不用预印本或仓储版本替代正式期刊版本（但 DOI 本身就指向
arXiv 时照常下载）。补充材料、SnapShot、采访稿都不算下载成功。
期刊**不设白名单**，缩写表外的刊照常下载。

## 快速开始

### 不熟悉 PowerShell？让 agent 帮你

把下面整段提示词复制给支持本地终端和文件操作的 agent（如 Claude Code、Codex）。
安装过程中仍可能需要你确认命令执行权限，并在 Windows 系统凭据窗口中亲自输入浙大
WebVPN 账号和密码；**不要把账号或密码发到聊天中**。

```text
我使用 Windows 10/11，请你实际协助我安装并初始化 p-literature-download，
不要只把命令发给我。项目地址是：
https://github.com/ShengLin1001/p-literature-download

请按以下要求执行：
1. 先检查 Git、Python 3.11+ 和 Microsoft Edge 是否可用；如果缺少软件，说明缺少
   什么并在安装前征得我的确认。
2. 确认当前 agent 的 skill 目录，把完整仓库克隆为 p-literature-download。不要使用
   npx skills add，也不要只复制 SKILL.md。若目标目录已存在，先确认它是这个仓库并
   检查本地改动；不得覆盖本地改动，无改动时才用 git pull 更新。
3. 在该仓库中安装 playwright、websocket-client、pypdf，并运行两个离线自检：
   python scripts/edge_download.py -selftest
   python scripts/verify_pdf.py -selftest
4. 运行 scripts/start_edge.ps1 启动专用 Edge。需要我操作 Windows 凭据窗口时暂停
   提醒我；不要向我索要、读取或回显账号和密码，也不要操作我原有的浏览器 profile。
5. 检查专用 Edge 是否正常启动，并告诉我安装目录、本机 data dir、自检结果和下一步
   怎么显式调用这个 skill。新安装的 skill 如果要新会话才能识别，也请明确提醒我。
6. 完成初始化后先不要下载我的私人 DOI；询问我是否要用仓库中的六篇公开样例验证。
   若我同意且由你执行脚本，请使用 -preset agent，并如实报告每篇结果，不要把启动
   浏览器或打开网页当成下载成功。

只在确实需要我操作或决定时暂停；遇到错误先诊断，不要反复重跑，也不要修改项目脚本。
```

如果仓库已经克隆到本机，也可以先在 agent 中打开仓库目录，再粘贴同一段提示词；agent
应复用现有目录，不再重复克隆。

### 1. 装依赖

Python 3.11+，本机已装 Microsoft Edge。

```bash
python -m pip install playwright websocket-client pypdf
```

不需要 `playwright install`——脚本用 `connect_over_cdp` 驱动你机器上已有的 Edge，
不下载浏览器二进制。除这三个包外没有别的依赖，`scripts/` 下的模块都是纯标准库。

### 2. 起一个专用的自动化 Edge，并登录一次

```powershell
powershell -NoProfile -File scripts\start_edge.ps1
```

会用独立 profile `%USERPROFILE%\.pj\p-literature-download\profile` 启动 Edge，
开调试端口 9333 并**直连**。这个 skill 用到的所有本机状态都在 `~/.pj/p-literature-download/` 下：

```text
~/.pj/p-literature-download/     # -data_dir，一个参数管住全部本机状态
├── profile/     # Edge 的 --user-data-dir，你的机构登录态在这里
└── download/    # 浏览器下载落地处
```

启动脚本会复用已有的 ZJU WebVPN 首页；没有时只补开一个。平时登录态由该 profile
里的 cookie 复用。会话失效且需要兜底时，脚本才读取该 profile 下由 Windows DPAPI 加密的凭据并自动登录。
首次启动会弹系统凭据窗口；换账号或密码时运行 `start_edge.ps1 -initialize_credentials`。
账号和密码都不写源码、命令行、日志或报告，也只有创建凭据的 Windows 用户能解密。

`--no-proxy-server` 不是可选项：直连主路径走系统代理时，Cloudflare 会按出口 IP 判定，
出版商挑战可能永久卡在 "Request Verification: In Progress"。

换个位置放这些状态就传 `-data_dir`，`edge_download.py` 那边是同名的开关，两边只有这一个旋钮。

换学校还要改 `scripts/edge_download.py` 顶部的 `INSTITUTION`（默认 `"Zhejiang University"`），
它用来在出版商的「Access through your institution」下拉框里匹配机构名。

### 3. 先跑离线自检

```bash
python scripts/edge_download.py -selftest
python scripts/verify_pdf.py -selftest
```

不联网、不开浏览器，只验证代码本身。

### 4. 用样例 DOI 试一遍

`examples/dois-sample.txt` 是六篇开放获取文献、六家出版社，不需要机构订阅，
所以装好之后应该拿到 **6/6**；拿不满说明是环境问题（Edge 没起来 / 走了代理 /
依赖没装），不是权限问题。

```bash
python scripts/edge_download.py examples/dois-sample.txt -output pdfs -preset human
python scripts/verify_pdf.py pdfs -batch
```

### 5. 换成你自己的 DOI 列表

每行一个 DOI，空白之后可以写备注；空行和 `#` 开头的行忽略：

```text
10.1038/nature12373            这篇要重点看
10.1103/PhysRevB.88.064104
```

## 两个 preset

绝大多数情况下你只需要记住这两个之一：

```bash
python scripts/edge_download.py dois.txt -output pdfs -preset human   # 人自己跑
python scripts/edge_download.py dois.txt -output pdfs -preset agent   # 被 agent 调用
```

| | `-preset human` | `-preset agent` |
|---|---|---|
| 失败重试 | **2 轮**（轮次间退避 45s） | **0 轮** |
| 验证码 | 弹窗口等你 120s | 不弹 |
| 跳过已有 / 写报告 | 都开 | 都开 |

区别的根子在**谁来兜失败**：agent 看到失败会自己重跑脚本，那本身就是重试，
脚本再轮询一遍就是双重重试，白白多花时间、多敲出版商的门；而且 agent 也解不了
图形验证码，把窗口弹出来没有意义。人自己跑没有这个外层循环，所以两件事都得自己来。

显式写在命令行上的开关**永远压过 preset**，比如 `-preset human -retries 0`。

## 全部开关

| 开关 | 含义 |
|---|---|
| `-output` | PDF 输出目录 |
| `-preset` | `human` / `agent`，见上 |
| `-retries N` | 第一遍跑完后，把失败的再走 N 轮（默认 0） |
| `-timeout` | 每篇每阶段秒数上限（默认 300）。20 MB 以上的综述在 180s 下会失败 |
| `-skip_existing` | 已有同名文件就跳过，补跑时用 |
| `-report` | 每篇写一次 JSON，长跑过程中随时可查 |
| `-cdp` | CDP 端点，默认 `http://127.0.0.1:9333` |
| `-human_wait N` | 只在遇到 hCaptcha 图形验证时把标签页弹到前台等 N 秒 |
| `-data_dir` | 本机状态根目录，默认 `~/.pj/p-literature-download`，下辖 `profile/` 与 `download/` |
| `-selftest` | 只跑离线自检 |

只有 `failed` / `no_pdf_link` / `fetch_failed` / `error` 会被重试。
`unsupported`（补充材料、SnapShot、元数据缺字段）和 `skipped`（已经下过）是确定性结论，
重试不会得到不同答案。`captcha` 同样不重试——图形验证要人过（`-human_wait 120` 或手动接管），
脚本重跑只会把 bot 评分越喂越高。报告始终每个 DOI 一条、按输入顺序，重试是就地覆盖不是追加。

## 浏览器下载目录

每篇先走当前直连四级策略；只有整篇最终未取到 PDF，才从 ZJU WebVPN 首页搜索框
重新进入官方文章页面。这样 AIP、PNAS 可借 WebVPN 取得机构权限，同时 APS、Cell 等与
WebVPN 不兼容的站点仍保留原本可用的直连路径。报告的 `access_via` 会写 `direct` 或
`webvpn.zju.edu.cn`。

绝大多数出版商的 PDF 是脚本在页面里直接 `fetch()` 回来的，不落浏览器的下载目录。
但 Elsevier 第 4 级取件、WebVPN 的 attachment 下载和人工接管会使用该目录。

**落地是 Edge 决定的，所以以 Edge profile 里写的为准。** `start_edge.ps1` 把目录写进
`<data-dir>/profile/Default/Preferences`（默认 `~/.pj/p-literature-download/download`），
`edge_download.py` 启动时从同一处读回来并打印。两边对不上的表现是上面那两条路径
**静默失效**，看起来像出版商的问题——所以启动时那行「浏览器下载目录」值得扫一眼。

## 人工接管

随时可以把 Edge 窗口拉出来自己操作，脚本不会把它压回去，也不会阻塞等你。
它每几秒重读一次所有标签页，所以三种接管动作都认：手动过验证码、手动打开 PDF、
手动点下载按钮。标签页或下载目录中的接管 PDF 必须从前 3 页匹配当前 DOI 或标题才会接收；
不匹配时忽略且不删除源文件，避免把上一篇或无关 PDF 改名成当前文献。普通出版社候选链接
仍只在不匹配时警告，以免误杀未印 DOI 或 OCR 较差的老文献。

## 命名与验收

输出文件名是 `年份-期刊缩写-标题前十个有效字符-DOI后缀.pdf`，例如
`2025-JACS-Machine-Lea-jacs.4c17739.pdf`。DOI 后缀保证一个 DOI 恒对应一个文件名，
标题前缀撞了也不会互相顶掉，`-skip_existing` 只看路径。缩写按 `JOURNAL_ABBREVIATIONS` → 本地缓存 → NLM Catalog（按 ISSN 在线查 ISO 4 缩写）→
Crossref 的 `short-container-title` → 期刊全名 → 出版商名的顺序取，表外的刊自动得到缩写，
不会被拒。首次得到的缩写写入 `<data_dir>/journal_abbreviations.json` 并永久复用，保证文件名稳定。
想给某本刊钉死一个叫法，就往 `JOURNAL_ABBREVIATIONS` 加一条。

脚本**在开浏览器之前**就查元数据定名（Crossref，查不到再走 doi.org 内容协商），
定不了名的才报告并跳过：元数据查不到、补充材料、SnapShot、缺年份或标题。

一个 DOI 记为 pass，当且仅当：本轮真实落盘 + `%PDF-` 头 / `%%EOF` 尾 / 页数 > 0 +
提取文本里的 DOI 或标题与 Crossref 匹配 + 首页不是补充材料。
进入登录页、点击成功、自检通过都**不算**。

## 目录

```text
.
├── SKILL.md                 # agent skill 说明（含原理、四级取件、故障表）
├── agents/openai.yaml       # Codex 接口定义，仅允许显式调用
├── scripts/
│   ├── edge_download.py     # 浏览器驱动与编排、CLI
│   ├── verify_pdf.py        # 验收
│   ├── literature_download.py  # DOI / Crossref / 缩写 / 命名 / 完整性
│   ├── publisher_pdf.py     # 出版商站点知识，与浏览器无关
│   └── start_edge.ps1       # 起专用自动化 Edge
├── references/setup.md      # 安装与首次初始化详解
├── examples/dois-sample.txt # 六篇开放获取样例，给别人试跑
└── tests/fixtures/          # 回归用 DOI 列表
```

## 作为 skill 安装

仓库根目录就是 skill 根目录，所以最直接的装法是整个复制过去、命名成 `p-literature-download`：

```powershell
Copy-Item -Recurse . "$env:USERPROFILE\.claude\skills\p-literature-download"
```

Codex 用 `$env:CODEX_HOME\skills`。

> ⚠️ **不要用 `npx skills add ShengLin1001/p-literature-download`。** 实测过：当仓库根目录本身
> 就是 skill 时，那个 CLI 只会装走 `SKILL.md`，`scripts/` 一个文件都不带，装完是个空壳。
> 它只对「skill 位于仓库子目录」的布局才拷贝完整目录。

要在自己的配置仓库里长期维护并接收本仓库更新，用 **git subtree**（不是 submodule——
submodule 存的是指针，别人克隆你的配置仓库会得到一个空目录）：

```bash
git subtree add  --prefix=<你的路径>/p-literature-download \
    git@github.com:ShengLin1001/p-literature-download.git main --squash
git subtree pull --prefix=<你的路径>/p-literature-download \
    git@github.com:ShengLin1001/p-literature-download.git main --squash   # 之后拉更新
```

该 skill **只允许显式调用**（`$p-literature-download`），不会因为对话里出现 DOI 或
"下载论文"就自动触发——它会开浏览器、发真实请求、动用机构会话，误触发的代价不该由用户承担。

## 安全与合规

- Cookie 与 DPAPI 加密的 WebVPN 凭据只存在于各自 Edge profile；账号和密码不写源码、命令行、日志或报告。
- **不要**把 `~/.pj/p-literature-download/profile` 复制给别人，它含你的机构会话。
  每位使用者建立自己的 profile。
- 不要提交 PDF、profile、Cookie、密钥或运行日志（`.gitignore` 已覆盖）。
- 下载量请自觉控制在个人科研的合理范围内，遵守你所在机构与出版商的使用条款。
