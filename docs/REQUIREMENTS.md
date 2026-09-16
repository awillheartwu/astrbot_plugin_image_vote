# AstrBot QQ 群图片轮播投票插件——开发要求

> 历史需求／设计记录，不作为当前能力或操作授权依据。现行用法见 USER_GUIDE.md，资源管理见 DATA_MAINTENANCE.md，验收边界见 IMPLEMENTATION_STATUS.md。


> 建议插件名：`astrbot_plugin_image_vote`
>
> 文档目标：作为 AI / Agent 前期开发输入，优先完成一个可稳定运行的 MVP，再逐步增加 WebUI、复杂统计与多平台兼容。
>
> 初始目标平台：QQ 群，优先适配 `aiocqhttp / OneBot v11 / NapCat`。

## 0.13.0 人物投票口径（覆盖下文旧的逐图计票描述）

本节是当前实现的权威口径；下文保留的“当前图片计票、每人每图一票、逐图排名”等早期文字仅作为历史需求背景。

1. 扫描完成后先按人物分组。人物顺序取扫描结果中首次出现的位置；同一人物内部保持原扫描顺序。人物名优先使用 `project.json.characters`，否则按标题规则派生。
2. 同一人物的图片连续发送，图片之间不执行配置间隔。该人物第一张图片成功发送后，普通数字票立即归属此人物；在后续图片上传期间和最后一张后的等待期内，普通数字票都归属该人物。
3. 该人物最后一张图片发送完成后开始等待完整 `interval_seconds`，再清空当前投票目标并发送下一个人物。最后一个人物使用不短于人物间隔的 `final_grace_seconds`。
4. 引用本场任意已发送图片时，票归属图片对应的人物，不受当前人物限制。引用旧场次或非本插件图片不计票。
5. 唯一票口径为 `(session_id, character_name, voter_id)`：同一用户对同一人物只保留一票；重复投票由 `same_user_vote_policy` 决定最终值，默认最后一次生效。若评分范围包含 0，则 `0` 和 `0分` 均为有效票。
6. 某人物至少一张图片成功发送即可投票；全部图片发送失败时不开放该人物的普通数字投票。暂停与进程恢复保留当前人物及人物内部发送进度；提前结束按已发送图片和已收到的人物票结算。
7. 报告以人物为统计、排名和逐人评分单位。概览展示人物排名，「全部图片」把相同人物放入同一分组，图片本身不再单独计票或排名。
8. 固定周期设置已移除；人物模式的等待始终从该人物最后一张图片发送完成后开始，不扣除上传耗时。

---

## 1. 项目目标

开发一个 AstrBot 插件，用于在 QQ 群中对本地项目文件夹中的一批图片进行自动轮播投票。

管理员在群内执行：

```text
/vote <项目名>
```

插件需要：

1. 根据项目名定位输入文件夹。
2. 扫描并生成一个稳定、可复现的图片顺序。
3. 按设定的时间间隔，自动把图片逐张发送到当前 QQ 群。
4. 在投票过程中监听群消息，将合法的纯数字消息计入当前图片的投票。
5. 支持用户通过“引用某一张由插件发送的投票图片 + 数字”对之前的图片进行投票或修改投票。
6. 全部图片结束后自动汇总结果。
7. 可选调用 AstrBot 当前可用 LLM，对统计结果生成自然语言总结。
8. 生成一个固定模板的 HTML 报告。
9. HTML 报告中的图片应自动压缩，避免直接复制原始大图导致报告体积过大。
10. 输入目录、输出目录、轮播间隔、压缩参数等必须可配置。
11. 输出内容必须可以单独清理，且不得误删原始图片。

---

## 2. 开发环境与兼容性

### 2.1 AstrBot

当前使用环境截图中 AstrBot 显示为 `4.4.0`，因此开发时不要默认所有最新 AstrBot API 都存在。

要求：

- MVP 尽量兼容 AstrBot `4.4.x`。
- 对较新版本 API 做适配层，不把版本差异散落在业务代码中。
- 如果某个功能只能在较新版本 AstrBot 实现，应：
  - 做版本检查；
  - 给出明确日志；
  - 降级而不是让整个插件加载失败。
- 插件命令执行后应避免无意义调用默认 LLM，例如命令处理时使用当前版本支持的方式关闭默认 LLM 响应。

### 2.2 首期平台

首期只要求：

```text
aiocqhttp / OneBot v11 / NapCat / QQ 群
```

原因：

- 本插件强依赖群消息监听；
- 需要处理 QQ 引用回复；
- 需要获取被引用消息的内容；
- 不同消息平台的 Reply 语义差异较大。

架构上不得把 OneBot 特殊逻辑写死到统计核心中，应通过 `QQReplyResolver` / `PlatformAdapter` 一类适配器隔离。

---

## 3. 参考 AstrBot 插件设计

开发时可参考但不要直接复制以下项目代码：

### 3.1 AstrBot 官方插件开发文档

- 插件开发指南：
  - https://docs.astrbot.app/dev/star/plugin-new.html
- 接收消息事件：
  - https://docs.astrbot.app/dev/star/guides/listen-message-event.html
- 发送消息：
  - https://docs.astrbot.app/dev/star/guides/send-message.html
- AI 调用：
  - https://docs.astrbot.app/dev/star/guides/ai.html
- Plugin Pages：
  - https://docs.astrbot.app/en/dev/star/guides/plugin-pages.html

### 3.2 群发言统计插件

仓库：

```text
https://github.com/xiaoruange39/astrbot_plugin_message_stats
```

可参考点：

- `@filter.event_message_type(EventMessageType.ALL)` 监听群消息；
- 指令权限控制；
- 后台异步任务；
- 缓存与持久化；
- 临时文件清理；
- `_conf_schema.json` 配置方式。

### 3.3 群分析总结插件

仓库：

```text
https://github.com/SXP-Simon/astrbot_plugin_qq_group_daily_analysis
```

可参考点：

- `main.py` 只承担插件接入与编排，复杂逻辑放入 `src/`；
- application / domain / infrastructure 分层；
- LLM 分析封装；
- HTML 报告生成；
- HTML 输出目录可配置；
- SQLite / checkpoint / history 等持久化思路；
- 后台任务管理与插件卸载时取消任务；
- Plugin Page 管理界面。

---

## 4. 输入项目与图片命名规则

插件必须兼容目前已有的两类文件名。

### 4.1 类型 A：带显式序号

示例：

```text
screenshot0001 - Alice - a1b2c3d4.png
screenshot0002 - Alex - b2c3d4e5.png
screenshot0003 - Alex - c3d4e5f6.png
screenshot0004 - Alice - d4e5f6a7.png
screenshot0019 - Bonnie - e5f6a7b8.png
```

推荐识别正则：

```regex
^screenshot(?P<seq>\d+)\s*-\s*(?P<title>.+?)\s*-\s*(?P<suffix>[0-9A-Za-z]+)\.(?P<ext>png|jpg|jpeg|webp|gif)$
```

对于此类型：

- `seq` 为首要排序依据；
- 必须按整数排序，不能按字符串排序；
- `0002` 必须在 `0010` 前；
- 中间的人物名只作为展示信息，不作为唯一 ID；
- 最后 hash/随机串只作为原始文件信息，不依赖它作为业务 ID。

### 4.2 类型 B：普通描述文件名

示例：

```text
Carol-Bella的兄弟.png
Doris-宫廷服饰.png
Elena-红发造型.png
Fiona-议会礼服.png
Grace-白色礼服.png
Grace-老年版本.png
Grace-现代版本.png
Helen-Carol和Doris的女儿.png
Iris-废土风格.png
```

注意：

**不要假设第一个 `-` 前一定是完整人物名。**

例如：

```text
Carol-Bella的兄弟.png
Helen-Carol和Doris的女儿.png
```

文件名内部本身可能包含人物名或多个名称，因此此模式默认只把完整 stem 当作 `display_title`。

对于此类型：

- 默认使用自然排序（natural sort）；
- 必须保证每次扫描同一目录得到相同顺序；
- 不使用文件修改时间作为默认排序依据；
- 后续允许通过 manifest 手动指定顺序。

### 4.3 混合命名

若一个文件夹同时存在 A/B 两类：

建议排序策略：

1. 能识别明确 `screenshot<number>` 的文件按数字顺序；
2. 其他文件按自然文件名顺序；
3. 扫描完成后为所有图片生成最终连续 `display_index = 1..N`。

但更推荐：

- 如果项目为混合命名，扫描时输出 warning；
- 支持 `project.json` / `manifest.json` 显式覆盖顺序。

---

## 5. 项目组织方式

### 5.1 输入根目录

配置：

```text
input_root
```

例如：

```text
/data/image_vote/projects
```

目录：

```text
/data/image_vote/projects/
├── game_a/
│   ├── screenshot0001 - Alice - a1b2c3d4.png
│   ├── screenshot0002 - Alex - b2c3d4e5.png
│   └── ...
├── game_b/
│   ├── Grace-现代版本.png
│   └── ...
└── project_alias.json
```

### 5.2 项目名解析

执行：

```text
/vote game_a
```

解析优先级：

1. 先查项目登记表（§5.4）；
2. 再查项目别名配置；
3. 再查 `input_root/game_a` 文件夹；
4. 找不到时报错并显示 `/vote list` 可用项目。

建议支持项目别名：

```json
{
  "一期角色": "game_a",
  "二期角色": "game_b"
}
```

### 5.3 可选项目 manifest

每个项目目录允许存在：

```text
project.json
```

示例：

```json
{
 "name": "game_b 角色投票",
 "sort_mode": "natural",
 "interval_seconds": 20,
 "description": "角色图投票",
  "files": [],
  "characters": {
    "Aurora": ["Aurora-现代版本.png", "Aurora-老年版本.png"]
  }
}
```

后续可通过 `files` 显式指定顺序，但 MVP 可以先只实现自动扫描。

---

### 5.4 项目登记表（任意目录）

`input_root` 只覆盖「根目录下一层子目录」这一种布局。真实图库常常层级很深、分散在不同路径，因此插件支持一份管理员维护的登记表，把项目名映射到容器内的任意绝对路径。

文件位置：插件数据目录下的 `projects.json`，与 `vote.db` 同级（通常已被 bind mount 出来，可以直接编辑）。

```json
{
  "version": 1,
  "projects": {
    "海滨之家": {
      "path": "/pictures/08_SLG/00XX_海滨之家/人物图",
      "interval_seconds": 5,
      "recursive": false,
      "description": "角色图投票"
    }
  }
}
```

- 键名即 `/vote <名字>` 使用的项目名，可以与文件夹名不同。
- `path` 必须是容器内绝对路径。宿主机目录要先通过 volume 映射进容器；推荐一次挂载图库根目录（例如 `/volume1/05_Pictures:/pictures:ro`），之后任意层级都能用。
- `interval_seconds`、`recursive`、`description` 可选，`interval_seconds` 覆盖该项目的默认发送间隔。
- 解析优先级高于别名与 `input_root`。
- 文件按修改时间自动重载，外部编辑后不需要重载插件。

维护方式：

- 群内管理员指令：`/vote register <项目名> <容器内绝对路径>`、`/vote unregister <项目名>`、`/vote projects`（列出登记项与路径）。
- 直接编辑 `projects.json`。
- 后续 Plugin Pages 管理页面提供目录浏览器与同样的增删改，写同一份文件。

安全边界：登记只对 AstrBot 管理员开放；项目路径来自管理员登记，因此允许位于 `input_root` 之外（§26 的例外）；登记与解析都会校验目录存在；`/vote check` 对登记项目只显示名称，绝对路径只在管理员的 `/vote projects` 中呈现。

## 6. 图片扫描规则

默认支持：

```text
.png
.jpg
.jpeg
.webp
.gif
```

MVP 可不支持动态图动画保留，GIF 在报告中可以原样引用或转静态 WebP 首帧；群发送时按平台能力处理。

扫描要求：

- 默认只扫描项目文件夹第一层；
- `recursive_scan` 可配置，默认 `false`；
- 忽略隐藏文件；
- 忽略报告输出目录；
- 忽略临时文件；
- 扫描开始时建立快照；
- 投票进行期间即使文件夹有新增/删除，也不改变当前 session；
- 每张图生成稳定 `candidate_id`，不要只依赖数组 index。

建议：

```text
candidate_id = sha1(relative_path + file_size + mtime_ns)
```

或者数据库 UUID，但报告中保留 `source_relative_path`。

---

## 7. 指令设计

为了兼容 AstrBot 4.4.x，MVP 可以只注册一个 `/vote` 指令并在内部解析参数，而不是强依赖新版本复杂 command group API。

### 7.1 必须指令

```text
/vote <项目名>
/vote list
/vote check <项目名>
/vote status
/vote pause
/vote resume
/vote stop
/vote finish
/vote export
/vote cleanup <项目名|session_id|all>
/vote reloadconfig
```

### 7.2 指令行为

所有控制类指令（`/vote pause`、`/vote resume`、`/vote finish`、`/vote stop`）执行后必须在群里回复一条确认消息，内容包括：触发的是哪条指令、项目名、当前进度（已发送 / 总数）、会话状态，以及下一步该怎么做（继续 / 导出 / 无需操作）。找不到进行中或可恢复的会话时，也要给出明确的中文说明，而不是直接抛出异常文本。

#### `/vote <项目名>`

开始投票。

开始前必须检查：

- 当前是否为群聊；
- 当前用户是否有权限；
- 当前群是否已有投票；
- 项目目录是否存在；
- 是否至少存在 1 张合法图片；
- 输出目录是否可写。

回复示例：

```text
已开始投票：game_a
图片数量：126
发送间隔：20 秒
评分范围：1-4
预计耗时：约 42 分钟
```

#### `/vote check <项目名>`

不启动投票，只做预检。

输出：

- 项目路径；
- 图片数量；
- 原始总大小；
- 命名类型统计；
- 排序方式；
- 首 5 张文件；
- 最后 5 张文件；
- 非法文件；
- 预计耗时；
- 预计报告图片压缩体积区间（仅估算）。

#### `/vote status`

输出：

```text
项目：game_a
状态：RUNNING
进度：37 / 126
当前：#037 Iris-废土风格
本图已投：18 人
总投票：621
下一张：12 秒后
```

#### `/vote pause`

- 暂停轮播；
- 已发送图片仍允许引用投票；
- 当前窗口不自动切换。

#### `/vote resume`

- 从暂停点继续；
- 不重复发送已经发送成功的图片。

#### `/vote stop`

- 取消当前任务；
- 保留已经收到的数据；
- 状态记为 `CANCELLED`；
- 不自动生成完整最终排名，除非额外执行 export。

#### `/vote finish`

- 立即停止后续图片发送；
- 进入 FINALIZING；
- 根据现有票数生成结果。

#### `/vote export`

- 对最近一个完成/取消 session 重新生成 HTML；
- 不重新调用 AI，除非指定 `--ai` 或配置允许。

#### `/vote reloadconfig`

- 重新读取插件配置并打印当前实际生效的值：发送间隔、最后一张额外等待、评分范围、报告模式、结束通知与自动报告开关、报告是否发群、AI 总结开关；
- 用于确认 WebUI 里保存的配置有没有传到运行中的插件（配置来源也会一并打印）；
- 仅管理员可用。

---

## 8. 权限要求

默认：

- `/vote <project>`：仅 AstrBot 管理员；
- pause/resume/stop/finish/cleanup：仅 AstrBot 管理员；
- status：所有群成员可用；
- 投票数字：所有普通群成员可用。

配置项：

```text
admin_only_start = true
allowed_group_ids = []
```

如果 `allowed_group_ids` 非空，只允许指定 QQ 群使用。

---

## 9. 投票轮播状态机

建议状态：

```text
IDLE
PREPARING
RUNNING
PAUSED
FINALIZING
COMPLETED
CANCELLED
FAILED
```

核心流程：

```text
/vote project
    ↓
PREPARING
    ↓
扫描目录 + 建立候选快照 + 建 session
    ↓
RUNNING
    ↓
发送 candidate #1
    ↓
等待 interval_seconds
    ↓
关闭普通窗口 #1，发送 #2
    ↓
...
    ↓
发送最后一张
    ↓
等待 final_grace_seconds
    ↓
FINALIZING
    ↓
统计 → AI 可选总结 → HTML
    ↓
COMPLETED
```

间隔语义：同一人物内图片连续发送，最后一张发送完成后等待完整 `interval_seconds` 秒；最后一个人物按 `final_grace_seconds` 等待，不扣除发送耗时。

---

## 10. 图片发送格式

每张图片必须带有一个可被引用解析的稳定文本标记。

推荐同一条消息发送：

```text
[投票 037/126]
Iris-废土风格
请回复 1-4 评分
```

+ 图片。

内部最好额外存在可识别标记，例如：

```text
[VOTE:sessionShortId:37]
```

如果不希望暴露内部 ID，可以仅依靠：

```text
[投票 037/126]
```

但应同时校验 session，避免用户引用上一次投票的历史消息造成串 session。

推荐实际展示：

```text
[投票 037/126 · A7F3]
海滨之家 · Iris-废土风格
回复 1-4 评分；也可引用之前的投票图重新评分
```

其中 `A7F3` 为当前 session 短 ID，第二行是「项目名 · 图片标题」。

人类可读标记自身已经包含短 ID 与图片序号，引用解析只依赖它：引用旧图、改分、跨 session 校验都基于这一行。早期版本额外发送的 `[VOTE:短ID:序号]` 机器标记因此成为冗余，新消息不再发送；解析器仍然兼容历史消息里的该标记。

### 10.1 发送 API

优先使用 AstrBot 标准消息链：

```python
MessageChain().message(...).file_image(path)
```

主动轮播应基于启动命令时保存的：

```text
event.unified_msg_origin
```

通过：

```python
self.context.send_message(umo, chain)
```

发送，不依赖原始 event 一直存活。

---

## 11. 投票识别规则

这是本插件最重要的业务规则，必须严格测试。

### 11.1 普通投票与评分制

评分制由 `score_min` / `score_max` 配置，默认 `1-4`，同样支持 `1-5`、`1-10` 这类满分制，上限 100。配置改动后群消息提示与报告标签必须跟着变，不允许写死。

合法投票文本（以 `1-10` 为例）：

```text
1
2
...
10
```

允许消息前后空白：

```text
 3
```

判定前先做 NFKC 归一化再 strip，所以全角数字 `３` 等价于 `3`。

以下全部无效（以 `1-4` 为例）：

```text
0
5
03
3分
评分3
3.0
1 2
👍3
10
```

规则要点：

- 可接受的位数由 `score_max` 决定：`1-4` 只接受 1 位，`1-10` 接受 1-2 位。
- 多位数带前导零视为无效（`03`、`05` 都不计票），避免与两位数制混淆。
- 超出范围、超出位数、含其他字符的消息一律忽略：不回复、不报错、不写库。
- 会话创建时把当时的评分范围写进 session，历史报告按当时的范围渲染。

### 11.2 普通窗口归属

若消息：

- 为合法纯数字；
- 没有引用其他候选图片；
- 当前群有 RUNNING / PAUSED session；

则计给“当前 active candidate”。

当前 candidate 定义为：

```text
最近一次成功发送、尚未被下一张图片替换为普通窗口目标的候选图
```

### 11.3 引用投票——重要例外

用户可以：

```text
引用之前由插件发送的某张投票图片
然后只发送：
4
```

此时：

- 不把票记给当前图片；
- 尝试从 Reply 组件中解析被引用消息；
- 如果被引用消息中含当前 session 的投票标记，则将分数路由到对应 candidate；
- 即使该 candidate 的普通时间窗口已经过去，也允许投票/改票；
- 引用非本插件投票图片时，不计票；
- 引用其他历史 session 的图片时，不计票，并可静默忽略。

推荐：

```text
quoted_vote_policy = route_to_quoted_candidate
```

### 11.4 Reply 解析策略

OneBot / AstrBot 当前适配器通常会把引用消息解析为 `Reply` 组件，并尝试通过 `get_msg` 回查原消息。

优先级：

1. 读取 AstrBot `Reply.chain` / `Reply.message_str`；
2. 解析 `[投票 xx/xx · sessionShortId]` 标记；
3. 若当前 AstrBot 版本 Reply 内容不足，则在 OneBot adapter 层使用原始 reply message id 调 `get_msg`；
4. 解析失败时不能崩溃，只记录 debug/warning 并按“无效引用票”处理。

**不要强依赖机器人主动发图后立即取得 message_id。**

更稳妥的做法是让被引用消息自身包含可解析 candidate/session 标记。

### 11.5 同一用户重复投票

配置项 `same_user_vote_policy`，可选值：

```text
last_wins   最后一次生效（默认）
first_wins  保留最早一次
max_score   取最高分
min_score   取最低分
```

语义统一为「同一用户对同一 candidate 只保留一票」，四个策略只决定这一票如何取值；后到的投票不会增加票数。`last_wins` 覆盖旧值，`first_wins` 保留首次的分数与来源，`max_score` / `min_score` 取更高或更低分，来源与 message_id 跟随胜出的那一次，`updated_at` 仅在真的发生变化时更新。

数据库唯一键：

```text
(session_id, candidate_id, voter_id)
```

使用 UPSERT。

记录：

- 首次投票时间；
- 最后修改时间；
- 当前分数；
- 来源：`current_window` / `quoted_reply`；
- 原始 message_id（若可获取）。

### 11.6 最后一张图

最后一张发出后必须额外等待：

```text
final_grace_seconds
```

默认：

```text
max(interval_seconds, 20)
```

再结束 session，避免最后一张几乎没有投票时间。

### 11.7 特殊情况与处理策略

| 场景 | 当前行为 | 策略说明 |
| --- | --- | --- |
| 两张图之间发无意义内容（文字、表情、图片） | 不计票 | 只有归一化后严格等于范围内数字的消息进入计票分支，其余静默忽略 |
| 发超出范围的数字（1-4 时发 5、0） | 不计票 | 解析在范围校验处返回空 |
| 发超出位数的数字（1-4 时发 10） | 不计票 | 位数上限由 `score_max` 决定 |
| 全角数字 `３` | 计票 | NFKC 归一化后按 3 处理 |
| 前导零 `03` | 不计票 | 避免与两位数制混淆 |
| 同一用户在同一张图连发多个数字 | 最后一次生效 | UPSERT 覆盖旧值 |
| 窗口切走后想给上一张打分 | 计给当前图 | 需要引用上一张的投票图再发数字；这是「普通数字归属当前图」的直接后果 |
| 引用非本插件消息 | 不计票 | 解析不到本 session 标记即放弃 |
| 引用其他历史 session 的投票图 | 不计票 | 短 ID 校验不通过 |
| 引用本 session 的投票图 | 计给被引用图 | 即使该图窗口已过 |
| 暂停期间投票 | 允许 | PAUSED 仍接受窗口票与引用票 |
| FINALIZING / COMPLETED 之后的迟到票 | 忽略 | 路由只接受 RUNNING 与 PAUSED |
| 私聊发数字 | 忽略 | 只监听群消息 |
| 机器人自己发出的数字 | 不计票 | 监听入口比对 `self_id` 后跳过 |
| 发送失败的图片 | 不作为投票目标 | 窗口票落在最近一次成功发送的图片上（`active_candidate_id`） |
| 连续多张发送失败 | 达到阈值自动暂停并提示管理员 | 阈值由 `send_failure_pause_threshold` 配置，默认 3，0 表示关闭；`/vote resume` 可继续 |
| 短 ID 碰撞 | 概率可忽略 | 短 ID 为 8 位十六进制（约 43 亿种）；4 位的历史会话仍能正常解析 |

---

## 12. 群消息监听要求

使用群消息监听器：

```text
EventMessageType.GROUP_MESSAGE
```

处理流程必须尽量轻量：

```text
收到群消息
→ 当前群是否有活动 session？
→ 文本是否严格为 1-4？
→ 有无 Reply？
→ resolve target candidate
→ SQLite UPSERT
→ return
```

不要在每一条群消息上：

- 扫描磁盘；
- 加载图片；
- 调 LLM；
- 重算全部统计；
- 生成报告。

### 12.1 是否回复“投票成功”

默认不要每票回复，避免刷屏。

配置：

```text
ack_vote = false
```

如果开启，可使用 reaction 或简短回复，但 MVP 不要求。

---

## 13. 并发与任务控制

要求：

- 同一个 QQ 群同一时刻只能有一个 active vote session；
- 不同群可以同时运行各自 session；
- 同一项目可被不同群同时使用；
- 每个群有独立 `asyncio.Task`；
- task 必须可 pause / resume / cancel；
- 插件 reload / terminate 时必须取消后台 task；
- 禁止 orphan task；
- 发送失败应有限次数重试；
- 单张图片失败不能导致整个 session 数据损坏。

推荐发送重试：

```text
max_send_retries = 3
retry_backoff = 2s, 5s, 10s
```

若某图最终发送失败：

- candidate 状态记为 `send_failed`；
- 继续下一张或根据配置暂停；
- 最终报告显示“发送失败/无投票”。

---

## 14. 重启恢复

必须考虑 AstrBot 重载插件、Docker 重启、机器重启。

MVP 推荐策略：

- session/candidate/vote 持久化到 SQLite；
- 当前进度也持久化；
- 插件启动后发现未完成 session：
  - 默认恢复为 `PAUSED_RECOVERED` / `PAUSED`；
  - 不自动继续发图；
  - 群管理员执行 `/vote resume` 后继续。

配置可增加：

```text
auto_resume_after_restart = false
```

默认必须为 false，避免机器人重启后突然在群内刷图。

---

## 15. 持久化设计

推荐 SQLite：

```text
data/plugin_data/astrbot_plugin_image_vote/vote.db
```

如果当前 AstrBot 版本有标准插件数据目录 API，应优先使用框架提供的方法获取路径，不硬编码绝对路径。

### 15.1 sessions

字段建议：

```text
id
short_id
group_id
umo
project_name
project_path
status
interval_seconds
final_grace_seconds
current_index
candidate_count
created_at
started_at
finished_at
output_path
ai_summary
error_message
```

### 15.2 candidates

```text
id
session_id
display_index
source_relative_path
source_filename
display_title
sequence_number
source_size
send_status
sent_at
```

### 15.3 votes

```text
id
session_id
candidate_id
voter_id
voter_name
score
source_type
message_id
created_at
updated_at
```

唯一索引：

```text
UNIQUE(session_id, candidate_id, voter_id)
```

---

## 16. 统计规则

每张图至少生成：

```text
vote_count
average_score
score_1_count
score_2_count
score_3_count
score_4_count
score_distribution
std_dev 或 variance（可选）
```

项目汇总：

```text
total_candidates
total_valid_votes
unique_voters
average_votes_per_candidate
overall_average_score
```

### 16.1 排名规则

默认：

1. `average_score` 降序；
2. 同分时 `vote_count` 降序；
3. 再同分时 `display_index` 升序。

### 16.2 角色维度统计

一个项目里可能有多张图属于同一个人物，因此除按图统计外，再做一份按角色的合并统计：同一角色的所有图片的票合并计算 `vote_count`、`average_score`、`score_distribution`，并给出角色排名（规则同 §16.1，同分按角色名）。

角色归属规则：

1. 默认取展示标题里第一个短横线之前的部分（`Aurora-现代版本` → `Aurora`、`Azalia-Isis和Elis的女儿` → `Azalia`）；
2. 项目目录的 `project.json` 可以用 `characters` 显式覆盖：`{"角色名": ["文件名", ...]}`，未列出的文件仍走默认规则；
3. 投票与单图排名不变，角色统计只是额外的一份视图；当角色数与图片数相同（没有合并发生时）报告不显示该区块。

必须明确：

- 0 票图片不要计算为 0 分参与正常排名；
- 0 票图片单独显示 `无投票`。

---

## 17. AI 总结

AI 是可选增强功能，不得成为最终结果生成的强依赖。

### 17.1 输入给 AI 的内容

默认只发送结构化统计数据和文件标题，例如：

```json
{
  "project": "game_a",
  "total_candidates": 126,
  "unique_voters": 32,
  "top": [
    {"name": "Grace-现代版本", "avg": 3.84, "votes": 28}
  ],
  "bottom": [],
  "high_disagreement": []
}
```

**不要把 500 MB 图片整体发送给 LLM。**

MVP AI 只做“统计总结”，不做视觉理解。

未来可增加：

```text
ai_vision_top_n = 0
```

仅对 Top N 图片做视觉分析，但不是 MVP。

### 17.2 模型调用

优先：

- 使用当前群当前 AstrBot 会话配置的 provider；
- 若用户在配置中指定 provider_id，则优先指定；
- 新版 AstrBot 可封装 `get_current_chat_provider_id()` + `llm_generate()`；
- AstrBot 4.4.x 使用兼容 wrapper；
- AI 调用失败时仍正常生成统计 HTML。

### 17.3 AI 输出要求

建议生成：

- 总体参与度；
- 最受欢迎 Top 5；
- 最具争议 Top 3；
- 低分项；
- 简短结论。

禁止让 AI 修改原始统计数字。

---

# 18. HTML 报告设计

## 18.1 强烈建议：默认不是“单个 Base64 巨型 HTML”

一个项目原图可能达到约 `500 MB`。

**默认绝对不要把所有原图直接 Base64 内嵌进单个 HTML。**

原因：

1. Base64 本身通常增加约 33% 体积；
2. 浏览器打开时会产生更大的内存压力；
3. 一个几百 MB 的 HTML 很难传输、预览和缓存；
4. 每次重生成都要重写整份巨型文件；
5. 清理和增量处理也更差。

### 推荐默认报告模式

```text
report_mode = directory
```

输出：

```text
<output_root>/
└── game_a/
    └── 2026-09-11_A7F3/
        ├── index.html
        ├── data.json
        ├── assets/
        │   ├── report.css
        │   └── report.js
        └── images/
            ├── 0001.webp
            ├── 0001_thumb.webp
            ├── 0002.webp
            ├── 0002_thumb.webp
            └── ...
```

HTML 使用相对路径：

```html
<img src="./images/0001.webp" loading="lazy">
```

这样整个文件夹可以：

- 直接打开；
- 打包 zip；
- Nginx 静态托管；
- 直接删除整个 session 文件夹完成清理。

---

## 18.2 图片自动压缩

要求生成报告时创建报告专用副本，不修改原图。

默认参数建议：

```text
report_image_format = webp
report_image_max_width = 1920
report_image_max_height = 1920
report_image_quality = 82
thumbnail_width = 480
thumbnail_quality = 72
strip_metadata = true
```

处理原则：

- 原图小于最大尺寸时不放大；
- PNG 截图优先转 WebP；
- 保持宽高比；
- EXIF / 无关 metadata 默认移除；
- HTML 列表加载 thumbnail；
- 点击后加载 1920px 主图；
- 使用 `loading="lazy"`；
- 不默认复制原始 4K PNG。

对于游戏截图，500 MB 的 PNG 原图经过 1920px WebP 80~85 质量压缩后，通常会显著下降，但最终大小取决于图片数量和细节，不能硬编码承诺固定压缩率。

### 处理库

MVP：

```text
Pillow
```

即可。

不要为了这个需求引入完整浏览器截图链路或重量级视频库。

---

## 18.3 单 HTML 模式

可以支持，但必须为可选模式：

```text
report_mode = single_html
```

实现方式：

- 先把图片压缩成 WebP；
- 再转换 Base64 data URI；
- 只嵌入“压缩后图片”，绝不嵌入原图。

必须设置硬限制：

```text
single_html_max_mb = 50
```

如果预估或实际超过上限：

```text
自动回退到 directory 模式
```

并记录：

```text
单文件报告超过限制，已自动生成目录式报告。
```

单文件报告可以通过 `send_report_html` 配置在结束时作为附件发到投票群；目录模式不发送文件，报告仍在 `output_root` 下。

单文件模式成功内嵌后会删除 `report.css`、`report.js` 与 `images/`（这些是目录模式的附属产物），报告目录里只保留 `index.html`、`data.json` 与 marker，`data.json` 里会写明 `report_mode = single_html`。

---

## 18.4 输出目录可指定

必须提供配置：

```text
output_root
```

例如：

```text
/data/image_vote/reports
```

或 Windows 原生部署：

```text
D:\AstrBotVoteReports
```

注意：

**路径必须是 AstrBot 进程实际能访问的路径。**

如果 AstrBot 运行在 Docker 中，Windows/NAS 的宿主机目录必须先通过 volume bind mount 映射到容器内，例如：

```yaml
volumes:
  - /volume1/vote-projects:/vote/projects:ro
  - /volume1/vote-reports:/vote/reports
```

插件配置：

```text
input_root = /vote/projects
output_root = /vote/reports
```

这样宿主机上可以直接：

```text
/volume1/vote-reports
```

统一管理、备份、删除。

---

## 19. 报告清理安全要求

这是必须项。

### 19.1 永远不要自动删除 input_root

插件只能清理：

```text
output_root
```

下由本插件创建的 session 目录。

### 19.2 每个报告目录写入标记文件

例如：

```text
.astrbot_image_vote_report
```

内容：

```json
{
  "plugin": "astrbot_plugin_image_vote",
  "session_id": "..."
}
```

执行 cleanup 时必须同时满足：

1. 目标路径位于 `output_root` 内；
2. 目录存在 marker；
3. marker plugin 名匹配；
4. 不允许 `..` path traversal；
5. 不允许删除 output_root 自身；
6. 不允许通过 symlink 越界。

### 19.3 清理指令

```text
/vote cleanup <session_id>
/vote cleanup <project>
/vote cleanup all
```

建议 `all` 需要二次确认或配置开关。

可选自动清理：

```text
auto_cleanup_reports = false
report_retention_days = 30
```

默认关闭。

---

## 20. HTML 页面内容

固定 HTML 至少包含：

### 顶部概要

- 项目名；
- Session ID；
- 投票群；
- 开始/结束时间；
- 图片数量；
- 总有效票；
- 独立参与人数；
- AI 总结（若有）。

### 排名区

至少：

```text
排名
缩略图
名称
平均分
投票人数
1票数量
2票数量
3票数量
4票数量
```

### 图片详情区

每项：

- 图片；
- 原文件名；
- 平均分；
- 投票数；
- 1~4 分布条；
- 排名；
- 可选投票人昵称列表。

### 前端要求

- 无外部 CDN 依赖；
- CSS/JS 与报告一起输出；
- 支持深色模式；
- 图片 lazy load；
- 可以本地 `file://` 打开；
- 搜索/筛选可选；
- 默认按排名排序，可切换原始顺序。

---

## 21. 推荐配置项

建议 `_conf_schema.json` 至少提供以下配置。

### 路径

```text
input_root: string
output_root: string
recursive_scan: bool = false
```

### 投票

```text
default_interval_seconds: int = 20
final_grace_seconds: int = 20
score_min: int = 1
score_max: int = 4
same_user_vote_policy: string = "last_wins"
allow_quoted_vote_after_window: bool = true
ack_vote: bool = false
```

### 权限

```text
admin_only_start: bool = true
allowed_group_ids: list[string] = []
```

### 图片报告

```text
report_mode: string = "directory"
report_image_format: string = "webp"
report_image_max_width: int = 1920
report_image_max_height: int = 1920
report_image_quality: int = 82
thumbnail_width: int = 480
thumbnail_quality: int = 72
strip_metadata: bool = true
single_html_max_mb: int = 50
```

### AI

```text
ai_summary_enabled: bool = true
ai_provider_id: string = ""
ai_top_n: int = 5
ai_bottom_n: int = 3
```

### 结束通知与自动报告

```text
notify_on_finish: bool = true
auto_report_on_finish: bool = true
send_report_html: bool = false
```

- `notify_on_finish`：结束时在投票群发一条提醒，内容包含项目名、图片数（含已发送张数）、有效票与参与人数；报告生成成功或失败时会再补一条。默认开启。
- `auto_report_on_finish`：结束时自动生成报告。关闭后会话照常结束但不生成报告，需要时由管理员执行 `/vote export`；大项目可以先关掉，挑合适的时间手动导出。默认开启。
- 这两个开关只影响收尾行为，不影响计票与持久化。
- `send_report_html`：仅在 `report_mode = single_html` 时生效，开启后把生成的单文件报告作为附件发到投票群，方便群成员直接下载。默认关闭。
- 配置读取顺序：构造参数 → `astrbot_config_mgr` → 磁盘上的 `<data>/config/<插件名>_config.json` → 插件实例属性 → `context.get_config()`。WebUI 保存后会更新配置文件，因此运行中的插件在收到下一条指令时会自动采用新值，不必重载插件。

### 恢复/清理

```text
auto_resume_after_restart: bool = false
auto_cleanup_reports: bool = false
report_retention_days: int = 30
```

### 稳定性

```text
max_send_retries: int = 3
send_retry_base_seconds: int = 2
send_failure_pause_threshold: int = 3
```

---

## 22. 推荐代码结构

不要把所有代码写在 `main.py`。

推荐：

```text
astrbot_plugin_image_vote/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── requirements.txt
├── README.md
├── CHANGELOG.md
├── src/
│   ├── config.py
│   ├── models.py
│   ├── project_scanner.py
│   ├── project_service.py
│   ├── session_manager.py
│   ├── vote_collector.py
│   ├── message_sender.py
│   ├── reply_resolver.py
│   ├── statistics_service.py
│   ├── ai_summary_service.py
│   ├── persistence.py
│   ├── image_processor.py
│   ├── report_generator.py
│   └── path_guard.py
├── templates/
│   └── report.html.j2
├── assets/
│   ├── report.css
│   └── report.js
└── tests/
    ├── test_filename_parser.py
    ├── test_project_scanner.py
    ├── test_vote_parser.py
    ├── test_quote_resolver.py
    ├── test_vote_upsert.py
    ├── test_statistics.py
    ├── test_path_guard.py
    └── test_report_generator.py
```

### main.py 只做

- 插件初始化；
- command 注册；
- group message listener；
- 依赖实例化；
- 生命周期；
- AstrBot API 接入。

业务逻辑全部放 `src/`。

---

## 23. 推荐依赖

`requirements.txt`：

```text
Pillow>=10
Jinja2>=3.1
aiosqlite>=0.20
```

若 AstrBot 自身已经提供兼容版本，可以避免重复锁死过高版本。

不建议 MVP 引入：

- Playwright；
- Chromium；
- pandas；
- numpy（标准差可纯 Python）；
- FastAPI 独立服务器；
- Redis；
- Celery。

该插件完全可以保持轻量。

---

## 24. 性能要求

500 MB 指的是输入图片总体积，不应该一次性读入内存。

要求：

- 扫描阶段只读文件 metadata；
- 发群时一次只处理/发送当前图片；
- 报告压缩逐文件处理；
- 一张处理完及时释放 Image 对象；
- 不把所有图片 bytes 放入 Python list；
- HTML directory 模式不 Base64；
- SQLite 操作异步或极短事务；
- 投票 listener 不阻塞事件循环。

图片压缩可通过：

```python
await asyncio.to_thread(process_image, ...)
```

放到线程池，避免 Pillow CPU 工作阻塞主 event loop。

可以使用 semaphore 限制报告生成并发：

```text
image_process_concurrency = 2~4
```

不要一次并发压缩几十张 4K 图。

---

## 25. 日志要求

日志分级：

### INFO

- session 创建；
- 项目数量；
- 开始/暂停/恢复/结束；
- 报告路径；
- AI 是否调用成功。

### DEBUG

- 每张图发送；
- 每一票 target candidate；
- quote resolver 结果；
- 图片压缩前后大小。

### WARNING

- 无法解析引用；
- 图片发送重试；
- 文件命名混合；
- 单 HTML 超限自动 fallback。

### ERROR

- SQLite 错误；
- 文件损坏；
- 最终报告生成失败；
- 路径安全检查失败。

默认不在 INFO 中打印完整 QQ 号 + 每票详情，避免日志污染。

---

## 26. 安全要求

必须：

- 所有用户输入的 project 名做 path sanitize；
- 使用 `Path.resolve()` 后校验仍位于 `input_root`；
- 禁止 `../`；
- 禁止通过绝对路径绕过 root，除非项目路径来自管理员配置；
- output cleanup 必须有 path guard；
- symlink 需要额外校验；
- 不允许群成员通过命令读取任意本地文件；
- report 里的文件名要 HTML escape；
- AI prompt 中的文件名作为数据，不作为系统指令；
- 不把原始绝对路径暴露到群消息或 HTML，默认只显示相对文件名。

---

## 27. 测试用例——必须覆盖

### 27.1 文件排序

输入：

```text
screenshot0002 - MC - a.png
screenshot0010 - Alice - b.png
screenshot0001 - MC - c.png
```

输出顺序：

```text
1
2
10
```

### 27.2 类型 B

输入：

```text
Grace-现代版本.png
Grace-白色礼服.png
Carol-Bella的兄弟.png
```

每次扫描顺序必须一致。

### 27.3 合法票

```text
"1" → true
" 4 " → true
"0" → false
"5" → false
"3分" → false
"03" → false
```

### 27.4 当前窗口

- #10 当前图；
- 用户发 `3`；
- 应记录 #10 = 3。

### 27.5 引用旧图

- 当前图 #10；
- 用户引用 #3 的机器人投票消息并发送 `4`；
- 必须记录 #3 = 4；
- #10 不增加。

### 27.6 引用普通群友图片

- 用户引用非插件图片并发 `4`；
- 不计票。

### 27.7 改票

同一用户：

```text
#5 → 2
#5 → 4
```

最终：

```text
1 个 voter
score = 4
```

### 27.8 群隔离

A 群 #5 和 B 群 #5 完全独立。

### 27.9 重启

运行到 20/100 重启：

- 数据仍存在；
- session 进入 PAUSED；
- `/vote resume` 从 21 继续；
- 不重发前 20 张。

### 27.10 500 MB 项目

- 扫描不能把 500 MB 全读进内存；
- report directory 正常生成；
- 图片自动压缩；
- index.html 本身保持较小；
- 原图不被修改；
- cleanup 只删 report。

### 27.11 单 HTML 超限

设置：

```text
single_html_max_mb = 10
```

输出超过 10 MB 时必须自动回退 directory。

### 27.12 Path Traversal

```text
/vote ../../etc
```

必须拒绝。

---

## 28. MVP 开发阶段

### Phase 1：最小可用

完成：

- 配置；
- 项目扫描；
- `/vote project`；
- 图片定时发送；
- 当前窗口 1-4 投票；
- SQLite；
- pause/resume/stop/status；
- 基础统计；
- directory HTML；
- WebP 压缩。

### Phase 2：引用旧图投票

完成：

- Reply 解析；
- session marker；
- quote route；
- 历史图片改票。

### Phase 3：AI 总结

完成：

- provider adapter；
- 统计 prompt；
- fallback；
- HTML AI 总结区域。

### Phase 4：WebUI

如果后续需要，再使用 AstrBot Plugin Pages 增加：

- 项目列表；
- 扫描预览；
- 当前 session 进度；
- 历史 session；
- 报告下载；
- 一键清理；
- 配置图形化。

**MVP 不要求 WebUI。**

---

## 29. 最终验收标准

满足以下条件才算 MVP 完成：

1. `/vote 项目名` 能在 QQ 群开始完整轮播。
2. 间隔可配置。
3. 图 A 发出后到图 B 发出前，群成员发送 `1~4` 能准确归属图 A。
4. 同一用户对同一图重复投票不会重复计数，默认最后一次生效。
5. 可以引用之前由插件发送的图并发送 `1~4`，票归属被引用图。
6. 引用非插件图片不会错误计票。
7. 多群同时运行互不影响。
8. pause/resume/stop 可用。
9. AstrBot 重启后已有数据不丢失。
10. 最终生成排名统计。
11. AI 总结失败也不影响最终结果。
12. 500 MB 输入项目可以逐图处理，不出现一次性高内存加载。
13. HTML 默认使用“目录 + 压缩 WebP”，而不是原图 Base64 巨型单文件。
14. 输出目录可自定义。
15. `/vote cleanup` 只能删除插件自己的报告，不会删除输入图片。
16. 代码有单元测试，核心 vote parser / quote resolver / path guard 必须测试。
17. 插件卸载或 reload 时不存在继续发送图片的后台孤儿任务。

---

## 30. 默认实现决策

除非开发过程中确认 AstrBot/OneBot 限制导致必须修改，MVP 直接按以下默认决策实现，不需要再次询问：

```text
插件名：astrbot_plugin_image_vote
平台：QQ / aiocqhttp / OneBot v11 / NapCat
评分：1-4
重复票：last vote wins
轮播间隔：20 秒
最后一张等待：20 秒
普通数字票：归属当前图片
引用数字票：归属被引用的当前 session 候选图
引用旧图：允许
引用其他图片：忽略
每群 active session：最多 1 个
重启后：自动暂停，不自动继续
持久化：SQLite
报告：directory
报告主图：WebP，最大 1920px，quality 82
缩略图：WebP，宽 480px，quality 72
原图：不复制、不修改
单 HTML：可选，超过 50 MB 自动回退
AI：可选；只输入统计数据，不输入整批图片
输出目录：可配置
自动清理：默认关闭
```

---

## 31. 对 AI 开发 Agent 的额外要求

请按以下顺序工作：

1. 先检查目标 AstrBot 版本真实可用 API，不凭旧博客或记忆猜 API。
2. 优先参考 AstrBot 官方最新文档和当前安装版本源码。
3. 第一轮先输出：
   - 技术方案；
   - 目录结构；
   - 数据模型；
   - AstrBot 4.4.x 兼容点；
   - OneBot Reply 解析方案；
   - 可能存在的 API 风险。
4. 再开始写代码。
5. 每完成一阶段先写测试。
6. 不把全部逻辑堆在 `main.py`。
7. 所有后台任务必须可取消。
8. 所有本地路径操作必须经过统一 `path_guard`。
9. 所有报告图片都应从原图生成派生文件，禁止覆盖源文件。
10. 若 Reply API 在当前 AstrBot 版本行为不确定，应先写一个最小探针插件/测试，打印 Reply 组件结构，再实现正式 quote resolver。
11. 如果需要使用 AstrBot internal API，必须集中封装并标注“内部 API，可能随版本变化”。
12. README 必须写清 Docker volume 映射示例。
