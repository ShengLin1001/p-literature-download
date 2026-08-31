# AGENTS.md

## 项目目标

用 Python 从 DOI 自动获取学术文献 PDF。下载入口只走出版社官网，结果必须保留可核验的来源信息。

## 架构边界

- 本仓库：浏览器驱动与编排、CLI 包装、测试输入、手工回归脚本和使用文档。
- `mymetal/academic/search/publisher_pdf.py`：出版商站点知识（页面状态分类、PDF URL host 规则、
  候选过滤、注入的 JS）。与浏览器无关，可被任何驱动复用。
- `mymetal/academic/search/literature_download.py`：DOI 解析、Crossref 元数据、期刊缩写、
  文件命名、PDF 完整性。
- 新编写的通用文献函数一律放 `mymetal/academic`，不要在本仓库或 `scansci-pdf` 中复制同类实现。
- `scansci-pdf` / CloakBrowser：只作兜底，非主路径。非必要不修改。

## 修改规则

- AI 生成的分析、阶段、交接和汇总文档只能放入 `ai-guide/` 的对应子目录。
- 测试输入放 `tests/fixtures/`，手工测试脚本放 `tests/manual/`，生成产物放 `tests/artifacts/`。
- 不提交 PDF、浏览器 profile、cookie、密钥、登录信息、截图、缓存或运行日志。
- 默认 UTF-8；优先复用现有脚本和函数，保持改动最小。
- 下载正文只走出版社官网（CDP 驱动的专用 Edge），不得用 API、聚合站、仓储或预印本替代。

## 最小验证

```bash
python publisher-official-pdf/scripts/edge_download.py --selftest
```

修改 `mymetal/academic` 时，在 `pjvasp_package` 根目录直接运行：

```bash
python tests/test_literature.py
```

真实官网回归用 `verify_pdf.py <dir> --batch` 验收，结果与单元测试分开报告。
单个 DOI 记为 pass 当且仅当：本轮真实落盘 + `%PDF` 头 / `%%EOF` 尾 / 页数 > 0 +
DOI 或标题与 Crossref 匹配 + 非补充材料。进入登录页、点击成功、自检通过都不算。
