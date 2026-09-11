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

清理项：`templates/report.html.j2` 已无引用；`CHANGELOG.md` 未记录本次 0.4.0 改动；`README`／`docs/ARCHITECTURE.md` 的「未确认」需改为实测结论。

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
