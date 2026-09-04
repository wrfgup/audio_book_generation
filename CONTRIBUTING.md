# 贡献指南

[English](CONTRIBUTING.en.md) | 简体中文

感谢你帮助改进 audiobook-generator。参与项目即表示你同意遵守
[行为准则](CODE_OF_CONDUCT.md)。安全问题请不要提交公开 Issue，请按
[安全政策](SECURITY.md)私密报告。

## 贡献前须知

- 只提交你有权公开的代码、文本和资源。
- 不得提交商业书籍正文、抓取页面、私人角色映射、真实音频、运行输出、
  个人路径、IP 地址、Cookie、令牌或 API Key。
- 示例和测试夹具必须是自创、短小、合成且不模仿真人的内容。
- 不接受绕过登录、付费墙、DRM、robots.txt 或访问限制的功能。
- 不接受内置第三方内容站点的专用搜索/抓取适配器。通用网页支持必须保持
  显式配置、域名白名单和安全默认值。

若不确定改动方向，请先提交简短 Issue 描述问题、预期行为和替代方案；但
不要在 Issue 中粘贴敏感信息或受版权保护的正文。

## 开发环境

```bash
python -m venv .venv
# 按 README 激活虚拟环境后：
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

项目支持 Python 3.10+。正式源码唯一位于 `src/audiobook_generator/`；不要
在仓库根目录另建可执行脚本作为第二套实现。开始工作前请阅读
[AGENTS.md](AGENTS.md) 的架构和安全约束。

## 建议工作方式

1. 从最新的干净 `main` 创建短期分支。
2. 将一个 Pull Request 限定为一个清晰问题。
3. 先写或更新离线测试，再实现最小改动。
4. 公共 CLI、JSON schema 或默认行为变化时，同步更新中英文文档与示例。
5. 提交前运行全部质量和发布前检查。

```bash
ruff check src tests scripts
ruff format --check src tests scripts
mypy src/audiobook_generator
pytest
python -m build
python -m twine check dist/*
python scripts/prepublish_check.py
pip-audit
detect-secrets scan --all-files
```

`pytest` 配置包含分支覆盖率，最低总覆盖率为 80%。新增行为应覆盖成功路径、
输入错误和安全边界，不能仅依赖总覆盖率数字。

## 测试规则

- 测试必须完全离线；使用 fake client、本地合成 HTML 和运行时生成的短 WAV。
- 禁止访问真实网站、OpenAI 或任何付费 API。
- 用保留域名（如 `example.org`）和合成文本，不使用真实服务端点或作品片段。
- 网络测试应覆盖 HTTPS、域名白名单、robots.txt、重定向重新校验、私网阻断、
  限速和响应体上限。
- 路径测试应覆盖绝对路径、`..`、符号链接逃逸、空文件和超大章节。
- 音频测试应覆盖兼容 WAV 的流式合并、格式不一致、损坏缓存和中断续跑。
- API 测试只断言经过脱敏的错误；日志和异常不得包含密钥或正文。

## 代码与接口约定

- Python 代码需要类型标注，并通过 Ruff 格式化与静态检查。
- 所有外部输入先校验再使用；错误信息要可操作，但不得回显秘密或输入正文。
- 公共 JSON 格式使用 `schema_version: 1`，未知字段和不安全路径应明确拒绝。
- v0.1 的音频边界固定为 WAV。不要悄悄添加未经验证的格式。
- OpenAI 调用使用官方 SDK。Responses 请求保持结构化输出和 `store=False`；
  TTS 输出先验证再原子落盘。
- 新依赖必须有明确必要性，并考虑安全、许可证、维护状态和 Python 版本支持。

## 文档与用户体验

面向用户的命令、错误、配置字段或安全约束发生变化时，同时更新
`README.md` 和 `README.en.md`。贡献流程变化时同步维护两份贡献指南。
示例必须可以复制执行，且默认路径不指向个人目录。

用户可见的音频流程必须保留 AI 合成语音披露，不得把预设音色描述成真人，
也不得加入模仿具体人物的默认指令。

## Pull Request 清单

PR 描述应说明：问题、方案、用户可见变化、风险、测试结果，以及是否改变
CLI/schema。提交前确认：

- [ ] 改动范围小且没有无关格式化或生成文件。
- [ ] 新行为有离线测试，全部检查通过。
- [ ] 没有秘密、私人路径、真实端点、商业正文或媒体文件。
- [ ] CLI/schema/默认值的变化已更新中英文文档和示例。
- [ ] 安全边界、费用确认、隐私和 AI 声音披露没有被削弱。
- [ ] `python scripts/prepublish_check.py` 通过。

维护者可能要求拆分过大的 PR。合并与发布由维护者决定；提交代码不保证立即
发布。

## 许可证

贡献被接受后，将按本项目的 [MIT License](LICENSE) 发布。提交贡献即表示你
有权按该许可证提供它。
