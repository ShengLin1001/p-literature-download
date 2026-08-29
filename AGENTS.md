# AGENTS.md

## 项目目标

用 Python 从 DOI 自动获取学术文献 PDF。下载入口只走出版社官网，结果必须保留可核验的来源信息。

## 架构边界

- 本仓库：下载编排、CLI 包装、测试输入、手工回归脚本和使用文档。
- `scansci-pdf`：浏览器下载底座。非必要不修改；若确认是上游缺陷，单独修复并运行其相关单元测试。
- `mymetal/academic`：新编写的通用文献函数。不要在本仓库或 `scansci-pdf` 中复制同类实现。

## 修改规则

- AI 生成的分析、阶段、交接和汇总文档只能放入 `ai-guide/` 的对应子目录。
- 测试输入放 `tests/fixtures/`，手工测试脚本放 `tests/manual/`，生成产物放 `tests/artifacts/`。
- 不提交 PDF、浏览器 profile、cookie、密钥、登录信息、截图、缓存或运行日志。
- 默认 UTF-8；优先复用现有脚本和函数，保持改动最小。
- 下载正文只调用 `scansci-pdf browser-get`，不得用聚合站、仓储或预印本替代。

## 最小验证

```bash
python publisher-official-pdf/scripts/pdf_download.py --selftest
python publisher-official-pdf/scripts/auto_pdf_download.py --selftest
```

修改 `mymetal/academic` 时，在 `pjvasp_package` 根目录直接运行：

```bash
python tests/test_literature.py
```

修改 `scansci-pdf` 时，只运行与改动相关的包内测试；真实官网回归与单元测试结果分开报告。
