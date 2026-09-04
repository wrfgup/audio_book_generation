# 维护者发布清单 / Maintainer release checklist

本文用于公开 GitHub 仓库和发布包。它不是普通开发流程；每次发布都必须从
独立候选目录执行。

> [!CAUTION]
> 不要压缩、镜像、bundle 或直接上传当前工作目录，不要复制或复用现有
> `.git`，也不要假设 `.gitignore` 能从历史或压缩包中移除私人文件。

## 中文清单

### 1. 冻结与资产确认

- [ ] 冻结发布范围并确认版本号与 `CHANGELOG`/发布说明一致。
- [ ] 确认所有曾出现在本地配置中的真实密钥均已撤销或轮换。
- [ ] 确认任何曾裸露在配置中的服务端点已停用、鉴权或限制访问。
- [ ] 确认私人文本、音频、网页、角色映射、运行数据和本机排除规则继续留在
  本地，不在候选文件列表中。
- [ ] 确认示例仅使用原创合成文本、保留域名和非真人模仿音色。

### 2. 建立独立公开候选目录

- [ ] 在工作区之外创建一个新的空目录。
- [ ] 只按明确白名单复制源码包、测试、脚本、示例配置、项目元数据、文档和
  GitHub 社区文件；逐个类别确认，不使用“复制全部再删除”的方式。
- [ ] 不复制 `.git`、本机 `.git/info/exclude`、环境文件、运行输出、缓存、
  构建产物、原始网页或媒体。
- [ ] 在候选目录运行 `python scripts/prepublish_check.py`，解决每一项发现；
  不用排除规则掩盖无法解释的结果。
- [ ] 人工查看完整候选文件列表、每个 JSON/环境示例以及大文件列表。

候选目录通过检查后，才在其中创建新的公开历史：

```bash
git init -b main
git add --all
git status --short
git diff --cached --stat
```

在第一次提交前逐个检查 `git status` 列出的文件。严禁使用 mirror、bundle、
复制对象数据库或导入旧引用。第一次提交后，再检查：

```bash
git ls-files
git rev-list --objects --all
python scripts/prepublish_check.py
```

- [ ] `git ls-files` 与白名单完全一致。
- [ ] 全部历史对象均来自新的公开候选目录。
- [ ] 扫描结果中没有密钥形状、裸 IP、个人绝对路径、版权正文、媒体或异常
  大文件。

### 3. 质量与包验证

在候选目录的干净虚拟环境中运行：

```bash
python -m pip install -e ".[dev]"
ruff check src tests scripts
ruff format --check src tests scripts
mypy src/audiobook_generator
pytest
python -m build
python -m twine check dist/*
pip-audit
python -X utf8 -m detect_secrets scan --no-verify
python scripts/prepublish_check.py
```

密钥扫描默认只检查 Git 跟踪文件，强制 UTF-8 并禁用联网验证。不要在含私人
数据的工作区使用 `--all-files`；CI 仅在干净 checkout 中添加该参数以覆盖
打包元数据。必须审查输出 JSON 的每项结果，不能将退出码 0 视为无发现。

- [ ] CI 支持的 Python/平台矩阵全部通过。
- [ ] 分支覆盖率不低于 80%，测试过程无真实网络或付费 API 请求。
- [ ] sdist 和 wheel 只包含预期源码、默认配置、许可证和必要元数据。
- [ ] 在第二个隔离虚拟环境仅安装 wheel，确认 `audiobook --version` 与
  `python -m audiobook_generator --version` 可运行。
- [ ] 用原创小型 fixture 验证：无 API Key 时 `import-text`、`validate`、
  `build --dry-run` 成功。
- [ ] wheel 安装后默认 voices 可读取，且没有私人映射或真人模仿指令。

### 4. 文档与产品安全复核

- [ ] 中英文 README 与实际 `--help` 一致，四个命令及全部 build flags 均有
  准确说明。
- [ ] 自定义 `OPENAI_BASE_URL` 的凭据/正文传输风险清楚可见。
- [ ] 费用确认、硬性上限、隐私边界、WAV-only 和 AI 合成声音披露没有被省略。
- [ ] 抓取文档不暗示可绕过访问控制，示例站点为保留域名。
- [ ] manifest 不含正文、绝对路径或带查询参数 URL，并标记
  `ai_generated: true`。
- [ ] LICENSE 年份、项目元数据和版本号一致。

### 5. GitHub 仓库设置

首次推送新的 `main` 后，在接受外部贡献前：

- [ ] 启用 **Private Vulnerability Reporting**，确认 Security 页面出现
  **Report a vulnerability**。
- [ ] 为 `main` 启用分支保护：要求 CI、禁止强推和删除，并按维护团队规模
  设置审批要求。
- [ ] 启用 secret scanning、Dependabot alerts 和依赖更新。
- [ ] 检查 Actions 的默认 token 权限为只读；只给具体 job 增加必要权限。
- [ ] 创建 Issue/PR 模板，确认 `SECURITY.md`、`CODE_OF_CONDUCT.md` 和
  `CONTRIBUTING.md` 被 GitHub Community profile 识别。
- [ ] 远端只接收这份新历史；不要把旧引用、隐藏分支或标签推送过去。

### 6. 发布与发布后检查

- [ ] 从经过验证的 `main` 提交创建签名标签和 GitHub Release。
- [ ] 发布说明列出 CLI/schema 变化、升级注意事项、安全影响和 AI 声音披露。
- [ ] 若发布到包索引，只上传本次验证的 `dist/` 文件并核对哈希。
- [ ] 从公开地址重新安装一次，执行版本、导入、校验和 dry-run 冒烟测试。
- [ ] 查看公开仓库文件和提交历史，确认没有意外私人数据。
- [ ] 若发现秘密或私人内容，立即撤销凭据、限制访问、停止发布，并按事件响应
  处理；仅删除最新提交不足以清除 Git 历史。

## English checklist

### 1. Freeze and inventory

- [ ] Freeze scope and confirm the version matches release notes.
- [ ] Revoke or rotate every real credential that ever appeared in a local
  configuration; secure or retire exposed service endpoints.
- [ ] Confirm private books, audio, HTML, role maps, runs, caches, and local
  exclusions are absent from the candidate list.
- [ ] Keep examples original and synthetic, with reserved domains and no
  real-person imitation.

### 2. Create a separate public candidate

- [ ] Create a new empty directory outside the workspace.
- [ ] Copy only explicitly allowlisted package source, tests, scripts, example
  configuration, metadata, documentation, and community files. Never copy
  everything and then try to subtract private data.
- [ ] Do not copy `.git`, environment files, `.git/info/exclude`, runs, caches,
  build output, raw pages, or media.
- [ ] Run `python scripts/prepublish_check.py`, review every candidate file and
  large-file result manually, and resolve rather than suppress unexplained
  findings.
- [ ] Initialize a new `main` history in the candidate only. Never mirror,
  bundle, import old refs, or copy the object database.
- [ ] Before and after the first commit, inspect `git status`, `git ls-files`,
  and `git rev-list --objects --all`; rerun the pre-publication check.

### 3. Verify quality and artifacts

- [ ] Run Ruff, formatting check, mypy, pytest with at least 80% branch
  coverage, build, Twine check, `pip-audit`, `detect-secrets`, and the
  pre-publication check.
- [ ] Use `python -X utf8 -m detect_secrets scan --no-verify` to scan Git-tracked
  files with UTF-8 and no online verification. Never use `--all-files` in a
  workspace containing private data; CI adds it only in a clean checkout to
  cover package metadata. Review every JSON result; exit code 0 does not mean
  there are no findings.
- [ ] Confirm tests make no live network or paid API calls.
- [ ] Inspect sdist and wheel contents. Install only the wheel in a second
  clean environment and run both version entry points.
- [ ] Without an API key, run `import-text`, `validate`, and `build --dry-run`
  against a small original fixture.
- [ ] Confirm the installed default voice configuration contains no private
  mapping or real-person imitation.

### 4. Review docs and safety behavior

- [ ] Both READMEs match `--help`, including all four commands and build flags.
- [ ] The compatible-endpoint credential/text warning, paid-call confirmation,
  hard limits, privacy boundary, WAV-only contract, and AI-voice disclosure
  remain prominent.
- [ ] Scraping guidance never suggests bypassing controls, and all example
  hosts are reserved domains.
- [ ] Manifests omit source text, absolute paths, and URL queries, and retain
  `ai_generated: true`.

### 5. Configure GitHub

- [ ] Enable Private Vulnerability Reporting before accepting reports.
- [ ] Protect `main`, require CI, and disallow force-push and deletion.
- [ ] Enable secret scanning, Dependabot alerts, and dependency updates.
- [ ] Keep the default Actions token read-only and grant only job-specific
  permissions.
- [ ] Verify GitHub recognizes the contribution, conduct, and security files.
- [ ] Push only the new public history, never old branches, refs, or tags.

### 6. Release and verify

- [ ] Tag the verified `main`, publish release notes, and upload only the
  artifacts already checked.
- [ ] Install again from the public location and run version, import,
  validation, and dry-run smoke tests.
- [ ] Inspect the public file list and history once more.
- [ ] If a secret or private artifact appears, revoke credentials, restrict
  access, stop the release, and perform incident response. Deleting the latest
  commit alone does not remove data from Git history.
