---
name: publisher-official-pdf
description: Batch-download academic article PDFs from publisher official websites using DOI lists, a persistent CloakBrowser profile, and institutional access when available. Use for official-site-only retrieval; never substitute APIs, aggregators, repositories, preprints, Sci-Hub, or LibGen.
---

# 出版商官网 PDF 批量下载

## 边界

- 只调用 `scansci-pdf browser-get`，从 DOI 进入出版商官网并保存正文 PDF。
- 不调用 `scansci-pdf get`，不使用 Elsevier API、Unpaywall、OpenAlex、CORE、DOAJ、Sci-Hub、LibGen 或预印本替代。
- 不把补充材料、预印本、Snapshot、采访、旧缓存或其他目录中的文件计作期刊正文下载成功。
- 仅处理 `mymetal.academic.search.literature_download.JOURNAL_ABBREVIATIONS` 中有缩写的期刊；无匹配项直接报告并跳过。
- 不读取、复制或共享用户的机构密码、Cookie、CloakBrowser key 或浏览器 profile。

## 环境检查

先运行：

```powershell
scansci-pdf browser-status
python -m cloakbrowser info
python -c "from mymetal.academic.search.literature_download import generate_pdf_filename; print('mymetal ok')"
```

若 `scansci-pdf` 不存在、版本未包含提交 `530e944`，或 CloakBrowser 尚未安装，读取 [references/setup.md](references/setup.md) 并完成安装。免费 CloakBrowser 足够运行单会话；不要把购买 Pro 描述为提高验证码通过率。

## 先初始化，再自动下载

DOI 文件每行一个 DOI，可在空白后附备注；空行和 `#` 注释忽略。

```powershell
python <skill目录>\scripts\auto_pdf_download.py dois.txt -o pdfs --initialize --wait 600
python <skill目录>\scripts\auto_pdf_download.py dois.txt -o pdfs --skip-existing --retries 1
```

第一条命令只建立当前用户自己的 hCaptcha、机构 SSO/MFA 和访问确认状态，不保存 PDF；第二条才自动下载。脚本使用同一个持久 profile，默认等待 180 秒，并在同一浏览器会话内对失败项自动重试一次。

若要声明初始化状态可复用，必须用“同一出版商的另一篇 DOI”验证，不能只重复下载初始化时使用的同一篇文章。

成功必须同时满足：

- 本轮在指定目录生成对应 PDF；
- 文件以 `%PDF-` 开头，尾部存在 `%%EOF`，且大小合理；
- 元数据确认是受支持期刊的 `journal-article`，而非预印本或被排除的文章类型；
- 批次内 PDF 摘要唯一，避免上一标签页正文串到下一 DOI；
- 来源日志为 `Publisher(Browser)` 或用户明确同意后的 `Publisher(Browser-Manual)`。
- 最终文件名为 `年份-期刊缩写-标题前十个有效字符.pdf`；空格和标点转为连字符。

## 首次授权与失败处理

初始化阶段由用户本人处理：

```powershell
python <skill目录>\scripts\auto_pdf_download.py dois.txt -o pdfs --initialize --wait 600
```

- hCaptcha 图片识别；
- 首次机构 SSO、密码或 MFA；
- 出版商要求用户确认访问。

之后必须用同出版商的不同 DOI 自动回归，才能声称初始化状态可复用。自动阶段已经重试一次；仍失败时不要无限循环，补足权限或等待会话恢复后再提交。`--manual` 只作单篇下载兜底，不用于证明自动化。遇到明确无订阅权限时停止并报告，不尝试绕过付费墙。

## 报告口径

区分三种结论：

- `自动成功`：本轮无人操作完成；
- `初始化后自动成功`：曾由用户建立 hCaptcha/机构会话，随后无人操作回归成功；
- `失败`：验证码未放行、会话过期或机构无权限。

不得把“当前测试集成功”表述为所有出版商、所有时间、全新 profile 下的 100% 保证。
