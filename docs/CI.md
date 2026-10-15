# Forgejo 自动检查与 NAS 部署

工作流：`.forgejo/workflows/ci.yml`。复用在线 `nas-runner-site` 的 `self-hosted`、`linux`、`docker` 标签和自动挂载的 `/var/run/docker.sock`。Runner 可以管理宿主 Docker，只运行受信任的仓库内代码，跳过 fork PR。不需要注册新 Runner、挂载额外宿主目录或配置 SSH。

## 执行平台隔离

CI 与 NAS 自动部署只在 Forgejo 执行；GitHub 仅同步源码。可执行工作流统一保存在 `.forgejo/workflows/`，`.github/workflows/` 只保留 README，不添加 `.yml` 或 `.yaml`，因此向两端同步 `dev`、`main` 不会触发 GitHub Actions。

Forgejo 工作流中的 `github.*` 兼容上下文与 GitHub checkout action 地址不改变执行平台。维护 CI 时只修改 `.forgejo/workflows/`，不要向 `.github/workflows/` 复制工作流。

## 触发与检查

| 事件 | 自动检查 | NAS 更新／重载 |
| --- | --- | --- |
| dev push | 是 | 否 |
| main push | 是 | 检查成功后 |
| 仓库内 PR 到 dev／main | 是 | 否 |
| fork PR | 跳过此宿主权限 Runner | 否 |
| 手动执行 | 是 | 仅选择 main 时 |

检查包括 YAML、Shell／JS 语法、完整 Python 单元测试、实际 Git 归档中的插件导入、图片报告生成与 SQLite 重开。面板／报告浏览器与真实 QQ 验收仍按 RELEASE.md 在发布时执行，不把本工作流等同于真群业务验收。

## 密钥与变量

唯一必需的仓库 Actions Secret 为 `ASTRO_KEY`：AstrBot OpenAPI Key，授予 `plugin` 权限。它没有“仅此插件”的细分权限；脚本固定操作 `astrbot_plugin_image_vote`。不需要面板密码、JWT 签名密钥、NAS 登录密码或 SSH 私钥。

密钥只注入部署步骤，随后通过 `docker exec -i` 的标准输入送入 AstrBot 容器内的工作进程；不放目标进程参数、容器环境、磁盘、Git 或日志。工作进程只访问该容器的 loopback HTTP，拒绝重定向，不输出 API 响应原文。

可选仓库变量（均为 AstrBot 容器内路径）：

| 变量 | 默认 |
| --- | --- |
| `ASTRBOT_CONTAINER` | 自动寻找唯一名称／镜像含 astrbot 的运行中容器；有多个时必须填写 |
| `ASTRBOT_PLUGIN_DIR` | `/AstrBot/data/plugins/astrbot_plugin_image_vote` |
| `ASTRBOT_DATA_DIR` | `/AstrBot/data` |
| `ASTRBOT_LOCAL_BASE` | `http://127.0.0.1:6185`，只接受容器 loopback 地址 |

无需 API `system` 权限读取日志。成功依据是重载接口返回成功，随后插件查询返回启用且版本匹配，同时 NAS Git HEAD 等于本次 CI 完整 SHA。版本和提交分别校验；只修改 metadata.yaml 但没成功重载不能算部署成功。

## 数据与失败状态

1. 使用已测试提交创建 Git bundle，通过 Docker copy 传入容器临时目录，不依赖 NAS 到 Git 仓库的网络或凭证，也不把 job 的 `$PWD` 当作宿主路径挂载。
2. 容器内 `ci-deploy.lock` 文件使用 `flock`，覆盖整个备份、快进和重载过程。Forgejo 15 的并发组另外将同一分支的运行排队、不取消在途发布。Actions 等待进程被取消时，已启动的 Docker exec 工作进程仍会继续收尾；不删除仍被占用的锁。
3. 先检查工作区干净、没有 PREPARING／RUNNING／PAUSED／FINALIZING 场次，并用 Key 查询插件。认证或权限错误在代码更新前失败。活动场次只提示先结束或取消，再重跑；CI 不会主动结束投票。开始备份、更新前和重载前均检查场次，但没有锁住用户发起新投票的入口，部署时应留出短暂空闲窗口。
4. 只接受从 NAS 当前提交快进到已验证 SHA；拒绝分叉与旧任务倒退部署。更新前使用 SQLite backup 保存一致性数据库，保存插件配置和原提交，目录与文件权限分别为 0700／0600，保留在插件数据目录的 `backup-ci-*`。目录创建后显式 chmod 并复核，避免 Synology 继承 ACL 忽略 mkdir 的权限参数；无法收紧时在写备份前失败。这些是恢复备份，不按缓存删除，需按运维需要保留或清理。
5. 失败不强制覆盖工作区、不清空历史、不重启 AstrBot 容器、不自动还原数据库。更新后失败时保留当前代码和备份，修复原因再重跑或发布向前修复；涉及降级先按 RELEASE.md 核对 schema 兼容。
6. 成功后写入数据目录 `ci-deployment.json`，记录 SHA、版本、旧提交、备份路径和核对时间；不含 Key。正常结束自动清理本次 `/tmp/lirating-ci-*`，不做全局 Docker prune。

## 操作与排查

- `dev` 用于日常开发。完成验收后将 dev 快进合入 main，推送 Forgejo main 即触发部署。标签与 GitHub 同步仍按 RELEASE.md 执行，标签 push 不另触发一次部署。
- 手动重跑：仓库 Actions 选择本工作流，在 main 执行；只能重复当前或更新的提交，不能用旧任务做降级。
- 无任务分配：确认本仓库可见的 Runner 在线且三个标签匹配。
- 缺 Key／HTTP 401／403：核对仓库 Secret 名为 `ASTRO_KEY`，以及 Key 未过期、未撤销并拥有 `plugin` scope；不把 Key 粘贴到日志。
- 容器歧义或找不到数据：设置上述变量；不要通过扩大挂载或直接清空数据绕过。
- 脏目录、场次未结束、分叉：先保留现场并人工处理，然后重跑。锁超时：检查前一工作进程，不能删除文件强行抢锁。
- 此机制部署插件代码，不会自动升级 AstrBot 自身或安装新的运行依赖。requirements.txt 如有变化，需在部署前确认目标环境依赖，不能以重载成功替代新依赖安装验收。
