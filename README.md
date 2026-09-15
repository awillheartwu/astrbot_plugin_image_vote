# astrbot_plugin_image_vote

在 QQ 群里按人物批次发送项目图片并收集人物评分（默认 1-4，可配成 1-5、1-10 或包含 0 的范围），结束后自动生成按人物归类的 HTML 报告。AstrBot 插件，面向 aiocqhttp / OneBot v11 / NapCat。

## 功能

- `/vote <项目名>` 先按人物稳定分组：人物按扫描时首次出现的顺序，人物内部保持原图顺序。
- 同一人物的图片连续发送，中间不等待；第一张成功发出后立即开始接收该人物评分，最后一张发送完成后才开始完整人物间隔。
- 群成员直接回复数字给当前人物评分，也可以引用本场任意已发图片，给该图片所属人物补投或改分。评分范围可配置为 0-100 内的连续区间，两位数和全角数字均可识别。
- 同一用户对同一人物只保留一票；重复投票的取值策略可配：`last_wins`（默认）、`first_wins`、`max_score`、`min_score`。
- 人物名默认取图片标题第一个短横线之前的部分，可用项目目录的 `project.json.characters` 明确覆盖。
- 结束后生成目录式报告：`index.html` + `data.json` + 压缩后的 WebP 主图与缩略图，原图不复制、不修改。
- 可选调用当前会话的 AI 模型生成统计总结，只发送结构化统计；调用失败不影响报告生成。
- 每群同时只允许一个投票；暂停、恢复、提前结束、取消、重新导出、清理都有对应指令。
- AstrBot 重启后未完成的投票停在 `PAUSED`，由管理员执行 `/vote resume` 从断点继续，不会自动刷图。

## 环境

- AstrBot **4.27.x**（在 4.27.5 上完成真机验收；更低版本未验证）
- aiocqhttp / OneBot v11 / NapCat
- 报告图片处理依赖 Pillow，AstrBot 环境已自带

## 安装

面板安装：AstrBot WebUI → 插件管理 → 安装插件，填入本仓库地址。

手动安装：把本仓库放到 `<AstrBot data>/plugins/astrbot_plugin_image_vote`，再在插件管理里重载。

## 配置

配置项由 `_conf_schema.json` 定义，在 WebUI 的插件配置页按分组展示。最常用的四个：

| 配置项 | 说明 |
| --- | --- |
| `input_root` | 图片项目根目录，每个子文件夹是一个项目，项目名就是文件夹名 |
| `output_root` | 报告输出根目录，建议放在 AstrBot data 目录下 |
| `default_interval_seconds` | 人物投票间隔；同一人物图片之间不等待，首次试跑建议设成 5 |
| `merge_character_images` | 同一个人物的多张图合并成一条消息发送；默认关闭（逐张发送） |
| `score_min` / `score_max` | 评分范围，默认 1-4，可设成 1-5、1-10 等；改动后群消息提示与报告标签自动跟随 |

其余包括最后一个人物的等待、权限控制（仅管理员可开始、群白名单）、重复投票策略、报告压缩参数、AI 开关与 Top/Bottom 数量、发送重试次数、连续发送失败自动暂停阈值、结束时是否在群里提醒、是否自动生成报告、单文件报告是否发到群里等。WebUI 保存后配置会在下一条指令时自动生效，想立刻确认就打 `/vote reloadconfig` 看实际生效值。

关于发送间隔：一个人物的图片会一张接一张连续发出。该人物最后一张发送完成后，才等待完整的 `default_interval_seconds`；最后一个人物使用 `final_grace_seconds`，且实际值不会短于人物间隔。旧配置 `interval_includes_send_time` 仍可读取，但人物模式不再扣除上传耗时。

`merge_character_images` 打开后，一个人物只发一条消息、内含该人物的全部图片；总耗时接近这些图片上传时间的总和（上传字节数不变，省掉的是逐条消息与逐张之间的开销），人物之间的等待间隔与逐张模式一致。

项目与目录的对应关系由登记表解决：`input_root` 只覆盖「根目录下一层子目录」这种布局，层级更深或分散在别处的目录，用管理员的 `/vote register <项目名> <容器内绝对路径>` 登记，或直接编辑插件数据目录下的 `projects.json`。登记项可带 `interval_seconds`、`recursive`、`description`，解析优先级高于别名与 `input_root`。

## 指令

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `/vote <项目名>` | 管理员 | 开始轮播 |
| `/vote list` | 所有人 | 列出可用项目 |
| `/vote check <项目名>` | 所有人 | 只做预检：图片数量、总大小、命名统计、排序方式、首末各 5 张、非法文件、预计耗时 |
| `/vote status` | 所有人 | 图片进度、当前人物、本人物票数、总票数、下一人物倒计时 |
| `/vote pause` / `/vote resume` | 管理员 | 暂停 / 继续，暂停期间仍可引用已发图片投票 |
| `/vote finish` | 管理员 | 立即停止后续发送并出结果 |
| `/vote stop` | 管理员 | 取消本次投票，保留已收到的投票 |
| `/vote export` | 管理员 | 用最近一次完成或取消的会话重新生成报告 |
| `/vote cleanup <短ID 或 项目名 或 all confirm>` | 管理员 | 只删除本插件生成的报告目录 |
| `/vote purge <短ID 或 session_id> confirm` | 管理员 | 彻底删除一场投票：报告目录 + 投票记录（票与候选），不可恢复；原图不受影响，页面历史里也有「彻底删除」按钮 |
| `/vote register <项目名> <容器内绝对路径>` | 管理员 | 把任意目录登记成一个项目 |
| `/vote unregister <项目名>` | 管理员 | 取消登记 |
| `/vote projects` | 管理员 | 列出登记项与它们的容器内路径 |
| `/vote reloadconfig` | 管理员 | 重新读取配置并打印当前实际生效的值 |

四条控制指令（`pause` / `resume` / `finish` / `stop`）执行后都会在群里回复确认消息：触发的是哪条指令、项目名、当前进度、会话状态，以及下一步该做什么。

## Docker 路径映射

插件只能访问容器内路径，宿主机目录需要先映射进容器：

```yaml
volumes:
  - /volume1/vote-projects:/vote/projects:ro
  - /volume1/vote-reports:/vote/reports
```

对应配置 `input_root = /vote/projects`、`output_root = /vote/reports`。

## 报告

默认目录模式，一个会话一个文件夹，可以整体打包、静态托管或直接删除：

```text
<output_root>/<项目名>/<短ID>-<会话ID前8位>/
├── index.html
├── data.json
├── report.css
├── report.js
└── images/0001.webp, 0001_thumb.webp, ...
```

页面无外部 CDN 依赖，可以 `file://` 直接打开。概览按人物排名，「全部图片」把同一人物的所有图片放在同一分组，「按人查看」展示每位参与者对各人物保留的最终一票。图片仅作为人物来源与浏览素材，不再单独排名。清理只删除带本插件 marker 的目录，不会触碰 `input_root`。

## 开发

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
```

核心逻辑不依赖 AstrBot，本地没有 AstrBot 和 Pillow 也能跑测试。

- `docs/ARCHITECTURE.md` 分层说明与 AstrBot 4.27.5 实测的 API 事实
- `docs/ROADMAP.md` 尚未完成的条目与后续需求
- `docs/REQUIREMENTS.md` 需求原文
- `tools/astrbot_api_probe.py`、`tools/probe_plugin/` 现场兼容性探针

## 已知限制

- 只在 AstrBot 4.27.5 加 NapCat 的组合上做过真机验收，其他版本与平台未验证。
- 跨目录项目要先用 volume 把图库根目录映射进容器，再用 `/vote register` 或 `projects.json` 登记；容器看不到的路径无法使用。
- 报告可包含昵称、缓存头像和最终逐人评分；`report_include_participants=false` 生成不含这些明细与群号的汇总分享版。
- `single_html` 模式可选，超过 `single_html_max_mb` 会自动回退目录模式。

## 插件网页与人物报告（0.13.0）

在 AstrBot 的本插件 Pages 中打开「image-vote」页面，使用当前 Dashboard 管理员账户操作。网页提供：

- **运行**：从已连接的 OneBot 群选择目标，预检后启动；暂停、继续、提前结束或取消。
- **项目**：登记容器内目录、编辑项目覆盖参数、预览图片；目录浏览限于输入根、登记目录及 `web_browse_roots`。取消登记不会删除原图。
- **历史与报告**：查看场次与报告状态，预览、下载、重新生成和清理。目录报告下载完整 ZIP，单文件报告下载 HTML。
- **设置**：分组与搜索，修改后明确保存；配置仍写入同一份 AstrBotConfig。发现其他页面修改会拒绝覆盖，保留当前草稿。

新版报告有「概览 / 全部图片 / 按人查看」：概览和分值分布以人物为单位，全部图片按人物成组，逐人页只列每个人物的一张最终票。报告不需要后台或 CDN；目录版请保留整个目录，单文件版可以独立打开。

`ai_prompt_template` 留空使用默认模板，支持 `{project_name}`、`{statistics}`、`{top_n}`、`{bottom_n}`、`{score_min}`、`{score_max}`。普通导出复用已有 AI 摘要，只有 `/vote export --ai` 或网页勾选重新生成时才再次调用模型。AI 只接收统计，不接收整批图片。

本轮网页按 AstrBot **v4.27.5** 官方接口实现，并进行了本地隔离验收；不代表已部署到你的实际实例。复现命令、完整验证范围和限制见 [实现与验收记录](docs/IMPLEMENTATION_STATUS.md)。
