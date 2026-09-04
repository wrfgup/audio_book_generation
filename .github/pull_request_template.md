## Summary / 变更摘要

<!-- Explain the user-visible behavior and why it is needed. -->

## Validation / 验证

<!-- List exact commands and important manual checks. -->

- [ ] `ruff check src tests scripts`
- [ ] `ruff format --check src tests scripts`
- [ ] `mypy src/audiobook_generator`
- [ ] `pytest`
- [ ] `python scripts/prepublish_check.py`

## Safety and compatibility / 安全与兼容性

- [ ] I used only synthetic or authorized fixtures and committed no credentials, private paths, raw books, logs, manifests, or generated media.
- [ ] Tests make no real network or OpenAI API calls.
- [ ] I documented public CLI, schema, environment, or behavior changes.
- [ ] I added or updated tests for failure paths and platform-sensitive behavior.
- [ ] I called out breaking changes, migration steps, cost changes, and AI-voice disclosure impact below.

## Additional notes / 补充说明

<!-- Write "None" when there is nothing else reviewers need to know. -->
