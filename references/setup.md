# 安装与首次初始化

已在 Windows 10、Microsoft Edge 152、Python 3.14 上验证。

## 1. 安装依赖

```powershell
python -m pip install playwright websocket-client pypdf
```

就这三个。`scripts/` 下的模块全部只用标准库，**不需要**安装本仓库，也不依赖任何私有包。

`edge_download.py` 只用 Playwright 的 `connect_over_cdp` 去驱动**已经装好的 Edge**，
不需要 `playwright install` 下载浏览器二进制。

| 包 | 用在哪 |
|---|---|
| `playwright` | resolve 阶段驱动 Edge：过 Turnstile、点 cookie 弹窗、走机构登录、读候选链接 |
| `websocket-client` | 第 4 级取件的裸 CDP 客户端，以及最小化窗口、开后台标签页 |
| `pypdf` | 验收和落盘后的内容核对，抽前 3 页文本 |

## 2. 启动专用自动化 Edge

```powershell
powershell -NoProfile -File <skill目录>\scripts\start_edge.ps1
```

启动一个与日常浏览器完全隔离的 Edge，带 `--remote-debugging-port=9333` 和 `--no-proxy-server`。
本 skill 的所有本机状态都收在 `~/.pj/p-literature-download/` 下：

```text
~/.pj/p-literature-download/     # -data_dir，一个参数管住全部本机状态
├── profile/     # Edge 的 --user-data-dir，你的机构登录态在这里
└── download/    # 浏览器下载落地处
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `-port` | `9333` | CDP 调试端口 |
| `-data_dir` | `~\.pj\p-literature-download` | 本机状态根目录，下辖 `profile\` 与 `download\` |
启动器固定确保 `https://webvpn.zju.edu.cn/` 根页面存在；专用 Edge 已运行时复用进程和现有页面，不重写 live profile。

脚本会把 `<DataDir>\download` 写进 `<DataDir>\profile\Default\Preferences`，
**profile 是全新的也会创建**——
这一步跳过的话 Edge 会下到你真实的「下载」文件夹，而 `edge_download.py` 不看那里，
表现是 Elsevier 取不到、手动点的下载也认不到，且没有任何报错。
`edge_download.py` 启动时从同一个 Preferences 读回目录并打印，两边永远一致，
不需要在 Python 那边再写一遍。

不要用日常 Edge 通过 `edge://inspect` 临时开的调试端口：它的 `/json/*` 全部 404，
且第一个客户端断开后就不再完成 WebSocket 握手。

## 3. 机构访问与持久 profile

- 直连出版社仍是主路径；整篇失败后才从 ZJU WebVPN 首页搜索框进入同一官方页面；
- cookie 落在该 profile，之后自动复用；首次启动用系统凭据窗口采集本使用者账号与密码，
  以 Windows DPAPI 密文保存为 `profile/webvpn-credential.clixml`；会话失效时才解密填表；
  遇到「继续登录将踢掉其他已登录账号」自动点「继续」，无需人工；
- 换账号或密码运行 `start_edge.ps1 -initialize_credentials`；凭据不写源码、命令行、日志或报告；
- 验证：直连文章应出现「Access provided by 你的学校」；WebVPN 兜底结果的报告中
  `access_via` 应为 `webvpn.zju.edu.cn`；
- 不要把该 profile 复制给别人，它含 Cookie 与机构会话。每位使用者建立自己的 profile；
- 换学校要改 `scripts/edge_download.py` 顶部的 `INSTITUTION`；
- 遇到 hCaptcha 图片题时脚本过不了，由用户本人处理（`-human_wait N` 会把标签页弹到前台）。
  Cloudflare Turnstile 一律由脚本拟人化点击通过，不打扰用户。
- 跑批期间尽量不要在这个自动化 Edge 窗口里打开无关 PDF；接管路径会按 DOI/标题核验并忽略错篇，
  但无关标签页仍会增加扫描噪声。临时看文献用自己的日常 Edge。详见 SKILL.md 的「人工接管」小节。

## 4. 安装 skill

仓库根目录就是 skill 根目录，整个复制过去、改名成 `p-literature-download` 即可：

```powershell
Copy-Item -Recurse . "$env:USERPROFILE\.claude\skills\p-literature-download"
```

Codex 用 `$env:CODEX_HOME\skills`。重启会话后确认能被发现。

**不要用 `npx skills add ShengLin1001/p-literature-download`**：仓库根目录本身是 skill 时，
那个 CLI 只装 `SKILL.md`，`scripts/` 全丢，装完是空壳（实测确认）。

要在配置仓库里长期维护并接收上游更新，用 **git subtree**：

```bash
git subtree add  --prefix=skills-using/root/p-literature-download \
    git@github.com:ShengLin1001/p-literature-download.git main --squash
git subtree pull --prefix=skills-using/root/p-literature-download \
    git@github.com:ShengLin1001/p-literature-download.git main --squash   # 之后拉更新
```

不要用 submodule：它存的是指针不是文件，`npx skills add` 克隆配置仓库时不带
`--recurse-submodules`，拿到的是空目录。

本 skill **只允许显式调用**（`$p-literature-download`）：它会开浏览器、发真实网络请求、
动用机构会话，不该因为对话里出现 DOI 就自动触发。

## 5. 第一次运行

先跑离线自检，不联网、不开浏览器：

```powershell
python <skill目录>\scripts\edge_download.py -selftest
python <skill目录>\scripts\verify_pdf.py -selftest
```

再用自带的开放获取样例试真实下载。`examples/dois-sample.txt` 是六篇 OA 文献、
六家出版社，不需要机构订阅，装好之后应当 **6/6**：

```powershell
python <skill目录>\scripts\edge_download.py <skill目录>\examples\dois-sample.txt -output .\pdfs -preset human
python <skill目录>\scripts\verify_pdf.py .\pdfs -batch
```

`-preset human` = 失败重试 2 轮 + 验证码弹窗口等 120s + 跳过已有 + 自动写报告。
被 agent 调用时改用 `-preset agent`：不重试（agent 自己会重跑）、不弹验证码窗口。

拿不满 6/6 说明是环境问题（Edge 没起来、走了系统代理、依赖没装），不是权限问题。

完整回归用 `tests/fixtures/dois-regression.txt`（22 篇，覆盖全部出版社与四级取件路径，
含订阅内容，需要机构会话）。

DOI 文件格式：每行一个 DOI，可在空白后附备注；空行和 `#` 开头的行忽略。

元数据查不到、属于补充材料、文章类型被排除（SnapShot 等）或缺年份/标题时，
脚本在开浏览器**之前**就报告并跳过。DOI 本身指向预印本或期刊不在缩写表时仍会下载，
表外期刊的文件名标签从元数据自动生成。

## 6. 常见问题

| 现象 | 原因与处理 |
|---|---|
| 连不上 `127.0.0.1:9333`，或首篇成功后全是 `WinError 10061` | 没跑 `start_edge.ps1`，或 Edge 被关了（旧版启动器用 `&` 起 Edge，调用 shell 结束就带走 Edge；现用 `Start-Process`）。代码里**永远不要**对 CDP 连接调 `browser.close()`，那会拆掉 DevTools 服务端 |
| 挑战永远停在 `Request Verification: In Progress` | 走了系统代理。Cloudflare 判的是出口 IP，`start_edge.ps1` 已带 `--no-proxy-server` |
| 全部 `no_pdf_link (state paywall)` | 机构会话过期，去自动化 Edge 里重新登录一次 |
| `state captcha` | hCaptcha 图片题，脚本过不了。加 `-human_wait 120` 由用户点，或跳过 |
| 偶发一两篇失败 | Cloudflare 抖动或超时。`-preset human` 自带 2 轮重试；agent 调用时由 agent 自己重跑 |
| Elsevier 总是 `fetch_failed`，或手动点的下载没被认到 | 下载目录对不上。比对启动时打印的「浏览器下载目录」与 `edge://settings/downloads`，不一致就重跑一次 `start_edge.ps1` |
| PDF 在内置阅读器里打开、拿不到文件 | 正常。**不要**改 `always_open_pdf_externally`，它是受保护偏好，会在启动时被还原；四级取件不依赖它 |
| 下载到 Supplementary Materials | 候选过滤器应拦掉。新出版商的补充材料命名不同时，往 `publisher_pdf.SUPPLEMENT_PATTERN` 补 |
| 下到了参考文献里别人的 PDF | 同上，检查 `filter_pdf_candidates`；候选必须含本文 DOI 后缀或页面 URL 里的 PII，都不匹配才回退到同域 |
| 期刊不在缩写表 | 在 `scripts/literature_download.py` 的 `JOURNAL_ABBREVIATIONS` 补充确认后的通用缩写 |
| 某出版商改版后取不到 | 先看 `get_page_state` 和 `filter_pdf_candidates` 的输出，再决定加 host 规则还是加取件级别 |
