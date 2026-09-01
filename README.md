# p-literature-download

按 DOI 列表，从**出版商官网**批量下载学术文献正文 PDF。

流程是：DOI → doi.org → 出版商官网 → 过 Cloudflare 与机构登录 → 取回正文 PDF →
按 `年份-期刊缩写-标题.pdf` 统一命名 → 验收。驱动的是一个你自己登录过一次的
专用 Microsoft Edge，脚本全程不接触任何密码或 Cookie。

本仓库同时是一个 agent skill（Claude Code / Codex 等），仓库根目录就是 skill 根目录。
也可以完全不用 agent，直接当命令行工具跑。

## 不做什么

只从出版商官网取正文。**不用** Elsevier API、Unpaywall、OpenAlex、CORE、DOAJ、
Sci-Hub、LibGen，也不用预印本或仓储版本替代正式期刊版本。
补充材料、SnapShot、采访稿都不算下载成功。

## 快速开始

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
~/.pj/p-literature-download/     # --data-dir，一个参数管住全部本机状态
├── profile/     # Edge 的 --user-data-dir，你的机构登录态在这里
└── download/    # 浏览器下载落地处
```

在弹出的窗口里手动登录一次你学校的统一身份认证 / WebVPN / CARSI，cookie 就留在这个
profile 里，之后每次跑脚本自动复用。

`--no-proxy-server` 不是可选项：走系统代理时 Cloudflare 按出口 IP 判定，
出版商挑战会永久卡在 "Request Verification: In Progress"。

需要先过 WebVPN 的话，直接把登录页当参数传进去，省得自己敲网址：

```powershell
powershell -NoProfile -File scripts\start_edge.ps1 -LoginUrl "https://webvpn.your-university.edu/"
```

换个位置放这些状态就传 `-DataDir`，Python 那边传同名的 `--data-dir`，两边只有这一个旋钮。

换学校还要改 `scripts/edge_download.py` 顶部的 `INSTITUTION`（默认 `"Zhejiang University"`），
它用来在出版商的「Access through your institution」下拉框里匹配机构名。

### 3. 先跑离线自检

```bash
python scripts/edge_download.py --selftest
python scripts/verify_pdf.py --selftest
```

不联网、不开浏览器，只验证代码本身。

### 4. 用样例 DOI 试一遍

`examples/dois-sample.txt` 是六篇开放获取文献、六家出版社，不需要机构订阅，
所以装好之后应该拿到 **6/6**；拿不满说明是环境问题（Edge 没起来 / 走了代理 /
依赖没装），不是权限问题。

```bash
python scripts/edge_download.py examples/dois-sample.txt -o pdfs --preset human
python scripts/verify_pdf.py pdfs --batch
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
python scripts/edge_download.py dois.txt -o pdfs --preset human   # 人自己跑
python scripts/edge_download.py dois.txt -o pdfs --preset agent   # 被 agent 调用
```

| | `--preset human` | `--preset agent` |
|---|---|---|
| 失败重试 | **2 轮**（轮次间退避 45s） | **0 轮** |
| 验证码 | 弹窗口等你 120s | 不弹 |
| 跳过已有 / 写报告 | 都开 | 都开 |

区别的根子在**谁来兜失败**：agent 看到失败会自己重跑脚本，那本身就是重试，
脚本再轮询一遍就是双重重试，白白多花时间、多敲出版商的门；而且 agent 也解不了
图形验证码，把窗口弹出来没有意义。人自己跑没有这个外层循环，所以两件事都得自己来。

显式写在命令行上的开关**永远压过 preset**，比如 `--preset human --retries 0`。

## 全部开关

| 开关 | 含义 |
|---|---|
| `-o/--output` | PDF 输出目录 |
| `--preset` | `human` / `agent`，见上 |
| `--retries N` | 第一遍跑完后，把失败的再走 N 轮（默认 0） |
| `--timeout` | 每篇每阶段秒数上限（默认 300）。20 MB 以上的综述在 180s 下会失败 |
| `--skip-existing` | 已有同名文件就跳过，补跑时用 |
| `--report` | 每篇写一次 JSON，长跑过程中随时可查 |
| `--cdp` | CDP 端点，默认 `http://127.0.0.1:9333` |
| `--human-wait N` | 只在遇到 hCaptcha 图形验证时把标签页弹到前台等 N 秒 |
| `--data-dir` | 本机状态根目录，默认 `~/.pj/p-literature-download`，下辖 `profile/` 与 `download/` |
| `--selftest` | 只跑离线自检 |

只有 `failed` / `no_pdf_link` / `fetch_failed` / `error` 会被重试。
`unsupported`（不是期刊论文、期刊没缩写）和 `skipped`（已经下过）是确定性结论，
重试不会得到不同答案。报告始终每个 DOI 一条、按输入顺序，重试是就地覆盖不是追加。

## 浏览器下载目录

绝大多数出版商的 PDF 是脚本在页面里直接 `fetch()` 回来的，不落浏览器的下载目录。
但有两条路径依赖它：Elsevier 走的第 4 级取件，以及你手动点「下载」按钮时的接管捕捉。

**落地是 Edge 决定的，所以以 Edge profile 里写的为准。** `start_edge.ps1` 把目录写进
`<data-dir>/profile/Default/Preferences`（默认 `~/.pj/p-literature-download/download`），
`edge_download.py` 启动时从同一处读回来并打印。两边对不上的表现是上面那两条路径
**静默失效**，看起来像出版商的问题——所以启动时那行「浏览器下载目录」值得扫一眼。

## 人工接管

随时可以把 Edge 窗口拉出来自己操作，脚本不会把它压回去，也不会阻塞等你。
它每几秒重读一次所有标签页，所以三种接管动作都认：手动过验证码、手动打开 PDF、
手动点下载按钮。

⚠️ 跑批期间别在这个自动化 Edge 里打开与本次任务无关的 PDF——接管捕捉会扫所有标签页，
可能把它当成当前这篇抓走，结果是文件名对、内容错。临时看文献用你的日常 Edge。

## 命名与验收

输出文件名是 `年份-期刊缩写-标题前十个有效字符.pdf`，例如
`2013-NATURE-Nanometre-s.pdf`。缩写表在 `scripts/literature_download.py` 的
`JOURNAL_ABBREVIATIONS`，新期刊往里加一条即可。

脚本**在开浏览器之前**就查 Crossref 定名，定不了名的直接报告并跳过：不是
journal-article（预印本、会议录）、被排除的文章类型（SnapShot）、期刊不在缩写表。

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

> ⚠️ **不要用 `npx skills add ShengLin1001/download_pdf`。** 实测过：当仓库根目录本身
> 就是 skill 时，那个 CLI 只会装走 `SKILL.md`，`scripts/` 一个文件都不带，装完是个空壳。
> 它只对「skill 位于仓库子目录」的布局才拷贝完整目录。

要在自己的配置仓库里长期维护并接收本仓库更新，用 **git subtree**（不是 submodule——
submodule 存的是指针，别人克隆你的配置仓库会得到一个空目录）：

```bash
git subtree add  --prefix=<你的路径>/p-literature-download \
    git@github.com:ShengLin1001/download_pdf.git main --squash
git subtree pull --prefix=<你的路径>/p-literature-download \
    git@github.com:ShengLin1001/download_pdf.git main --squash   # 之后拉更新
```

该 skill **只允许显式调用**（`$p-literature-download`），不会因为对话里出现 DOI 或
"下载论文"就自动触发——它会开浏览器、发真实请求、动用机构会话，误触发的代价不该由用户承担。

## 安全与合规

- 脚本不读取、不复制、不转发任何密码或 Cookie，登录态只存在于你自己的 Edge profile。
- **不要**把 `~/.pj/p-literature-download/profile` 复制给别人，它含你的机构会话。
  每位使用者建立自己的 profile。
- 不要提交 PDF、profile、Cookie、密钥或运行日志（`.gitignore` 已覆盖）。
- 下载量请自觉控制在个人科研的合理范围内，遵守你所在机构与出版商的使用条款。
