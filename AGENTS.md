# AGENTS.md

## 项目目标

用 Python 从 DOI 自动获取学术文献 PDF。下载入口只走出版社官网，结果必须保留可核验的来源信息。

## 这个仓库是什么

仓库根目录**就是** skill 根目录（`SKILL.md` 在根）。这样 codex-config 之类的
配置仓库可以直接把它作为 git submodule 挂进 `skills-using/root/p-literature-download`，
上游一改，下游 `git submodule update --remote` 就能拉到。

所以：不要在根目录上面再套一层 skill 子目录，也不要把 `SKILL.md` 挪走。

## 架构边界

- `scripts/` 下的四个 Python 文件**必须自包含**，只依赖标准库 + `playwright`、
  `websocket-client`、`pypdf`。不要 import 本仓库之外的私有包（`mymetal`、
  `scansci-pdf` 等），别人不一定装得上。
  - `edge_download.py` —— 浏览器驱动与编排、CLI；
  - `verify_pdf.py` —— 验收；
  - `literature_download.py` —— DOI 解析、Crossref、期刊缩写、命名、PDF 完整性；
  - `publisher_pdf.py` —— 出版商站点知识，与浏览器无关。
- `literature_download.py` 和 `publisher_pdf.py` 是从 `pjvasp_package/mymetal/academic/search/`
  复制过来的。**上游那份保持原样，不要改动。** 两边如果都要改，先改这里，
  确认后再由人工决定是否回灌上游。
- 下载正文只走出版社官网（CDP 驱动的专用 Edge），不得用 API、聚合站、仓储或预印本替代。

## 修改规则

- AI 生成的分析、阶段、交接和汇总文档只能放入 `ai-guide/`，该目录已 gitignore，不进仓库。
- 测试输入放 `tests/fixtures/`，对外试跑样例放 `examples/`，生成产物放 `tests/artifacts/`（已 gitignore）。
- 不提交 PDF、浏览器 profile、cookie、密钥、登录信息、截图、缓存或运行日志。
- 本机状态一律收在一个 data dir 下（默认 `~/.pj/p-literature-download`）：`profile/` 放
  登录态，`download/` 放下载，`journal_abbreviations.json` 缓存期刊缩写（文件名稳定性靠它，别删）。Python 侧和 PowerShell 侧都叫 `-data_dir`，
  只此一个旋钮；不要再加第二个路径参数，也不要往用户家目录里散落其他目录。
- 默认 UTF-8；优先复用现有脚本和函数，保持改动最小。
- 本 skill 只允许显式调用。改 `SKILL.md` 的 frontmatter `description` 或
  `agents/openai.yaml` 的 `policy.allow_implicit_invocation` 时，必须保持这一点。

## 最小验证

改任意 `scripts/*.py` 之后跑离线自检（不联网、不开浏览器）：

```bash
python scripts/edge_download.py -selftest
python scripts/verify_pdf.py -selftest
```

真实官网回归用 `examples/dois-sample.txt`（全开放获取，应当满分）或
`tests/fixtures/dois-regression.txt`（22 篇全出版社矩阵，需机构会话），
再用 `verify_pdf.py <dir> -batch` 验收；结果与自检分开报告。

单个 DOI 记为 pass 当且仅当：本轮真实落盘 + `%PDF` 头 / `%%EOF` 尾 / 页数 > 0 +
DOI 或标题与 Crossref 匹配 + 非补充材料。进入登录页、点击成功、自检通过都不算。
