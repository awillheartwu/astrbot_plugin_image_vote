# 使用手册

## 图片目录与 Docker

input_root 下的一级子目录是项目；深层或外部目录可在工作区登记。示例：

```yaml
volumes:
  - /volume1/vote-projects:/vote/projects:ro
```

把 input_root 设为 `/vote/projects`。output_root 留空可使用插件数据目录 reports/；需要单独挂载时配置可写的容器路径。容器不可见的 NAS 路径无法使用。

人物按扫描时首次出现顺序分组，组内保留图片顺序。`project.json` 支持 `files` 顺序与 `characters` 人物映射；被 `characters` 命中的图片，展示标题也使用 manifest 里的人物名。项目登记优先于别名和输入根目录，并可覆盖间隔、递归设置与说明。

## 评分与发送

默认 1–4 分，可设置 0–100 内的连续整数区间。同一用户同一人物保留最终一票，默认后票覆盖；可选首次、最高、最低分策略。普通数字票记到当前人物，引用本场已发图片记到图片所属人物。

同一人物图片连续发送，最后一张发完才等待完整间隔。合并发送默认关闭，开启后每条默认最多 3 张；单条默认 90 秒超时，连续失败可自动暂停。最后一个人物的等待不少于人物间隔。暂停时仍可引用已发送图片投票。

## 全部命令

| 指令 | 用途 |
| --- | --- |
| `/vote 项目名` | 管理员开始投票 |
| `/vote list`、`/vote check 项目名`、`/vote status` | 列项目、预检、看状态 |
| `/vote pause`、`/vote resume` | 管理员暂停、恢复 |
| `/vote finish`、`/vote stop` | 管理员提前结算、取消并保留票 |
| `/vote export`、`/vote export --ai` | 管理员重新导出；后者重新调用 AI |
| `/vote cleanup 短ID或项目名`、`/vote cleanup all confirm` | 只删除本插件报告，保留记录 |
| `/vote purge 短ID或session_id confirm` | 删除场次记录及报告，不可恢复；不删原图或群消息 |
| `/vote register 项目名 容器内绝对路径` | 登记目录 |
| `/vote unregister 项目名`、`/vote projects` | 取消登记、查看登记项 |
| `/vote reloadconfig` | 重新读取并显示生效配置 |

除列项目、预检、查看状态外，管理操作要求管理员，具体权限受插件设置影响。

## 报告与体积

目录版含 HTML、JSON、样式脚本和派生图片；下载 ZIP 后完整解压。单文件版内嵌去重图片资源，超过默认 50 MB 上限会回退目录模式。

高清派生默认 WebP、1920×1920 内、质量 82；缩略图宽 480、质量 72。质量参数不是固定压缩比例。默认 `character_cover` 每个人物保留首张成功展示图的高清派生（全失败则首张），其余缩略图；`all` 保留全部高清。更改后重新导出才生效，对比前先下载保留上一版。

单文件图片在资源池中存储一次；无脚本时保留统计文字，查看内嵌图片需启用 JavaScript。只显示最终人物票，不提供改分历史或单图评分。

## AI 与隐私

默认提示词直接显示在设置页，可编辑与恢复默认，支持 `{project_name}`、`{statistics}`、`{top_n}`、`{bottom_n}`、`{score_min}`、`{score_max}`。输入为人物汇总统计，不传原图或逐人明细；模型返回的一句话和观察可折叠阅读。调用失败不阻止报告。

默认报告可以包含昵称、头像和逐人评分。分享前关闭 `report_include_participants`，重新导出汇总版；隐藏网页入口不能替代这一序列化设置。

## 管理网页与预检

通过 AstrBot 已登录管理员的 Plugin Pages 打开 image-vote；网页不提供绕过鉴权的独立入口。预检先扫描并显示数量、规则、输出状态，随后逐张取 240px 缩略图；群列表单独加载，就绪后即可启动。首次扫描及首次解码仍受图库规模和磁盘性能影响。

默认设置保存到同一份 AstrBotConfig，保存冲突时保留草稿并提示重新读取。缓存、目录和清理细节见 [DATA_MAINTENANCE.md](DATA_MAINTENANCE.md)。
