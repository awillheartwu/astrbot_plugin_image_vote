# 首轮架构与接力说明

## 目标

本轮先建立一个不依赖 AstrBot 的可测试核心，避免 OneBot Reply、消息链和版本差异污染投票业务。当前已继续接入可暂停轮播、群消息投票、重启后暂停恢复、目录报告导出和安全清理；`main.py` 仍只负责生命周期、装配和边缘事件。

## 分层

```text
AstrBot event / command
        ↓
main.py + src/astrbot_compat.py
        ↓
src/application.py
        ↓
domain services: scanner / vote_collector / statistics / session_manager
        ↓
ports: platform_adapter / persistence / image_processor / ai_summary_service
        ↓
OneBot、SQLite、Pillow、AstrBot provider
```

### 已建立的边界

- `config.py`：默认配置和运行时校验。
- `models.py`：Session、Candidate、Vote、统计结果和状态枚举。
- `project_scanner.py`：编号文件名、普通文件名、混合命名、manifest 顺序、人物识别，以及按首次出现位置进行稳定人物分组。
- `character_service.py`：发送、投票、统计和报告共用的人物身份兜底规则。
- `path_guard.py`：输入路径和报告清理的统一安全校验。
- `vote_collector.py`：严格评分解析、当前人物窗口路由，以及“引用图片 → 所属人物”的路由。
- `persistence.py`：SQLite schema、Session/Candidate/Vote UPSERT 边界。
- `session_manager.py`：每群一个可暂停、可恢复、可取消的 asyncio task。
- `report_generator.py`：目录式报告、派生图片入口、相对路径和 marker。
- `astrbot_compat.py`：AstrBot 可选导入、事件文本/插件数据目录兼容壳。
- `application.py`：命令与监听器应调用的框架无关应用服务。
- `astrbot_adapter.py`：MessageChain 发送和 Reply 组件归一化。
- `report_generator.py`：`/vote export` 复用最近 session，清理服务只删除本插件 marker 目录。

## 数据模型

SQLite 表为 `sessions`、`candidates`、`votes`。

- `sessions.id` 是全局 session ID；`short_id` 只用于群消息标记。
- `candidates.id` 不依赖数组 index，且由应用层按 session 作用域生成；`display_index` 只表示当前快照中的展示顺序。
- `sessions.active_character` 是普通数字票的当前人物目标，`active_candidate_id` 只保留最近成功发送图片的来源信息。
- `votes.character_name` 是票的统计目标，唯一键是 `(session_id, character_name, voter_id)`；`candidate_id` 记录触发该人物最终票的来源图片。
- 同一人物图片在候选快照中连续排列；人物第一张成功发送后开放投票，最后一张发送完成后才开始完整人物间隔。
- `source_relative_path` 永远相对项目根目录，报告和群消息不暴露绝对路径。

## Reply 解析方案

`reply_resolver.py` 只接收 `ReplyPayload`，不导入 OneBot 类型：

1. 适配器把 `Reply.chain` / `Reply.message_str` 和可选 `message_id` 归一化到 `ReplyPayload`。
2. 先匹配展示标记 `[投票 003/126 · A7F3]`，同时兼容内部标记 `[VOTE:A7F3:3]`。
3. `ReplyResolver` 校验 session short ID，再通过 display index 查当前快照候选。
4. 适配器无法提供引用文本时，可在 OneBot 边界用 message ID 回查，再重新生成 `ReplyPayload`。
5. 解析成功后读取图片所属人物；任何解析失败都返回 `None`，不会把引用票错误地记到当前人物。

## 报告数据口径

报告 schema v3 以 `characters` 为排名与评分主表，`candidates` 只保存人物分组、图片来源、发送状态和派生图路径。参与者明细的每条票包含 `character` 与 `source_candidate_id`：前者用于人物统计，后者用于追溯最后一次有效评分来自哪张引用图。目录版和单文件版使用同一份人物分组界面。

## 目标实例已确认的事实（2026-09-11 现场探针）

目标环境是 Portainer 里的 AstrBot（`soulter/astrbot:latest`）＋ NapCat 组合，实测版本 **AstrBot 4.27.5 / Python 3.12.14 / Pillow 12.3.0**，比需求文档里假定的 4.4.x 新得多。

- 挂载：宿主 data 目录（示例 `/mnt/docker/astrbot/data`）→ 容器 `/AstrBot/data`（读写）。插件目录 `/AstrBot/data/plugins`，插件数据目录必须用 `StarTools.get_data_dir("astrbot_plugin_image_vote")`，实测返回 `/AstrBot/data/plugin_data/astrbot_plugin_image_vote`。
- 发送：`MessageChain().message(text).file_image(path)` 存在；`Context.send_message(session, message_chain) -> bool`，返回 False 表示会话无法解析。
- 配置：`Star.__init__(self, context, config=None)` 收到的是 `AstrBotConfig`（`dict` 子类），键结构由 `_conf_schema.json` 决定。该文件是「按 key 索引的对象」，分组写法为 `"type": "object"` + `"items"`，枚举用 `"options"`，字符串列表用 `"items": {"type": "string"}`；写法参考 `astrbot_plugin_qq_group_daily_analysis`。
- 事件：`AstrMessageEvent.__init__(message_str, message_obj, platform_meta, session_id)`，`message_str` 与 `message_obj` 是实例属性；`filter` 与 `EventMessageType` 不在 `astrbot.api.event` 的静态导出列表里，`astrbot_compat.py` 因此按多种真实布局依次尝试，并在插件装配日志里自报命中来源。
- LLM 默认响应：AstrBot 的 `star_request` 处理管线会自行调用 `event.stop_event()`，命令不需要额外关闭默认 LLM 响应。
- 所有 AstrBot import 仍集中在 `astrbot_compat.py`；本地无 AstrBot 时仍可导入和跑测试，但一旦检测到 AstrBot 却找不到 `EventMessageType`，插件会在装配阶段直接抛错，避免静默失效。

仍未确认：`filter` / `EventMessageType` 的具体来源路径、`Reply` 组件的字段（需要在真实群里引用一条机器人消息触发探针）、`Context.llm_generate` 与 `get_current_chat_provider_id` 的签名。

## 下一步接力顺序

已完成并真机验证：引用消息的 `Reply` 结构（无需 OneBot `get_msg` 回查）、`Context.llm_generate` 与 `get_current_chat_provider_id` 接线、19 张图小项目的完整轮播与报告生成、Pillow 派生图。

接下来：

1. 补齐验收缺口：多群并行互不影响、跨进程重启恢复、500 MB 级项目的内存表现。插件重载路径已回归验证为 `PAUSED` 可续跑。
2. 按 `docs/ROADMAP.md` 的批次推进：项目注册表 → 投票明细与按人分析 → 头像 → 报告页面重构，之后是管理页面。
3. 单元测试不能替代 Reply 与发送链路验收；验收前不要把 `input_root` 指向真实的大项目。
