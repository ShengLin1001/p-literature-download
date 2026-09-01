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

会用独立 profile `%USERPROFILE%\edge-automation` 启动 Edge，开调试端口 9333 并**直连**。
在弹出的窗口里手动登录一次你学校的统一身份认证 / WebVPN / CARSI，cookie 就留在这个
profile 里，之后每次跑脚本自动复用。

`--no-proxy-server` 不是可选项：走系统代理时 Cloudflare 按出口 IP 判定，
出版商挑战会永久卡在 "Request Verification: In Progress"。

需要先过 WebVPN 的话，直接把登录页当参数传进去，省得自己敲网址：

```powershell
powershell -NoProfile -File scripts\start_edge.ps1 -LoginUrl "https://webvpn.your-university.edu/"
```

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
python scripts/edge_download.py examples/dois-sample.txt -o pdfs \
    --timeout 180 --skip-existing --report pdfs/report.json
python scripts/verify_pdf.py pdfs --batch
```

### 5. 换成你自己的 DOI 列表

每行一个 DOI，空白之后可以写备注；空行和 `#` 开头的行忽略：

```text
10.1038/nature12373            这篇要重点看
10.1103/PhysRevB.88.064104
```

## 常用开关

| 开关 | 含义 |
|---|---|
| `-o/--output` | PDF 输出目录 |
| `--timeout` | 每篇每阶段秒数上限（默认 300）。20 MB 以上的综述在 180s 下会失败 |
| `--skip-existing` | 已有同名文件就跳过，补跑时用 |
| `--report` | 每篇写一次 JSON，长跑过程中随时可查 |
| `--cdp` | CDP 端点，默认 `http://127.0.0.1:9333` |
| `--human-wait N` | 只在遇到 hCaptcha 图形验证时把标签页弹到前台等 N 秒 |
| `--selftest` | 只跑离线自检 |

脚本只跑一遍，不做轮询。偶发失败（Cloudflare 抖动、超时）带 `--skip-existing`
重跑同一份列表即可，成功的不会重下。

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

把整个仓库目录复制或软链到 agent 的 skill 根目录，重命名为 `p-literature-download`：

```powershell
Copy-Item -Recurse . "$env:USERPROFILE\.claude\skills\p-literature-download"
```

Codex 用 `$env:CODEX_HOME\skills`。该 skill **只允许显式调用**
（`$p-literature-download`），不会因为对话里出现 DOI 或"下载论文"就自动触发——
它会开浏览器、发真实请求、动用机构会话，误触发的代价不该由用户承担。

## 安全与合规

- 脚本不读取、不复制、不转发任何密码或 Cookie，登录态只存在于你自己的 Edge profile。
- **不要**把 `%USERPROFILE%\edge-automation` 这个 profile 复制给别人，它含你的机构会话。
  每位使用者建立自己的 profile。
- 不要提交 PDF、profile、Cookie、密钥或运行日志（`.gitignore` 已覆盖）。
- 下载量请自觉控制在个人科研的合理范围内，遵守你所在机构与出版商的使用条款。
