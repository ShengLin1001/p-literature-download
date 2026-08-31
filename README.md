# download_pdf

面向学术科研的 Python 文献 PDF 自动下载仓库。流程从 DOI 进入出版社官网，
用 CDP 驱动一个已登录机构账号的专用 Microsoft Edge，过 Cloudflare 与机构登录后取回正文 PDF，
再由 `mymetal.academic` 完成元数据预检、期刊缩写、文件命名和完整性校验。

## 设计边界

- 本仓库维护下载编排脚本、使用说明、测试输入和本地回归工具。
- 出版商站点知识（页面状态分类、PDF URL 规则、候选过滤、注入的 JS）放
  `mymetal/academic/search/publisher_pdf.py`，与浏览器无关，可被任何驱动复用；
  命名与元数据放 `mymetal/academic/search/literature_download.py`。
  新的通用文献函数统一放入 `mymetal/academic`，本仓库只调用，不复制实现。
- `scansci-pdf` / CloakBrowser 只作兜底，非主路径；非必要不修改。
- AI 生成的分析、交接和汇总文档统一放在 `ai-guide/`。
- PDF、浏览器截图和其他测试产物保存在 `tests/artifacts/`，不提交 Git。

## 目录

```text
.
├── publisher-official-pdf/  # 可复用下载 skill 与 Python 脚本
├── tests/
│   ├── fixtures/            # DOI 列表等测试输入
│   ├── manual/              # 从 scansci-pdf/mytest 迁入的手工回归脚本
│   └── artifacts/           # 本地生成产物，Git 忽略
└── ai-guide/                # AI 分析、交接与汇总文档
```

## 环境准备

Python 3.11 或更高版本，本机已安装 Microsoft Edge。

```bash
python -m pip install playwright websocket-client requests pypdf
python -m pip install -e "F:/BaiduSyncdisk/version20240608/main_code_space/pjvasp_package"
```

不需要 `playwright install`：脚本用 `connect_over_cdp` 驱动本机已装的 Edge。

一次性准备（详见
[publisher-official-pdf/references/setup.md](publisher-official-pdf/references/setup.md)）：

```powershell
# 启动专用自动化 Edge（独立 profile + 调试端口 9333 + 直连）
powershell -NoProfile -File publisher-official-pdf\scripts\start_edge.ps1
# 然后在弹出的窗口里手动登录一次统一身份认证 / WebVPN，cookie 留在该 profile
```

`--no-proxy-server` 是载荷性参数：走系统代理时 Cloudflare 会按出口 IP 判定，
把出版商挑战永久挂在 "Request Verification: In Progress"。

不得提交 cookie、浏览器 profile、登录信息或下载的论文。

## 使用

先运行不联网自检：

```bash
python publisher-official-pdf/scripts/edge_download.py --selftest
```

批量下载与验收：

```bash
python publisher-official-pdf/scripts/edge_download.py dois.txt \
  -o tests/artifacts/latest --timeout 180 --skip-existing \
  --report tests/artifacts/latest/report.json
python publisher-official-pdf/scripts/verify_pdf.py tests/artifacts/latest --batch
```

输出文件名由 `mymetal` 统一生成，格式为 `年份-期刊缩写-标题前十个有效字符.pdf`。
元数据不是 journal-article、文章类型被排除或期刊不在缩写表时，脚本在开浏览器前就报告并跳过。

## 下载范围

默认只接受出版社官网正文 PDF，不用 API、聚合站、仓储或预印本替代正式期刊版本。
下载成功仍需结合来源记录、标题或 DOI、PDF 头尾标和摘要校验，不能只按"文件存在"判断。
