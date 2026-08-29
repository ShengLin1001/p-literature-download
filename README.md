# download_pdf

面向学术科研的 Python 文献 PDF 自动下载仓库。当前流程从 DOI 进入出版社官网，调用 `scansci-pdf browser-get` 下载正文 PDF，再由 `mymetal.academic` 完成元数据预检、期刊缩写、文件命名和完整性校验。

## 设计边界

- 本仓库维护下载编排脚本、使用说明、测试输入和本地回归工具。
- `scansci-pdf` 负责浏览器与出版社页面适配；除上游缺陷确实阻塞流程外，不在本仓库继续修改它。
- 新的通用文献函数统一放入 `mymetal/academic`，本仓库只调用，不复制实现。
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

Python 3.11 或更高版本。开发机上的两个依赖仓库为：

```text
F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf
F:/BaiduSyncdisk/version20240608/main_code_space/pjvasp_package
```

在隔离环境中安装：

```bash
python -m pip install -e "F:/BaiduSyncdisk/version20240608/main_code_space/pjvasp_package"
python -m pip install -e "F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf[cloakbrowser,fast]"
```

每位使用者需自行完成 CloakBrowser 初始化及出版社机构登录；不得提交 API key、cookie、浏览器 profile 或下载的论文。

## 使用

先运行不联网自检：

```bash
python publisher-official-pdf/scripts/pdf_download.py --selftest
```

批量下载：

```bash
python publisher-official-pdf/scripts/pdf_download.py \
  tests/fixtures/test-doi.txt \
  -o tests/artifacts/latest \
  --report
```

详细安装、初始化和故障排查见 [publisher-official-pdf/references/setup.md](publisher-official-pdf/references/setup.md)。

## 下载范围

默认只接受出版社官网正文 PDF，不用 API、聚合站、仓储或预印本替代正式期刊版本。下载成功仍需结合来源记录、标题或 DOI、PDF 头尾标和摘要校验，不能只按“文件存在”判断。
