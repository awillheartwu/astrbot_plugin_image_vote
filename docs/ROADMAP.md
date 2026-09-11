# 路线图与差距清单

更新时间：2026-09-11。基线：`docs/REQUIREMENTS.md`（1751 行）＋ 真机验收结果（AstrBot 4.27.5 / NapCat / 本地 Portainer stack）。

## 一、已真机验证

- `/vote list`、`/vote check sample`（19 张、sequence 排序、94.3 MB、耗时估算与实测吻合）。
- 19 张完整轮播到 `COMPLETED 19/19`，群消息带 `[投票 0NN/019 · 短ID]` 与内部标记。
- 当前窗口票与**引用投票**都落库（`source_type` 出现 `current_window` 与 `quoted_reply`），同一用户同一图唯一一行。
- 目录式报告：`index.html` + `data.json` + `report.css/js` + `images/NNNN.webp` 与 `NNNN_thumb.webp` 派生图，原图未被修改。
- AI 统计总结在真实 provider 上生成并进入报告页面。
- 兼容层事实：`filter=astrbot.api.event.filter`、`event_message_type=filter.EventMessageType`、`data_dir=StarTools.get_data_dir`、配置由构造参数注入。

## 二、需求文档中尚未完成的条目

| 章节 | 条目 | 现状 |
| --- | --- | --- |
| §5.3 | `project.json` 的 `name` / `sort_mode` / `interval_seconds` / `description` | 只实现了 `files` 顺序覆盖 |
| §6 | 扫描时忽略报告输出目录 | 未实现（output_root 位于项目目录内时会被扫到） |
| §7 | `/vote export --ai` | 未实现（export 固定不重新调用 AI） |
| §2.1 | AstrBot 4.4.x 兼容 | 目标实例是 4.27.5，未验证 4.4.x；文档需改写 |
| §13 | 发送重试退避 2s / 5s / 10s | 实现为 2s / 4s / 6s |
| §16、§17.3 | 标准差 | 已计算并输入 AI，报告页面未展示 |
| §18.1 | 报告目录命名 `<date>_<短ID>`、`assets/` 子目录 | 实现为 `<短ID>-<会话ID前8位>`，css/js 平铺；功能等价，命名不同 |
| §18.3 | 单 HTML 超限回退的提示 | 只写入 `data.json` 与日志，未回群消息 |
| §20 | 图片详情区的「投票人昵称列表」 | 未实现（新需求 N2 / N3 会覆盖并扩展为头像与按人视图） |
| §24 | `image_process_concurrency` 并发上限 | 当前串行压缩，满足「不要一次并发几十张」；500 MB 级压测未做 |
| §25 | DEBUG 的「压缩前后大小」与「quote resolver 结果」 | 未打印 |
| §27.8 | 群隔离显式用例 | 仅有按群分任务的实现，无用例 |
| §27.9 | 跨进程重启 E2E | 未做（单测覆盖了恢复逻辑） |
| §27.10 | 500 MB 项目 | 未做（真实跑了 94.3 MB / 19 张） |
| §28 Phase 4 | WebUI | 未做 → 新需求 N4 |
| §29 #7 / #9 / #12 | 多群并行、重启恢复、超大项目 | 未验证 |
| §31 #5 | 「每完成一阶段先写测试」 | 实际为边写边测 |

清理项：`templates/report.html.j2` 已无引用，可以直接删；README 与 docs 的「未确认」已改为实测结论。

## 三、新需求（本次提出，需要并入 `docs/REQUIREMENTS.md`）

### N1 报告页面细化与视觉升级

- 总结区结构化：参与度、Top、争议项、低分项分块呈现，而不是一段文字。
- 排名区与详情区分层：概览表格 + 可展开详情。
- 视觉：卡片密度、排版层级、深浅色一致性。

### N2 投票人头像

- 报告详情里展示投票人昵称与头像。
- 离线可用：生成报告时把头像下载到 `images/avatars/`，HTML 用相对路径引用。
- 头像来源候选：NapCat/OneBot 群成员信息接口，或 QQ 头像 URL 模板（`https://q1.qlogo.cn/g?b=qq&nk=<QQ号>&s=100`）。容器有外网。
- 需要新增持久化：`voter_id → 昵称/头像文件` 的映射（避免每张图重复下载）。

### N3 按人查看与选项分析

- 按投票人聚合：某人给哪些图打了分、平均分、投票时间线。
- 选项分析：分数分布、分歧度（标准差）、票数分布、0 票项。
- 需要报告 `data.json` 增加投票明细（当前只输出聚合结果）。

### N4 Plugin Pages 管理页面

参考 `astrbot_plugin_qq_group_daily_analysis` 的实现：

- 项目列表与扫描预览、当前 session 进度、历史 session、报告下载入口、一键清理。
- 路径配置、AI 提示词模板等可编辑项（与 N5、N6 共用页面）。
- 需要先读 AstrBot 4.27.5 的 Plugin Pages / `register_web_api` 实际接口，再定前后端结构。

### N5 AI 提示词模板可配置

- 新增配置项（如 `ai_prompt_template`），页面可编辑多行文本。
- 变量占位：项目名、Top N、Bottom N、统计 JSON。
- 保留「只喂统计数据、不改数字」的约束，模板改动不得改变统计来源。

### N6 项目注册表（一个项目名对应任意目录）

- 现状：所有项目必须是 `input_root` 下的第一层子目录。
- 目标：支持登记任意绝对路径的项目，可跨目录、可不同层级、彼此不相通。
- 形态：`projects.json`（项目名 → 绝对路径 + 可选排序方式/间隔说明），`/vote list` 同时列出注册项目与 `input_root` 下的目录。
- 安全：`docs/REQUIREMENTS.md` §26 已允许「项目路径来自管理员配置」时使用绝对路径；登记入口只对管理员开放，`path_guard` 仍需校验可读性与非 symlink 越界。
- 每个项目可选是否递归、扫描深度（应对「上层隔着几层」的目录结构）。

**状态：已实现（0.8.0，2026-09-12）**，见本文档第九节。

## 四、建议批次

1. **批次 1（数据与呈现）**：N6 项目注册表 → N3 投票明细入库与聚合 → N2 头像 → N1 页面重构。这一批不依赖 AstrBot 页面接口，风险最低，且能立刻改善可用性。
2. **批次 2（管理页面）**：N4 Plugin Pages + N5 提示词编辑 + 路径编辑。先做接口探针，再定前后端。
3. **批次 3（验证补齐）**：重启恢复、多群并行、500 MB 压测、cleanup/export、§27 剩余用例；同步文档与 CHANGELOG。

## 五、AstrBot 官方约定（已核对 docs.astrbot.app）

### 配置 schema（`guides/plugin-config`）

- `type` 支持：`string`、`text`、`int`、`float`、`bool`、`object`、`list`、`dict`、`template_list`。
- `text` 会渲染成可拖拽的大文本框 → N5 的 AI 提示词模板直接用它，不需要自建页面。
- `_special: "select_provider"` 让用户在面板里从已配置的模型服务中选 → `ai_provider_id` 改用这个，不必手抄 Provider ID。
- 其他可用字段：`secret`（遮罩）、`options`、`editor_mode`/`editor_language`（代码编辑器）、`invisible`、`obvious_hint`、`hint`。

### 插件 Pages（`guides/plugin-pages`）

- 目录结构：`pages/<page_name>/index.html`，只扫描一级子目录且必须有 `index.html`；新增或删除页面后需重载插件，改静态资源刷新即可。
- 前端运行在受限 iframe 里，通过 `window.AstrBotPluginPage` bridge 与 Dashboard 通信，由 Dashboard 转发到插件后端。
- 后端：`context.register_web_api("/<插件名>/xxx", handler, ["GET", "POST"], "描述")`；handler 内用 `astrbot.api.web` 的 `json_response`、`error_response`、`request`（`request.query.get("k", 默认, type=int)`、`await request.json(default={})`、`request.username`）。
- 官方建议：只填少量配置优先用 `_conf_schema.json`，Pages 用于复杂表单、状态面板、日志、上传下载、SSE、图表。

### 存储（`guides/storage`）

- 小状态可用插件 KV：`self.put_kv_data / self.get_kv_data / self.delete_kv_data`（≥ 4.9.2）。
- 大文件规范位置是 `data/plugin_data/<插件名>/`，可用 `get_astrbot_data_path()` 或 `self.name`。

### metadata 与发布（`plugin-new`、`plugin-publish`）

- 可用字段：`name`、`display_name`、`desc`、`short_desc`、`version`、`author`、`repo`、`astrbot_version`、`support_platforms`、`social_link`、`tags`；可选 `logo.png`（1:1，256px）。
- 插件市场 zip 上限 16 MB，需排除 `.git`、`__pycache__` 等。
- 待办：本插件 `metadata.yaml` 的版本号与 CHANGELOG 不一致；可补 `astrbot_version`、`support_platforms: [aiocqhttp]`、`short_desc`，`repo` 等 remote 就绪后再填。

### 对批次的影响

- N5 不必等 Pages：把提示词模板做成 `type: "text"` 的配置项就能在现有配置页里编辑。
- `ai_provider_id` 改为 `_special: select_provider`，顺手解决「不知道 Provider ID 叫什么」的问题。
- N4 的管理页面结构已明确（`pages/` + `register_web_api` + `astrbot.api.web`），实施前再抓一次 bridge 前端的完整示例。

## 六、已完成：评分制可配置（2026-09-12）

- `score_min` / `score_max` 上限从 9 放宽到 100，支持 5 分制与 10 分制。
- 解析器改为按 `score_max` 决定位数，支持两位数；新增 NFKC 归一化（全角数字可用）与前导零拒绝。
- 群消息提示语、报告分数标签、`/vote check` 输出全部跟随配置。
- session 新增 `score_min` / `score_max` 字段并写入 SQLite，老库自动 ALTER 补列，历史报告按当时范围渲染。
- AI 输入新增评分范围，提示词里显式告知满分值。

## 七、待定的边界策略

以下场景在 `docs/REQUIREMENTS.md` §11.7 有完整表格。已按默认策略实现的两条：机器人自己发的数字消息直接跳过；发送失败的图片不再成为投票目标，窗口投票落在上一张成功发送的图片上。

两条已按决策实现（2026-09-12）：连续发送失败达到阈值（默认 3，可配，0 为关闭）自动暂停并在群里提示管理员；短 ID 从 4 位十六进制提高到 8 位（约 43 亿种），4 位的历史会话仍能正常解析。

## 八、已修复的稳定性问题（2026-09-12）

1. **取消语义拆分**：插件卸载/重载不再把运行中的会话写成 `CANCELLED`，而是留下 `PAUSED` 供 `/vote resume` 续跑；显式 `/vote stop` 仍然是 `CANCELLED`。
2. **`FINALIZING` 纳入恢复**：结算中断的会话重启后回到可恢复状态，`/vote resume` 会重新结算并出报告。
3. **发送失败不再改变投票目标**：新增 `active_candidate_id`，窗口票始终落在最近一次成功发送的图片上；老库自动补列。
4. **结束时间与报告状态对齐**：报告在 `COMPLETED` 之后生成，`finished_at` 先于结算写入；报告失败只记错误并保留 `/vote export` 重试路径。
5. **计票范围以会话为准**：运行中改评分范围只影响以后的会话，当前会话按创建时的范围计票并打一次警告。
6. **机器人自己发的数字不再计票**：监听入口比对 `self_id` 后跳过。
7. **连续发送失败自动暂停**：新增 `send_failure_pause_threshold`（默认 3，0 关闭），命中后在群里提示管理员，`/vote resume` 可继续。
8. **短 ID 提到 8 位**：`secrets.token_hex(4)`，解析规则不变，历史 4 位会话兼容。

## 九、已完成：项目登记表（2026-09-12）

- `projects.json` 支持「项目名 → 容器内任意绝对路径」，解析优先级高于别名与 `input_root`，允许跨卷、任意层级。
- 新增管理员指令 `/vote register`、`/vote unregister`、`/vote projects`；`/vote list` 分开列出「注册项目」与「目录项目」。
- 登记项可覆盖 `interval_seconds`、`recursive`、`description`；文件按时间戳自动重载，外部编辑无需重载插件。
- `/vote check` 对登记项目只显示名称，绝对路径只在管理员的 `/vote projects` 中呈现。
- 管理页面里的目录浏览器（浏览容器内挂载根 + 表单增删）仍属批次 2。

## 十、已完成：结束行为可配（2026-09-12）

- `notify_on_finish`（默认开）：结束时在群里发提醒（项目、图片数、已发送张数、有效票、参与人数），报告成功或失败再补一条。
- `auto_report_on_finish`（默认开）：关闭后会话照常结束但不生成报告，由 `/vote export` 手动导出，适合大项目挑时间出报告。
- 配置页新增「结束通知与自动报告」分组；两个开关只影响收尾行为，不影响计票与持久化。

## 十一、已完成：控制指令确认回复（2026-09-12）

`/vote pause`、`/vote resume`、`/vote finish`、`/vote stop` 现在都回复结构化确认消息：指令动作、项目名、进度（已发/总数）、状态，以及下一步提示（继续 / 导出 / 无需操作）。没有进行中或可恢复会话时，给出中文说明而不是异常文本。
