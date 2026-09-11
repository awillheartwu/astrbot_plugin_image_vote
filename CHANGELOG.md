# Changelog

## 0.8.0 - 2026-09-12

- 新增项目登记表 `projects.json`：项目名 → 容器内任意绝对路径，支持跨卷与任意层级，解析优先级高于别名与 `input_root`。
- 新增管理员指令 `/vote register`、`/vote unregister`、`/vote projects`；`/vote list` 分开列出注册项目与目录项目。
- 登记项可覆盖 `interval_seconds`、`recursive`、`description`；文件按修改时间自动重载，外部编辑无需重载插件。
- `/vote check` 对登记项目只显示名称，绝对路径仅在管理员的 `/vote projects` 中呈现。
- 测试从 58 增加到 62。

## 0.7.0 - 2026-09-12

- 新增 `send_failure_pause_threshold`（默认 3，0 表示关闭）：连续发送失败达到阈值时自动暂停会话，并向投票群发送提示，管理员可用 `/vote resume` 继续。
- 短 ID 从 4 位十六进制提高到 8 位（约 43 亿种），降低跨会话引用误路由的概率；4 位的历史会话仍能正常解析。
- 测试从 55 增加到 58。

## 0.6.0 - 2026-09-12

- 修复插件卸载/重载会把运行中的会话写成 `CANCELLED`、导致无法续跑的问题：现在留下 `PAUSED`，`/vote resume` 可继续；显式 `/vote stop` 仍然是 `CANCELLED`。
- `FINALIZING` 纳入恢复范围：结算中断的会话重启后可重新结算并生成报告。
- 新增 `active_candidate_id`：发送失败的图片不再成为投票目标，窗口票落在最近一次成功发送的图片上；老数据库自动补列。
- 报告改为在 `COMPLETED` 之后生成，`finished_at` 先于结算写入；报告失败只记录错误，保留 `/vote export` 重试路径。
- 计票范围以会话快照为准：运行中修改评分范围只影响新会话，并打印一次警告。
- 监听入口跳过机器人自己发出的数字消息。
- 测试从 46 增加到 55。

## 0.5.0 - 2026-09-12

- 评分制可配置：`score_min` / `score_max` 上限放宽到 100，支持 1-5、1-10 等满分制；解析位数由范围决定，支持两位数，新增 NFKC 归一化（全角数字可用）并拒绝前导零。
- 群消息提示语、报告分数标签、`/vote check` 输出全部跟随配置，不再写死 1-4。
- session 持久化评分范围，老数据库自动补列，历史报告按当时的范围渲染。
- AI 输入与提示词带上评分范围。
- 修复 `single_html` 模式从 `data.json` 读回后分数分布键变成字符串、导致分布显示为 0 的问题。

## 0.4.0 - 2026-09-12

- 按目标实例实测（AstrBot 4.27.5）重写兼容层：改用 `StarTools.get_data_dir`，`filter` 与 `EventMessageType` 按多种真实布局探测，装配日志自报命中来源。
- 修复插件以 `data.plugins.<插件名>.main` 包形式加载时的导入失败，并加入回归测试。
- `_conf_schema.json` 改为官方对象格式（分组、hint、options），配置读取同时兼容分组与扁平结构。
- 接入 AI 统计总结（`get_current_chat_provider_id` + `llm_generate`，失败不影响报告生成），AI 输入新增争议项。
- `/vote finish` 立即停止后续发送；`/vote cleanup` 支持短 ID 与报告目录名；新增按保留天数自动清理。
- `/vote check` 补齐命名统计、首末各 5 张、非法文件、预计耗时与体积估算；`/vote status` 增加倒计时；启动回复增加预计耗时。
- 报告默认按排名排序并可切回原始顺序，头部增加开始/结束时间，发送失败的图片单独标注。
- 日志按 INFO / DEBUG / WARNING / ERROR 分级接入。
- 新增 `docs/ROADMAP.md`：差距清单、新需求与 AstrBot 官方约定核对结果。

## 0.1.0 - 2026-09-11

- 建立配置、领域模型、项目扫描、路径安全、投票路由、统计、SQLite、报告和任务生命周期边界。
- 加入 AstrBot 可选导入兼容壳，核心模块不依赖 AstrBot。
- 加入 Python 标准库可运行的核心回归测试。

## 0.2.0 - 2026-09-11

- 接入可暂停、可恢复、可停止和可提前完成的轮播 runner。
- 接入群消息投票、引用投票路由、重启后暂停恢复和最近 session 导出。
- 接入 AstrBot MessageChain/Reply 适配边界与安全报告清理命令。
- 新增应用层、适配层和 runner 的回归测试。

## 0.3.0 - 2026-09-11

- 完善 `/vote status`、`export`、`cleanup`，并要求清理全部报告时显式确认。
- 支持目录报告与压缩图内嵌的 single HTML 模式，超限自动回退目录模式。
- 接入结构化 AI 总结输入、项目别名、重启后暂停投票和报告输出目录防碰撞。
- 增加真实 AstrBot API 探针 `tools/astrbot_api_probe.py`。
