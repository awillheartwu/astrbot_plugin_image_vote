# 发布流程

## 分支与版本

日常开发在 `dev`，正式版本在 `main`，标签使用 `v<metadata.yaml版本>`。运行时注册与日志从 metadata.yaml 读取版本，不另维护 BUILD 常量。

1. 核对工作区，读取 GitHub 与 Forgejo 的 main/dev 最新状态；有远端独有提交时先合并审阅，禁止强推覆盖。
2. 在 dev 更新版本与 CHANGELOG，完成针对性测试、报告交互检查、面板明暗主题检查。
3. 首次发布或改动安装／配置链路时，运行隔离 HTTP 验收：`python tools/check_workspace.py --astrbot-source <AstrBot源码目录>`。需 FastAPI、uvicorn、httpx、Pillow；该工具使用临时数据和替身发送，不发送真实群消息。
4. 分类提交，在 main 执行 `git merge --ff-only dev`。若不能快进，先回 dev 解决分歧和复验。
5. 用带 Pillow 的 Python 运行 `python tools/check_release.py --ref HEAD`，检查实际 Git 归档内容、干净解压后的插件导入、真实图片报告生成与配置。
6. 创建带说明标签 `git tag -a v<版本> -m 'Release <版本>'`，再按标签运行归档检查，保留 ZIP、SHA256 与检查记录。
7. 显式分别推送 main、dev 和本次标签到 GitHub、Forgejo；不要使用 `--tags` 或强推。两个远端不是原子事务，一端失败时记录成功端并仅补推失败端。
8. 分别使用 `git ls-remote <仓库> refs/heads/main refs/heads/dev 'refs/tags/v<版本>^{}'` 确认两端指向本次发布提交。
9. 发布者注册 AstrBot Cloud，并用 GitHub 仓库地址提交插件市场。NAS 部署独立授权执行，不由 git push 隐式触发。
10. 返回 dev 继续后续开发。发现已发布问题时追加修复提交和新版本，不移动已发布标签。

## 分发内容

`.gitattributes` 的 export-ignore 从 Git 归档中排除原型、设计图片、测试、工具、开发文档；这些仍留在源码仓库。ZIP 保留 main.py、src、pages、assets、metadata.yaml、配置 schema、requirements、README、CHANGELOG、LICENSE 和 logo。

本地打包必须用 Git 归档，不手工收集文件。市场实际下载途径仍需在提交后验证；平台若忽略 export-ignore，完整源码 ZIP 也应小于官方 16 MB 限制。不要把 .gitignore 误认为已跟踪文件的打包排除规则。

## 验收边界与回退

干净归档检查验证独立包可导入和生成真实图片报告，不等同于 AstrBot 真机首次安装。公开发布前后应在测试实例检查安装、配置、投票、报告下载与重启恢复；不得把生产实例里的旧配置和图片当作自动化测试夹具。

回退先保存插件配置、vote.db 与现有报告，再安装前一发布归档。涉及数据库 schema 变更时，先验证降级可行性，不只替换 Python 文件。
