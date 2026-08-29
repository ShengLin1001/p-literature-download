# 学术论文 PDF 自动化下载社区调研报告

日期：2026-08-28
基于 web_search 调研结果和社区工具分析

## 一、开源工具生态

### 1.1 批量下载工具

| 工具 | 语言 | 方式 | 特点 |
|---|---|---|---|
| **PyPaperBot** (ferru97) | Python | Sci-Hub + Google Scholar | 支持 DOI 列表/查询/Scholar 链接，生成 BibTeX |
| **paper2pdf** | Python | arXiv 批量 | 专注 arXiv，不适合出版商官网 |
| **arXiv-bulk-download-tool** (RytisKumpa) | Python | arXiv API | 批量 arXiv 下载 |
| **scidown** (booksloth) | Python | Sci-Hub + LibGen | 简单 CLI |
| **scholar.py** | Python | Google Scholar | 学术搜索+引用，非直接下载 |

### 1.2 浏览器自动化方案

| 方案 | 底层 | 反检测能力 | 适用场景 |
|---|---|---|---|
| **CloakBrowser** | Playwright | 内置 stealth + humanize（overshoot/wobble/burst-pause/mistype） | 当前项目使用 |
| **Patchright** | Playwright fork | 补丁 Playwright 的自动化痕迹 | 替代 Playwright |
| **Camoufox** | Firefox + Playwright | 反指纹（Canvas/WebGL/Audio 伪造） | Firefox 路线 |
| **undetected-chromedriver** | Selenium | 补丁 ChromeDriver | Selenium 生态 |
| **nodriver** | CDP 直连 | 无 webdriver 标记 | 轻量级 |
| **selenium-stealth** | Selenium | stealth 插件 | 补充方案 |
| **Botright** | Playwright | 内置 captcha solver | 需要解验证码时 |

## 二、学术界合法来源

### 2.1 开放获取（OA）API

| 来源 | API | 是否合法 | 特点 |
|---|---|---|---|
| **Unpaywall** | `api.unpaywall.org/v2/{doi}?email=...` | ✅ 合法 | 查找 DOI 的 OA 版本，返回 best_oa_location |
| **OpenAlex** | `api.openalex.org/works/doi:{doi}` | ✅ 合法 | 元数据+OA 信息+引用网络 |
| **CORE** | `api.core.ac.uk/v3/search` | ✅ 合法 | 开放获取论文聚合 |
| **DOAJ** | `doaj.org/api/v2/articles` | ✅ 合法 | 纯 OA 期刊 |
| **Crossref** | `api.crossref.org/works/{doi}` | ✅ 合法 | 元数据（当前已使用） |
| **Elsevier API** | `api.elsevier.com` | ✅ 合法（需 key） | ScienceDirect 全文，需机构订阅 |
| **OpenAIRE** | `api.openaire.eu` | ✅ 合法 | EU 资助论文 |

### 2.2 机构访问

| 方式 | 描述 | 当前项目支持 |
|---|---|---|
| **校园网/VPN** | 直接 IP 认证 | ✅ |
| **WebVPN** | AES-CFB URL 加密代理 | ✅ (instsci) |
| **CARSI/Shibboleth** | 联邦认证 | ✅ (carsi) |
| **EZproxy** | 反向代理 | ✅ |
| **OpenAthens** | 联邦认证 | 部分 |
| **ZJU Connect** | SOCKS5 校园连接器 | ✅ (EasyConnect/aTrust) |

## 三、反风控技术

### 3.1 Cloudflare Turnstile

Turnstile 有三种模式：
1. **Non-interactive**：无交互，仅基于浏览器指纹评估
2. **Invisible**：无可见挑战，但可能需要 mouse movement
3. **Managed**：可能显示复选框，需要点击

**关键发现**（来自 kameleo 文章）：
- Turnstile 评估浏览器指纹的可信度
- 一旦判定可信，自动放行
- 纯点击 Turnstile 复选框的成功率取决于指纹评分，不是点击本身
- **persistent profile 复用是关键**：同一 profile 清除 Turnstile 后，后续访问通常自动放行

### 3.2 浏览器指纹检测

| 检测项 | 说明 | CloakBrowser 应对 |
|---|---|---|
| `navigator.webdriver` | Selenium/Playwright 标记 | 已 patch |
| Canvas fingerprint | Canvas 渲染指纹 | stealth_args 覆盖 |
| WebGL fingerprint | GPU 信息 | stealth_args 覆盖 |
| Audio fingerprint | 音频处理特征 | stealth_args 覆盖 |
| `navigator.plugins` | 插件列表 | 已 patch |
| `navigator.languages` | 语言列表 | 可配置 |
| `--disable-blink-features=AutomationControlled` | Chrome 自动化标记 | **本次已添加** |

### 3.3 人类行为模拟

| 技术 | 当前实现 | 改进 |
|---|---|---|
| **鼠标轨迹** | smoothstep + sine bend | ✅ 已增加过冲+抖动+随机方向 |
| **贝塞尔曲线** | 未使用 | CloakBrowser humanize 内置 |
| **随机延迟** | 固定 3s | ✅ 已改为 jittered 2.5-4.0s |
| **页面停留** | 无 | ✅ 已增加等待时滚动 |
| **滚动行为** | 无 | ✅ 已增加每 15-25s 随机滚动 |
| **trusted click** | 使用 `mouse.down/up` | ✅ 保持（trusted event） |
| **event.isTrusted** | 不适用（用 CDP 鼠标） | CloakBrowser 已处理 |
| **overshoot** | 无 | ✅ 已增加 40% 概率过冲 |
| **post-click drift** | 无 | ✅ 已增加点击后漂移 |
| **burst-pause** | 无 | CloakBrowser HumanConfig 内置 |

## 四、对当前项目的改进建议

### 高优先级（已实施）
1. ✅ **修复导入路径**：`mymetal.universal.literature` → `mymetal.academic.search.literature_download`
2. ✅ **增强鼠标轨迹**：过冲、抖动、随机方向、post-click drift
3. ✅ **Jittered 等待间隔**：消除固定间隔的机器人特征
4. ✅ **等待时人类行为**：随机滚动和鼠标移动
5. ✅ **补充出版商规则**：AIP/IOP/MDPI/PLOS/Frontiers/BMC/Annual Reviews/ACM
6. ✅ **增强补充材料检测**：AIP/Elsevier/RSC/Wiley/Nature SI 模式
7. ✅ `--disable-blink-features=AutomationControlled`
8. ✅ `human_preset="careful"`

### 中优先级（建议后续）
1. **利用 `page.click(selector)`**：当 `humanize=True` 时 CloakBrowser 已 patch `page.click()`，使用它可以自动获得完整的 HumanConfig 行为（overshoot/wobble/burst-pause/mistype），而不需要手动 `mouse.move/down/up`
2. **添加 Unpaywall 作为 OA 预检**：在 browser-get 之前先查 Unpaywall，如果论文是 OA 的，直接下载不需要过 Cloudflare
3. **persistent profile 优化**：确保 profile 目录不在临时位置，CloakBrowser 的 `official-browser-profile` 应持久化
4. **距离自适应步数**：鼠标移动距离越远步数越多，当前 32-48 步不随距离变化

### 低优先级
1. **多 profile 轮换**：免费版只有 1 并发，但可以在不同 profile 间轮换以降低单个 profile 的请求频率
2. **请求间隔**：在 DOI 之间添加随机 5-15s 间隔，降低速率限制风险
3. **代理轮换**：如果使用代理，定期轮换出口 IP
4. **Camoufox 备选**：如果 CloakBrowser 无法过某些出版商的 Turnstile，可以尝试 Firefox 路线（Camoufox）
5. **Botright captcha solver**：如果遇到 hCaptcha 图片题，可考虑集成第三方解题（但用户明确反对共享凭据）

## 五、结论

当前项目基于 CloakBrowser + scansci-pdf 的方案是社区中较先进的方案。主要瓶颈不是代码逻辑，而是：
1. 免费版 CloakBrowser 1 并发限制
2. Cloudflare 风险评分的波动性
3. 部分出版商的机构订阅权限

本次修复已解决了导入路径断裂（阻塞性 bug），并显著增强了模拟人类行为的能力。后续最关键的改进是利用 CloakBrowser 内置的 `page.click()` 方法（而非直接操作 `page.mouse`），以及添加 Unpaywall OA 预检以减少需要过 Cloudflare 的下载次数。
