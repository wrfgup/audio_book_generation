# 安全政策 / Security Policy

## 中文

### 支持版本

| 版本 | 是否接收安全修复 |
| --- | --- |
| 当前 `main` 与最新的 `0.1.x` | 是 |
| 更早版本或其他未发布快照 | 否 |

项目尚未发布稳定版时，仅维护当前 `main` 和最新发布版本。安全修复可能要求
升级到最新补丁版本。

### 私密报告漏洞

请勿为安全问题创建公开 Issue、Discussion 或 Pull Request，也不要把利用代码、
密钥、私人文本或日志粘贴到公共位置。

请在 GitHub 仓库的 **Security** 页面选择 **Report a vulnerability**，使用
GitHub Private Vulnerability Reporting 提交报告。如果该入口不可见，说明仓库
维护者尚未启用它；请不要公开细节，先通过维护者 GitHub 个人资料中列出的
私密联系方式提醒维护者启用该功能。

报告请尽量包含：

- 受影响版本、提交或组件；
- 不含真实秘密或版权正文的最小复现；
- 预期行为、实际影响和利用前提；
- 你已经尝试的缓解方法；
- 是否已经在其他地方披露。

特别欢迎报告密钥或正文泄露、日志脱敏失败、SSRF/DNS rebinding、恶意重定向、
路径穿越或符号链接逃逸、缓存投毒、任意文件覆盖、费用护栏绕过和依赖供应链
问题。

如果你发现真实凭据已经泄露，请先由凭据所有者立即撤销或轮换；不要等待
项目修复，也不要在报告中重复完整凭据。只提供经过遮盖的标识和必要上下文。

维护者会在能力范围内尽快确认报告、评估影响并通过同一私密线程沟通修复与
披露时间。请在修复发布或双方约定日期之前保持细节私密。项目是志愿维护，
不承诺固定响应时限或漏洞赏金。

### 安全研究边界

仅对你拥有或明确获准测试的系统和数据进行研究。不要：

- 请求真实 OpenAI 或第三方 API、产生费用或影响服务可用性；
- 抓取真实受版权保护内容、绕过认证/付费墙/DRM，或访问他人数据；
- 持久化、下载或传播你偶然发现的秘密和私人内容；
- 使用社会工程、拒绝服务或破坏性载荷。

优先使用离线 fake client、保留域名、合成 HTML/文本和临时目录。仓库许可证
不授予测试第三方系统的权限。

### 不属于安全漏洞

一般功能错误、文档问题、模型输出质量、预期的 API 费用，以及没有越过安全
边界的本地错误，应使用普通 Issue。对第三方服务本身的漏洞请遵循该服务的
安全政策。版权下架请求也不是漏洞报告，但如果包含私人信息，可先私密联系
维护者。

## English

### Supported versions

| Version | Receives security fixes |
| --- | --- |
| Current `main` and latest `0.1.x` | Yes |
| Earlier versions or other unpublished snapshots | No |

Before a stable release, only the current `main` branch and latest published
version are maintained. A security fix may require upgrading to the latest
patch release.

### Reporting a vulnerability privately

Do not open a public issue, discussion, or pull request for a security concern.
Never paste exploit details, credentials, private text, or logs in a public
place.

On the GitHub repository's **Security** page, choose
**Report a vulnerability** and submit through GitHub Private Vulnerability
Reporting. If that entry is not visible, the repository owner has not enabled
it yet. Keep the details private and use a private contact method listed on the
maintainer's GitHub profile only to ask that the feature be enabled.

Please include, when possible:

- the affected version, commit, or component;
- a minimal reproduction without real secrets or copyrighted text;
- expected behavior, actual impact, and exploitation prerequisites;
- mitigations you have already tried; and
- whether the issue has been disclosed elsewhere.

Reports involving key or source-text exposure, failed log redaction, SSRF or
DNS rebinding, malicious redirects, path traversal or symlink escape, cache
poisoning, arbitrary file overwrite, cost-guardrail bypass, and dependency
supply-chain issues are especially useful.

If a real credential is exposed, its owner should revoke or rotate it
immediately instead of waiting for a project fix. Do not repeat the complete
credential in the report; include only a redacted identifier and necessary
context.

Maintainers will acknowledge, assess, and coordinate remediation and
disclosure through the same private thread as capacity permits. Keep details
private until a fix is released or an agreed disclosure date is reached. This
is a volunteer project and does not promise a fixed response time or bounty.

### Research boundaries

Test only systems and data that you own or have explicit permission to test.
Do not:

- call real OpenAI or third-party APIs, incur charges, or affect availability;
- scrape copyrighted content, bypass authentication/paywalls/DRM, or access
  another person's data;
- retain, download, or distribute secrets or private content encountered by
  accident; or
- use social engineering, denial of service, or destructive payloads.

Prefer offline fake clients, reserved domains, synthetic HTML and text, and
temporary directories. The repository license does not grant permission to
test third-party systems.

### Not a security vulnerability

Ordinary bugs, documentation mistakes, model-output quality, expected API
charges, and local failures that do not cross a security boundary belong in a
regular issue. Report vulnerabilities in third-party services under that
service's policy. Copyright takedown requests are also not vulnerability
reports, although a private maintainer contact may be appropriate when they
contain personal information.
