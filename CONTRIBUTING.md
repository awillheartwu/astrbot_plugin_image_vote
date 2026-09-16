# 开发约定

- 日常开发使用 `dev`；需要隔离工作时从 `dev` 建功能分支。`main` 只接收验证通过的发布。
- 一次提交只做一类事情，格式为 `type(scope): 中文说明`。常用 type：feat、fix、refactor、test、docs、chore；scope 按实际模块选择，如 report、panel、send、vote、config、release。
- 修复说明写清触发条件、结果与验证；不要在一个提交里混入部署凭证、数据库、用户图片或生成报告。
- 提交前检查 `git status --short`、`git diff --cached --check` 和暂存内容，保留其他人的修改。
- Python 验证：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .`。完整图片测试需要 `pip install -r requirements.txt`。
- 浏览器验证：`npm install --prefix /tmp/lirating-ui playwright`，然后 `NODE_PATH=/tmp/lirating-ui/node_modules node tools/check_panel_ui.cjs` 和 `node tools/check_report_ui.cjs`（第二条也需同一个 NODE_PATH）。脚本使用已安装的 Chrome，不需要下载浏览器。两套检查均默认不截图。
- 不把单元测试、隔离 HTTP 验收等同于真实 QQ 或生产验收。修改与验证范围必须写明。
- 发布执行 [发布流程](docs/RELEASE.md)，没有启用 CI，发布者负责运行检查并保存输出。
