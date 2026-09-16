# Lirating 项目背景（供另一个 Agent 使用）

> 整理日期：2026-09-16（同日更新到 `0.13.11`）。代码基线见最新 `CHANGELOG.md`；本文描述的能力与边界截至该版本。
> 本文是项目背景快照，不是待执行任务或部署授权。后续需求由用户另行给出；实现细节以接手时的代码为准。

## 1. 项目定位

Lirating 是一个运行在 AstrBot 内的 QQ 群人物图片投票插件。管理员选择本地图片项目，机器人按人物连续发送图片；群成员给人物打分，结束后生成可离线浏览、分享的 HTML 统计报告。管理员也可通过 AstrBot 内的插件网页管理运行、项目、历史和设置。

- 插件标识：`astrbot_plugin_image_vote`。
- 插件展示名：**AstrBot 人物图片投票**；报告品牌：**LIRATING**。
- 本地仓库：`/Users/wuhaoli/projects/astrobot/lirating`。
- 仓库地址：<https://github.com/awillheartwu/astrbot_plugin_image_vote>。
- 主要使用者：组织投票的群管理员、参与评分的群成员、阅读报告的人。
- 核心业务单位是**人物**。图片是人物的展示素材与投票来源，不单独计票或排名。

## 2. 技术栈与运行形态

| 部分 | 当前方案 |
| --- | --- |
| 宿主与消息平台 | AstrBot，aiocqhttp / OneBot v11 / NapCat |
| 后端 | Python，dataclass 数据模型，asyncio 异步任务与控制 |
| 持久化 | 标准库 sqlite3；异步锁保护访问，通过 asyncio.to_thread 执行数据库工作 |
| 图像处理 | Pillow；生成压缩主图、缩略图及头像派生缓存 |
| 管理网页 | 原生 HTML / CSS / JavaScript，通过 AstrBot Plugin Pages / PageBridge 接入 |
| 管理 API | AstrBot register_web_api；复用当前 Dashboard 管理员身份 |
| 报告 | Python 生成 HTML 与 JSON，原生 JavaScript 渲染交互；不依赖后台或外部 CDN |
| AI | 调用 AstrBot 的模型 provider，根据结构化统计生成文字总结 |
| 测试 | Python unittest；另有隔离 HTTP、大图处理、报告页与面板的浏览器检查工具（`tools/check_report_ui.cjs`、`tools/check_panel_ui.cjs`） |
| 部署 | 安装或重载 AstrBot 插件；Docker 环境需要映射图片输入与报告输出目录 |

`requirements.txt` 声明 `Pillow>=10`。当前前端不需要 Vue、React 或独立 Node 构建服务。生产报告 HTML 的生成入口是 `src/report_generator.py`，不要仅凭 `templates/report.html.j2` 的文件名判断正在使用 Jinja2。

`metadata.yaml` 声明 AstrBot `>=4.27.0`。仓库记录过 4.27.5 与 4.28.0 的现场验证；这不代表所有版本、平台或最新代码均已完成线上验收。

## 3. 架构与文件地图

```text
QQ群命令 / 消息                     AstrBot 插件管理网页
       │                               │
main.py + AstrBot 适配器          pages/image-vote/ 原生前端
       │                               │
       │                         workspace_api.py
       │                         workspace_service.py
       └──────────────┬────────────────┘
                      ↓
                application.py
                      ↓
     项目解析 / 扫描 / 会话控制 / 投票路由 / 统计
                      ↓
    SQLite / OneBot 消息发送 / Pillow / AI / 报告导出
```

| 文件或目录 | 职责 |
| --- | --- |
| `main.py` | 插件生命周期、依赖装配、命令与群事件入口、权限与配置接线 |
| `src/application.py` | 核心应用编排：准备和启动会话、发送循环、控制、计票、结算、导出与删除 |
| `src/models.py` | 会话、候选图片、票、发送上下文、统计结果和状态枚举 |
| `src/config.py`、`_conf_schema.json` | 配置默认值与校验、AstrBot 配置页面定义 |
| `src/project_service.py`、`project_registry.py` | 项目名解析、别名、目录登记、项目参数覆盖 |
| `src/project_scanner.py` | 图片扫描、标题处理、排序、manifest、人物稳定分组 |
| `src/character_service.py` | 发送、路由和统计共享的人物身份与布局规则 |
| `src/session_manager.py` | 每群一个运行任务，暂停、恢复、终止与等待控制 |
| `src/message_sender.py` | 群消息文案、图片组发送与重试 |
| `src/platform_adapter.py` | 平台发送接口边界 |
| `src/astrbot_adapter.py`、`astrbot_compat.py` | AstrBot 消息链、事件与兼容处理 |
| `src/vote_collector.py`、`reply_resolver.py` | 评分解析、当前人物路由、引用图片定位 |
| `src/persistence.py` | SQLite schema、迁移、读写与票的冲突更新策略 |
| `src/statistics_service.py`、`report_data.py` | 人物统计、参与者最终票、报告 schema v3 数据投影 |
| `src/report_generator.py` | 派生图、目录与单文件报告、临时生成和发布 |
| `src/report_activity.py` | 同一场次报告读取、生成、清理的共享互斥守卫 |
| `src/image_processor.py`、`avatar_service.py` | 图片压缩、元数据处理、头像缓存与失败回退 |
| `src/ai_summary_service.py` | AI 提示词模板、统计输入、超时与失败降级 |
| `src/path_guard.py` | 目录边界与报告清理路径校验 |
| `src/workspace_service.py`、`workspace_api.py` | 管理网页业务与 AstrBot HTTP 接入 |
| `pages/image-vote/` | 正式插件管理网页 |
| `assets/report.js`、`assets/report.css` | 正式离线报告的交互与样式 |
| `prototypes/image-vote/` | 设计原型与示例素材，不是正式管理系统 |
| `tests/`、`tools/` | 单元测试、探针、隔离验收与预览工具 |

边界原则：群命令与网页共用应用服务和数据，不各自实现计票、导出或清理逻辑。平台差异留在适配层，核心规则应可在没有 AstrBot 的本地环境测试。

## 4. 关键业务规则与流程

### 项目发现与扫描

项目路径解析优先级：**projects.json 登记项 → project_alias.json 别名 → input_root 下的项目目录**。分散或深层目录可通过 `/vote register` 登记，但路径必须在容器内可访问。

支持项目 `project.json` 的 `files` 顺序与 `characters` 人物映射。默认从处理后的标题提取人物，常见规则是取第一个短横线前的部分。人物按扫描时首次出现顺序排列，同一人物内部保留原图顺序。

### 发送与投票窗口

1. 开始前扫描并保存候选快照；每群同时只允许一个投票。
2. 同一人物的图片连续发送，中间不插入人物等待间隔。
3. 该人物第一张图片成功发出即开放普通数字投票。
4. 最后一张发送完成后，才等待完整人物间隔；最后一个人物使用最终等待时间，且不短于人物间隔。
5. 全部图片发送失败的人物不开普通票窗口；部分成功仍可评分。

默认逐张发送。开启合并后，按图片组发送；每条默认最多 3 张，超出拆条，仍属于同一个人物窗口。默认单条超时 90 秒，支持重试与连续失败自动暂停。合并发送减少消息开销，不减少图片上传字节数。

固定周期配置已移除。不要恢复成“发送耗时抵扣人物投票间隔”的旧逻辑。

### 计票与引用

- 评分范围是 0–100 内的可配置连续整数区间，默认 1–4；支持两位数、全角数字等输入。
- 普通数字票归属当前人物；引用本场已发送图片时归属该图片人物。
- 同一用户对同一人物只保留一张最终票，默认后一次覆盖；可选首次、最高或最低分策略。
- 引用定位标记带会话短 ID 和展示序号；解析失败或跨场次引用不能退回当前人物误计。
- 暂停期间可以引用已发图片投票，具体窗口资格与配置由路由层判定。

### 会话结束与恢复

状态包括：`IDLE / PREPARING / RUNNING / PAUSED / FINALIZING / COMPLETED / CANCELLED / FAILED`。

`finish` 停止后续发送并结算；`stop` 取消并保留已有票。重启或重载后未完成场次暂停，管理员手动恢复，避免自动刷图。

## 5. 数据与报告

SQLite 主要表：

- `sessions`：项目、群、评分范围快照、进度、状态、当前人物、报告路径和 AI 摘要。
- `candidates`：会话内图片快照、人物、相对路径、展示序号、发送结果。
- `votes`：最终人物票；唯一键为 `(session_id, character_name, voter_id)`，`candidate_id` 保留最终票的来源图片。

`session_id` 是完整身份，短 ID 用于展示和引用；展示序号不是候选主键。数据库存在旧结构迁移。最终票表不等同于完整的每次改分事件日志。

报告 schema **v3**：`characters` 是人物排名与评分主表；`candidates` 承载图片浏览与来源；参与者票含 `character` 与 `source_candidate_id`。不要把旧版按图片计分的 schema 和页面需求直接套到当前代码。

报告有三个页面：

- **概览**：人物排名卡、人数与展示进度、人物票总数、统计口径、总体分值分布、可选 AI 解读。
- **全部图片**：按人物分组、搜索、图片放大、人物分布与参与者评分。
- **按参与者查看**：每人对各人物保留的最终票、均分与人物覆盖率。

两种导出：

- `directory`：HTML、JSON、CSS、JS、派生图片组成完整目录；网页下载提供 ZIP。
- `single_html`：样式、脚本和派生图片内嵌，HTML 可独立打开；默认 50 MB 上限，超限回退目录模式。

仅生成派生图，不修改原图。报告支持明暗主题与离线使用。关闭 `report_include_participants` 时生成汇总分享版，在序列化阶段移除个人明细与群号。

导出先生成临时产物，失败保留旧报告。读取、生成与清理共用 `ReportActivity`，群命令和网页都必须遵守。`cleanup` 只删带插件 marker 的报告；`purge` 经显式确认后删除场次、候选、票和报告，不删除原图或群消息。

AI 只接收结构化统计，不上传整批图片；调用失败不阻塞报告。普通导出复用已有摘要，`/vote export --ai` 或网页显式选择才重新调用模型。

## 6. 管理功能与配置

正式管理页分为 **运行 / 项目 / 历史与报告 / 设置**：选择群、项目预检与启动，暂停和继续，目录登记与浏览，历史场次，报告下载与重新生成，清理或彻底删除，分组配置保存。报告预览已移除（改为直接下载）。

配置写回同一份 AstrBotConfig，兼容分组与扁平结构，保存有版本冲突检查。项目登记支持 `interval_seconds`、`recursive`、`description` 覆盖。API 要求当前 Dashboard 管理员账户；文件浏览受输入根、登记目录和 `web_browse_roots` 限制。

常用命令：`/vote <项目名>`、`list`、`check`、`status`、`pause`、`resume`、`finish`、`stop`、`export`、`cleanup`、`purge`、`register`、`unregister`、`projects`、`reloadconfig`。完整参数和权限以 README 与 main.py 为准。

常用默认值：人物间隔 20 秒、最终等待 20 秒、逐张发送、合并上限 3 张、发送超时 90 秒、评分 1–4、后票覆盖、目录报告、AI 摘要开启。不要把用户某一场的 0–10 分配置当成项目默认值。

## 7. 术语与可复用文案

### 一句话介绍

> 在 QQ 群中按人物连续发送项目图片，收集每位成员的最终评分，自动生成可离线浏览的人物统计报告。

### 核心规则说明

> 同一个人物就是一个投票窗口。

> 同一人物的多张图片组成一个投票批次。每位参与者对每个人物只保留一票；引用任意本场图片都会路由到该图片所属人物。

“人物”指评分对象，“参与者”指打分的人，“图片”指展示素材。文案尽量避免含义不明的“按人查看”或把人物票写成图片票。

### 群消息示例（示意数据）

```text
示例项目 · Elis
第 2/17 位人物 · 第 4-6/7 张（本条 3 张） · 之后还有 1 张
回复 0-10 给「Elis」打分 · 引用本场任意图片可改分
[投票 012/045 · A7F3]
```

名字放首行，进度放第二行，操作提示放第三行，定位标记放末行。人物最后一条使用“本人物已发完”。具体标点、编号和文案以 `message_sender.py` 为准。

### 页面标签

| 场景 | 当前文案 |
| --- | --- |
| 报告导航 | 概览 / 全部图片 / 按参与者查看 |
| 人物未获票 | 已展示，暂无评分 |
| 全部发送失败 | 未成功展示 |
| 样本不足 | 仅 N 票 |
| 展示不完整 | 图片未全部展示 |
| 参与者指标 | 已评分人物 / 该参与者均分 / 人物覆盖率 |
| 运行状态 | 未开始 / 准备中 / 轮播中 / 已暂停 / 正在结算 / 已完成 / 已取消 / 失败 |
| 报告缺失状态 | 无报告 / 已清理（区分两者） |
| AI 区域 | AI 统计解读 |

清理提示应说明“只删除报告，保留评分，可重新生成”；彻底删除提示应说明“删除本场报告与投票记录，不可恢复；原图不受影响”。这两句是交接建议文案，具体页面实现可有差异。

## 8. 当前状态、验证与接手注意点

0.13.0 完成人物口径迁移；0.13.1–0.13.2 增加合并发送、拆条上限与超时；0.13.3–0.13.4 统一中文状态与投票消息结构；0.13.5 修复合并发送的节奏警告判定；0.13.6–0.13.10 重做报告页（深色作品面板、离线 SVG 图表、图册/列表切换、参与者评分表、封面策略与单文件资源去重）并升级 AI 总结输入；0.13.11 移除面板的报告预览、删除 111 条报告页遗留 CSS、修正窄屏历史表格与按钮点按尺寸，补充两个浏览器检查工具、`logo.png` 与 `tags`。

0.13.11 时点重新运行单元测试：共 140 项，139 项通过、1 项跳过（本机解释器缺 Pillow）。面板检查 `check_panel_ui.cjs` 覆盖 390/768/1440 × 四页 × 正常/空态/断连共 27 组，全部通过；报告页检查 `check_report_ui.cjs` 通过。真机在 AstrBot 4.28.0 上完成 45 张 / 17 人物 / 46 票的完整场次（发送、计票、报告、重新导出、下载均核对）。

本会话上一轮对报告排版做过本地浏览器验收：目录版与单文件版，320 / 390 / 640 / 900 / 1440px，单卡和三卡不溢出、不重叠，导航与图片弹窗可用，检查了明暗主题截图。该结果来自本地示例，不代表截图中真实历史报告已被重新导出。

`docs/IMPLEMENTATION_STATUS.md` 与 `docs/ARCHITECTURE.md` 已在 2026-09-16 对齐到 0.13.11；`docs/ROADMAP.md` 标注为历史路线图。历史验收记录基于不同版本，判断当前功能时仍应优先阅读代码与最新 CHANGELOG，不能把历史测试数或部署记录当成当前在线事实。

接手原则：

1. 保持人物投票口径、平台适配边界与共享应用服务，不另建重复业务入口。
2. 修报告查 `assets/report.*` 与 `report_generator.py`；修管理页查 `pages/image-vote/` 与 workspace 服务，别误改原型。
3. 已生成的报告是静态快照，更新插件源码不会自动更新历史 HTML；重新导出一次一场。正式上线前用户会清空旧测试数据，**不要**为旧报告/旧配置做兼容或批量重导。
4. 本地测试、隔离验收、真实群验证与部署完成应分别报告。
5. 迁移、生产数据清理、部署与群消息发送需按用户授权范围执行；本文不授予这些操作权限。
6. 报告预览入口已按用户要求移除，不要再加回来；历史报告只走下载。

## 9. 开发与参考入口

```bash
# 核心单元测试
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .

# 真实图片派生的示例报告（需要 Pillow）
python3 tools/generate_report_preview.py

# 隔离工作区验收（需要对应 AstrBot 源码）
python3 tools/check_workspace.py --astrbot-source <AstrBot源码目录>

# 大图处理检查
python3 tools/check_large_report.py
```

推荐阅读顺序：本文 → `README.md` → 最新 `CHANGELOG.md` → `src/models.py` → `src/application.py` → 所涉及的具体模块。需求背景查 `docs/REQUIREMENTS.md`，历史验收查 `docs/IMPLEMENTATION_STATUS.md`，后续方向查 `docs/ROADMAP.md`。
