# audiobook-generator

[English](README.en.md) | 简体中文

一个本地优先、可断点续跑的多人有声书命令行工具。它把你有权使用的
UTF-8 文本或经明确配置的授权网页整理为标准书籍目录，并可调用 OpenAI
Responses API 识别说话人、调用 Speech API 生成 WAV 音频。

> [!IMPORTANT]
> 只处理你创作、已获授权或依法可以使用的内容。请勿抓取付费墙、受 DRM
> 保护或禁止自动访问的内容，也不要把商业作品正文、私人音频、API Key
> 或运行目录提交到仓库。

> [!NOTE]
> 生成的声音是 AI 合成声音，不是真人录音。发布或播放结果时，必须向听众
> 清楚披露这一点。OpenAI 的[文本转语音文档](https://developers.openai.com/api/docs/guides/text-to-speech)
> 也明确要求进行此类披露。

## 功能

- 本地导入单个 `.txt` 文件或包含 `.txt` 文件的目录。
- 根据中文等常见章节标题自动切分；没有章节标题时保留为单章。
- 使用站点配置抓取你获准访问的 HTTPS 网页，无内置站点搜索、登录、Cookie、
  付费墙或 DRM 绕过功能。
- 使用规则或 OpenAI Responses API 识别叙述与对白说话人。
- 通过 OpenAI Speech API 生成并合并 WAV；内容寻址缓存支持恢复中断的任务。
- 在发起付费请求前显示章节数、字符数、预计请求数和缓存命中数。
- 所有公开 JSON 数据格式均带有 `schema_version: 1` 并进行严格校验。

## 工作流程

```text
授权的本地文本 ── import-text ─┐
                                ├── 标准书籍目录 ── validate ── build ── WAV + manifest
授权的 HTTPS 网页 ── scrape ───┘
```

导入、校验和 `build --dry-run` 不需要 API Key。只有 `build` 的 LLM/TTS
阶段会把待处理文本发送到配置的 API 服务。

## 环境要求与安装

- Python 3.10 或更高版本
- 真正生成音频时，需要可用的 OpenAI API Key 和相应 API 访问权限

从源码安装：

```bash
python -m venv .venv
```

激活虚拟环境的命令取决于平台：

```bash
# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

激活后安装：

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

确认安装：

```bash
audiobook --version
python -m audiobook_generator --version
```

## 快速开始：导入本地文本

以下示例仅使用你自己的文本：

```bash
audiobook import-text ./my-book.txt --output ./work/book \
  --title "我的故事" --author "作者名"

audiobook validate --book ./work/book

audiobook build --input ./work/book --output ./work/audio --dry-run
```

`import-text` 也接受目录。目录中的 `.txt` 文件会按稳定顺序导入：

```bash
audiobook import-text ./my-chapters --output ./work/book
```

导入结果形如：

```text
work/book/
├── book.json
└── chapters/
    ├── 0001.txt
    └── 0002.txt
```

确认 dry-run 的统计与上限后，再配置 API 并生成音频：

```bash
# Linux / macOS
export OPENAI_API_KEY="example-api-key"

# Windows PowerShell
$env:OPENAI_API_KEY = "example-api-key"

audiobook build --input ./work/book --output ./work/audio
```

默认内置声音配置只使用 OpenAI 预设音色，不模仿具体真人。若要使用自己的
角色映射，请复制示例到仓库外并显式传入：

```bash
audiobook validate --voices ./local/voices.json
audiobook build --input ./work/book --output ./work/audio \
  --voices ./local/voices.json
```

## 抓取经授权网页

抓取是可选功能。入口 URL、域名白名单和 CSS 选择器必须全部写入站点配置；
CLI 不接受临时裸 URL，也不提供站点搜索：

```bash
cp configs/site.example.json ./local/site.json
# 编辑 ./local/site.json，只填写你有权抓取的站点。
audiobook validate --site-config ./local/site.json
audiobook scrape --site-config ./local/site.json --output ./work/book
```

抓取器只允许 HTTPS，并实施域名白名单、robots.txt、重定向重新校验、
私网/loopback 拒绝、响应体大小限制和至少 0.5 秒的请求间隔。它不会绕过
身份验证、Cookie 限制、付费墙或 DRM。站点许可和 robots.txt 并不等同于
内容版权授权；使用者仍须自行确认两者。

## 校验

`validate` 至少接收一个目标，也可以在一次调用中同时校验：

```bash
audiobook validate \
  --book ./work/book \
  --site-config ./local/site.json \
  --voices ./local/voices.json
```

标准书籍目录要求章节路径为 `chapters/` 下的相对 `.txt` 路径。校验会拒绝
绝对路径、`..`、符号链接越界、重复索引、空正文和超过 5 MiB 的单章。

### JSON 配置与数据格式

`book.json` 的最小结构如下；网页来源可在 `source` 和章节中增加经过清理的
`url`/`source_url`：

```json
{
  "schema_version": 1,
  "source": { "type": "local_text" },
  "book": { "title": "原创示例", "author": "示例作者" },
  "chapters": [
    { "index": 1, "title": "第一章", "file": "chapters/0001.txt" }
  ]
}
```

站点配置固定入口、白名单、选择器和请求节奏：

```json
{
  "schema_version": 1,
  "start_url": "https://example.org/my-authorized-book/",
  "allowed_domains": ["example.org"],
  "selectors": {
    "book_title": "h1",
    "chapter_links": ".chapters a",
    "chapter_content": "article",
    "author": ".author",
    "chapter_title": "h1"
  },
  "request_interval_seconds": 0.5,
  "user_agent": "audiobook-generator/0.1",
  "max_chapters": 20
}
```

voices 配置包含 `schema_version`、`narrator`、`male`、`female`，以及可选的
`default_dialogue` 与 `characters`。每个声音项由 `voice` 和不模仿真人的
`instructions` 组成。请从 `voices.example.json` 复制；所有 schema 都拒绝
未知字段，以便尽早发现拼写和版本错误。

## 构建选项

```text
audiobook build --input DIR --output DIR
                [--voices FILE]
                [--env-file FILE]
                [--chapters 1,3-5]
                [--speaker-mode auto|llm|rules]
                [--dry-run] [--yes] [--force]
                [--max-chapters N]
                [--max-tts-characters N]
```

- `--voices`：省略时使用包内无真人模仿的默认配置。
- `--env-file`：可选 dotenv 文件；已有环境变量优先。该文件只应保存在本地。
- `--chapters`：以 `1,3-5` 格式选择正整数章节索引。
- `--speaker-mode auto`：默认模式；可降级的 LLM 错误会给出警告并回退规则
  识别，认证和配置错误会立即失败。
- `--speaker-mode llm`：强制使用 LLM；错误不会静默回退。
- `--speaker-mode rules`：完全离线识别说话人，不产生 LLM 费用；TTS 生成仍
  需要 API。
- `--dry-run`：只校验和估算，不发送付费请求，也不需要 API Key。
- `--yes`：跳过交互确认。非交互环境必须显式使用；它不能绕过硬性章节数或
  字符数上限。
- `--force`：重新生成 TTS 缓存项和输出；仍保留安全和费用上限。
- `--max-chapters`、`--max-tts-characters`：设置本次任务的硬性费用护栏；
  默认分别为 100 章和 1,000,000 个字符。为避免误写的巨大章节范围耗尽
  内存，章节上限本身不得超过 10,000。

默认情况下，CLI 会在任何付费调用前显示计划并询问确认。模型价格和账户
限额会变化；请在运行前查看 OpenAI 当前的[模型与价格信息](https://developers.openai.com/api/docs/models)。

进程退出码为：`0` 成功，`2` 参数/配置/输入错误，`1` 网络/API/构建错误。
脚本应依赖退出码，不要解析可能本地化的错误文字。

## OpenAI 配置

推荐通过环境变量注入密钥，不要把真实值写入 `.env.example`、JSON、命令
历史或日志：

```env
OPENAI_API_KEY=example-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_LLM_MODEL=gpt-5.6-luna
```

- 默认 TTS 模型为 `gpt-4o-mini-tts`，通过 Speech API 输出 WAV。
- 默认说话人识别模型为 `gpt-5.6-luna`，通过 Responses API 使用严格 JSON
  Schema，并设置 `store=False`。
- v0.1 只接受和生成 WAV，不支持 MP3 等输出格式。
- 模型名可通过环境变量覆盖；可用性、费用和限额取决于你的账户。

### 自定义兼容端点的安全提醒

如果设置 `OPENAI_BASE_URL`，API Key 和需要处理的文本会发送到该端点。
只使用你完全信任的服务。自定义远程地址必须使用 HTTPS；HTTP 仅允许
loopback 开发地址。带用户名/密码、查询参数或 URL 片段的地址会被拒绝。

## 输出、缓存和恢复

构建输出包含章节 WAV、分段 WAV、章节 manifest 和全书 manifest。manifest
只记录相对 POSIX 路径、字符数、SHA-256、声音、缓存标识和
`ai_generated: true`，不保存分段原文、绝对路径或带查询参数的 URL。

LLM 与 TTS 缓存键包含输入内容、模型、音色、指令、速度和实现版本。相同
配置可复用已验证结果；配置或内容变化、缓存损坏时会重建。音频先写入临时
文件，验证为合法 WAV 后再原子替换目标文件，因此中断后通常可以安全重跑。

输出目录、缓存和 manifest 仍可能泄露书名、角色名、文本长度或工作习惯。
请把它们视为私人数据，不要提交或随仓库打包。

## 隐私、费用与内容责任

- 本地导入的数据不会因为执行 `import-text` 或 `validate` 自动上传。
- LLM 说话人识别和 TTS 会把相关文本发送到 OpenAI 或你配置的兼容端点。
- `store=False` 控制 Responses API 的响应存储选项，但不能替代阅读所选服务
  的数据处理条款和隐私政策。
- 缓存可以减少重复请求，但不能保证最终费用；以服务提供方账单为准。
- 不要使用预设音色冒充真人，不要声称生成结果是真人录制。
- 发布音频时，请明确标注“本音频包含 AI 合成语音”或等效提示。
- 你须负责文本、网页抓取、声音使用和生成音频在所在地的合法性。

## 故障排查

**`OPENAI_API_KEY` 缺失**

先使用 `--dry-run` 验证本地流程；真正构建前，在当前 shell 中设置环境变量。

**自定义端点被拒绝**

确认远程地址是 HTTPS，且不含 userinfo、查询参数或片段。私网地址和普通
HTTP 远程端点是有意禁止的。

**网页抓取失败**

先运行 `validate --site-config`，再检查站点是否允许自动访问、域名是否在
白名单、选择器是否匹配，以及重定向是否离开允许域名。工具不会帮助绕过
访问限制。

**WAV 无法合并或缓存反复重建**

分段 WAV 的声道数、采样宽度、采样率和压缩类型必须一致。损坏或不兼容的
缓存会被判定为不可复用；需要时可使用 `--force` 重建。

**非交互运行停止在确认前**

检查 dry-run 计划后显式传入 `--yes`，并设置合理的
`--max-chapters` 与 `--max-tts-characters`。

## 开发与贡献

安装开发依赖并运行检查：

```bash
python -m pip install -e ".[dev]"
ruff check src tests scripts
ruff format --check src tests scripts
mypy src/audiobook_generator
pytest
python scripts/prepublish_check.py
```

测试必须离线运行，不访问真实网站或 OpenAI，也不得包含受版权保护的正文。
详见[贡献指南](CONTRIBUTING.md)、[安全政策](SECURITY.md)和
[行为准则](CODE_OF_CONDUCT.md)。

## 发布仓库前的重要提醒

不要压缩、镜像或直接上传当前工作目录，也不要复制现有 `.git`。私人文本、
音频、运行数据和本机忽略规则可能仍留在本地。维护者必须从明确的公开文件
白名单创建独立候选目录，运行 `python scripts/prepublish_check.py`，并从该
候选目录初始化全新的 `main` 历史。完整步骤见
[维护者发布清单](docs/maintainer-release.md)。

## 安全与许可证

请勿在公开 Issue 中报告密钥泄露、SSRF、路径逃逸等漏洞；请使用 GitHub
Private Vulnerability Reporting，参见 [SECURITY.md](SECURITY.md)。

本项目采用 [MIT License](LICENSE)。
