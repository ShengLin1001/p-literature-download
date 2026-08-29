# 出版商官网自动下载文献 PDF：修订汇总报告

日期：2026-08-26
状态：本地代码已修复并通过本次相关单元测试；尚未提交、推送，也尚未重新执行整批官网浏览器回归。

## 一、修订结论

此前“可访问测试集 21/21 均为出版社官网正文”的结论撤回。旧批次虽然 21 个文件都具有 PDF 头尾标且摘要唯一，但这些条件只能证明文件完整、彼此不同，不能证明内容是目标期刊正文。

已确认的误收如下：

| DOI / 文件 | 实际内容 | 新流程处置 |
|---|---|---|
| `10.1063/5.0316442` / `5.0316442.pdf` | 27 页 Supplementary Materials | 检测首页“Supplementary Materials/Information”，拒绝并删除候选 |
| `10.1101/2020.03.22.20041079` / `2020.03.22.20041079.pdf` | medRxiv 预印本 | DOI 元数据预检和预印本域名检查均会跳过 |
| `10.48550/arXiv.1706.03762` / `arXiv.1706.03762.pdf` | arXiv 预印本 | 跳过，不作为期刊官网下载成功 |
| `10.1016/j.cell.2016.03.044` / `j.cell.2016.03.044.pdf` | Cell 官方 `SnapShot` | 虽来自官网，仍按非目标文章类型跳过 |
| `10.1145/3806644` / `3806644.pdf` | ACM Turing Interview | 期刊不在缩写表，按当前规则跳过 |

因此，旧表中的“21/21”不能继续使用。新的严格成功数必须在修复版完成整批浏览器回归后重新统计。

## 二、初始化与复用

人工初始化应放在自动下载之前，且只建立当前用户自己的持久浏览器状态，不保存 PDF：

```powershell
python publisher-official-pdf\scripts\auto_pdf_download.py dois.txt -o pdfs --initialize --wait 600
```

用户可在该阶段完成：

- hCaptcha 图片识别；
- 首次机构 SSO、密码或 MFA；
- 出版商要求的访问确认。

初始化是否可复用，必须用同一出版商的另一篇 DOI 做无人操作下载验证。重复下载初始化时的同一篇文章，只能证明该文章可再次访问，不能证明其他文章也能复用授权状态。不同出版商、不同认证域或会话过期后仍可能需要重新初始化。

## 三、自动重试

自动下载默认在同一个 CloakBrowser 上下文内对失败项重试 1 次：

```powershell
python publisher-official-pdf\scripts\auto_pdf_download.py dois.txt -o pdfs --skip-existing --retries 1
```

这样可利用首次访问建立的 Cookie、SSO 和挑战状态，也能覆盖临时页面超时。预印本等明确不合格项不重试。重试后仍失败才报告，不需要先由用户重新提交一遍脚本；不做无限循环，以免反复触发风控。

## 四、元数据预检与文件命名

可复用逻辑已集中到 `mymetal/academic/search/literature_download.py`：

- DOI 规范化和列表解析；
- Crossref 元数据获取（只用于验证与命名，不用于下载 PDF）；
- 通用期刊缩写索引 `JOURNAL_ABBREVIATIONS`；
- 期刊论文类型、年份、标题和排除类型检查；
- PDF 完整性检查；
- 最终文件名生成。

命名格式为：

```text
年份-期刊缩写-标题前十个有效字符.pdf
```

字母、数字和汉字计入十个字符，空格和标点只作为分隔并转为连字符。例如：

```text
2013-PRB-Effect-of-st.pdf
```

若期刊不在通用缩写表中，脚本不会猜缩写，而是报告 `journal abbreviation missing` 并跳过。确认规范缩写后，只需在 mymetal 的一张表中补充。

## 五、修复后的下载判定

下载成功必须同时满足：

1. Crossref 元数据为受支持期刊的 `journal-article`；
2. DOI 进入出版商官网，不能落到 arXiv、medRxiv 等预印本平台；
3. PDF 来自当前官网浏览器会话；
4. 文件以 `%PDF-` 开头、尾部有 `%%EOF` 且大小合理；
5. 首页内容不是 Supplementary Materials/Information；
6. 批次内摘要唯一，避免前一标签页串到后一 DOI；
7. 最终按 mymetal 规则命名。

`SnapShot`、采访等不属于本任务所需的常规期刊正文，即使确实从出版社官网获得，也不会计入成功。

## 六、代码位置

- `pjvasp_package/mymetal/academic/search/literature_download.py`：共享元数据、缩写、命名和完整性函数；
- `pjvasp_package/tests/test_literature.py`：共享函数测试；
- `scansci-pdf/src/scansci_pdf/pdf_utils.py`：补充材料内容识别；
- `scansci-pdf/src/scansci_pdf/sources/browser_direct.py`：预印本拦截、候选 PDF 内容检查、同会话重试、初始化；
- `scansci-pdf/src/scansci_pdf/main.py`：`--initialize` 与 `--retries` 命令行入口；
- `publisher-official-pdf/scripts/pdf_download.py`：调用 mymetal 预检并执行最终命名。

## 七、仍需现场完成的验收

代码单元测试不能替代真实官网回归。下一次整批验收应使用隔离输出目录，并分别记录：

- 全新 profile 的自动结果；
- 用户初始化后的结果；
- 用不同 DOI 验证同出版商授权是否复用；
- 每个最终 PDF 的来源日志、内容类型、头尾标和 SHA-256；
- 被跳过的预印本、非目标文章类型与未知期刊。

在完成该回归前，不再报告新的“全部成功”比例。
