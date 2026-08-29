# 安装与首次初始化

本流程已在 Windows AMD64、Python 3.14.5、CloakBrowser wrapper 0.5.9、Chromium v151 上验证。`scansci-pdf` 要求 Python 3.11 或更高版本。

## 1. 安装 mymetal 与 scansci-pdf

在 PowerShell 中运行；虚拟环境目录可自行调整：

```powershell
git clone https://github.com/ShengLin1001/scansci-pdf.git
Set-Location scansci-pdf
py -3.11 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e "F:\BaiduSyncdisk\version20240608\main_code_space\pjvasp_package" --no-deps
python -m pip install -e ".[cloakbrowser,fast]"
```

`mymetal.academic.search.literature_download` 提供 DOI 元数据预检、通用期刊缩写表、统一文件名和 PDF 完整性检查。当前修复尚未提交远程仓库时，应直接从本机修改后的两个工作树安装；提交后再改用对应 commit。升级时先用自己的 DOI 集重新回归。

## 2. 初始化 CloakBrowser

```powershell
python -m cloakbrowser login
python -m cloakbrowser info
scansci-pdf browser-status
```

每位使用者都应通过自己的 GitHub 登录获得免费 key。不要共享 key。首次启动会下载匹配平台的浏览器二进制。

`Version ... (pro)` 表示使用最新版编译通道，不等于购买了付费会员。CloakBrowser 官网说明免费与付费运行同一最新版，免费限制为一个并发会话；Pro 主要增加并发数和支持：

- https://cloakbrowser.dev/
- https://github.com/CloakHQ/CloakBrowser/blob/main/README.md
- https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md

官方明确说明不内置 CAPTCHA 解题服务或代理轮换，因此会员不能保证通过 Cloudflare/hCaptcha。

## 3. 安装 skill

把整个 `publisher-official-pdf` 目录复制到同学所用 agent 的 skill 根目录，例如：

```powershell
Copy-Item -Recurse .\publisher-official-pdf "$env:USERPROFILE\.agents\skills\publisher-official-pdf"
```

若该 Codex 安装使用 `$env:CODEX_HOME\skills`，则复制到对应位置。重启或新建 agent 会话后，确认 `$publisher-official-pdf` 能被发现。

## 4. 机构访问与持久 profile

- 保持校园网、学校 VPN 或 ZJU Connect 正常连接。
- 首次遇到学校 SSO、密码、MFA 或 hCaptcha 图片题时，由用户本人处理。
- 浏览器状态默认保存在 `%USERPROFILE%\.scansci-pdf\cache\official-browser-profile`。
- 不要把该 profile 复制给其他人；它可能包含 Cookie、机构会话和个人数据。
- 每位同学必须建立自己的 profile 和机构授权。

## 5. 第一次运行

准备 `dois.txt`：

```text
10.1038/nature12373
10.1103/PhysRevB.88.064104
10.1016/j.commatsci.2018.12.013
```

先初始化当前用户自己的持久会话：

```powershell
python <skill目录>\scripts\auto_pdf_download.py .\dois.txt -o .\pdfs --initialize --wait 600
```

再执行自动下载；失败项会在同一个浏览器会话内自动重试一次：

```powershell
python <skill目录>\scripts\auto_pdf_download.py .\dois.txt -o .\pdfs --skip-existing --retries 1
```

是否可复用必须用同一出版商的另一篇 DOI 验证，不能重复下载初始化用的原 DOI。元数据不是期刊论文、文章类型被排除或期刊不在缩写表时，脚本会直接跳过。

## 6. 常见问题

| 现象 | 原因与处理 |
|---|---|
| `Sessions: 1/1 in use`，但本地无浏览器 | 异常中止后的服务端租约尚未释放；等待约 10 分钟，不要反复启动 |
| Turnstile 已点击但仍超时 | Cloudflare 风险评分具有波动；保持同一网络/profile，自动重试一次 |
| 出现 hCaptcha 图片题 | 当前流程不自动识图；由用户本人完成首次初始化 |
| `Security verification` 出现在 View PDF 后 | 提交 `530e944` 已支持自动识别并点击第二道 Turnstile |
| 官网显示无访问权限 | 连接学校网络并检查机构订阅；无订阅则停止，不绕过付费墙 |
| PDF 重复或不完整 | 不应保留；脚本会检查 PDF 尾标与批内摘要唯一性 |
| 下载到 Supplementary Materials | 内容校验会拒绝并删除该候选，随后在本会话重试 |
| 期刊不在缩写表 | 在 `mymetal/academic/search/literature_download.py` 补充确认后的通用缩写；未补前跳过 |
