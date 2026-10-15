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
9. 插件市场首次注册／上架仅在明确请求时执行。Forgejo `main` 的 push 现在会在检查通过后自动部署 NAS，因此推送 main 同时是生产部署动作；日常开发与验证留在 dev。
10. 自动部署使用仓库 Actions Secret `ASTRO_KEY`、现有 NAS Docker Runner 和容器内快进／备份／重载／版本核对，详见 [CI.md](CI.md)。`tools/deploy_nas.sh` 保留为独立手动方式；它使用 SSH 和面板密码，不是 CI 的运行路径。
11. 返回 dev 继续后续开发。发现已发布问题时追加修复提交和新版本，不移动已发布标签。

## 每次开发完成后的收尾清单

1. **确认范围和工作区**：保留无关修改；按需求完成正常路径、失败路径和恢复。NAS 试部署与正式双仓库发布分别确认授权；不因历史发布授权而自动发布新任务。先只部署测试版时，可提交 dev 后独立部署，不必提前发布 main/tag。
2. **验证并保留证据**：使用带 Pillow 的 Python 3.12 运行单元测试；运行改动相关的面板／报告浏览器检查。配置、安装或持久化链路变化时，补隔离 HTTP 和旧库迁移／重开验证。测试必须使用临时数据；真实 QQ 验收另记，不能用单元测试替代。
3. **同步文档**：更新 README 的使用说明、USER_GUIDE 的配置语义、CHANGELOG 和 IMPLEMENTATION_STATUS 的验证范围。未完成或待真实环境验证的内容记录到 ROADMAP，保留历史记录。版本只改 metadata.yaml。
4. **提交和发布**：按职责分类 Conventional Commits，检查暂存差异与敏感文件。fetch 两端并确认没有远端独有提交；main 只快进 dev；按 HEAD、带说明标签分别做干净归档检查。保留 ZIP、SHA256、检查输出。
5. **明确推送目标**：本仓库 origin 可能有多个 push URL，正式发布用明确的 GitHub URL 和 Forgejo remote 分别推送 main、dev、本次标签；用 `ls-remote` 核对三者提交一致。失败只补失败目标，不强推、不移动已发布标签。
6. **NAS 部署前准备**：检查 NAS 工作区、当前版本和活动场次；数据库结构变化前，用 SQLite backup 保存一致性备份并保存插件配置，备份仅留 NAS 私有目录。历史报告与原图不作为清理对象；记录旧提交以备回退。
7. **部署与重载分开验收**：Forgejo main 推送后跟踪 Actions 至部署成功，核对完整提交、重载响应、运行版本与启用状态。手动脚本缺少 `ASTRBOT_PASSWORD` 时仅完成代码传输，不能把退出 0 当作已重载。自动部署缺少 `ASTRO_KEY` 必须失败。不得为重载而重启整个机器人容器。
8. **最终交接**：返回 dev，确认工作区、两端分支／标签、NAS 提交与运行版本。说明配置默认值、用户如何测试、实际完成的验证和待办；移除本次创建且已无用的临时产物，不删除用户数据、历史报告或需要保留的发行归档。插件市场首次上架、账户注册等另需明确请求，不是每次收尾的自动步骤。

## 分发内容

`.gitattributes` 的 export-ignore 从 Git 归档中排除原型、设计图片、测试、工具、开发文档；这些仍留在源码仓库。ZIP 保留 main.py、src、pages、assets、metadata.yaml、配置 schema、requirements、README、CHANGELOG、LICENSE 和 logo。

本地打包必须用 Git 归档，不手工收集文件。市场实际下载途径仍需在提交后验证；平台若忽略 export-ignore，完整源码 ZIP 也应小于官方 16 MB 限制。不要把 .gitignore 误认为已跟踪文件的打包排除规则。

## 验收边界与回退

干净归档检查验证独立包可导入和生成真实图片报告，不等同于 AstrBot 真机首次安装。公开发布前后应在测试实例检查安装、配置、投票、报告下载与重启恢复；不得把生产实例里的旧配置和图片当作自动化测试夹具。

回退先保存插件配置、vote.db 与现有报告，再安装前一发布归档。涉及数据库 schema 变更时，先验证降级可行性，不只替换 Python 文件。
