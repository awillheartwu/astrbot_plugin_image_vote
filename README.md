# astrbot_plugin_image_vote

在 QQ 群里轮播项目图片并收集 1-4 分投票，结束后自动生成带压缩图的 HTML 报告。AstrBot 插件，面向 aiocqhttp / OneBot v11 / NapCat。

## 功能

- `/vote <项目名>` 按设定间隔把项目目录里的图片逐张发到群里，扫描顺序稳定可复现。
- 群成员在图片的展示窗口内直接回复 `1`-`4` 计分；也可以引用之前某张投票图片回复数字，补投或改分。
- 同一用户对同一张图只保留一票，重复投票按最后一次生效。
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

配置项由 `_conf_schema.json` 定义，在 WebUI 的插件配置页按分组展示。最常用的三个：

| 配置项 | 说明 |
| --- | --- |
| `input_root` | 图片项目根目录，每个子文件夹是一个项目，项目名就是文件夹名 |
| `output_root` | 报告输出根目录，建议放在 AstrBot data 目录下 |
| `default_interval_seconds` | 每张图的发送间隔，首次试跑建议设成 5 |

其余包括评分范围、最后一张的额外等待、权限控制（仅管理员可开始、群白名单）、报告压缩参数、AI 开关与 Top/Bottom 数量、发送重试次数等。

## 指令

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `/vote <项目名>` | 管理员 | 开始轮播 |
| `/vote list` | 所有人 | 列出可用项目 |
| `/vote check <项目名>` | 所有人 | 只做预检：图片数量、总大小、命名统计、排序方式、首末各 5 张、非法文件、预计耗时 |
| `/vote status` | 所有人 | 进度、当前图、本图票数、总票数、下一张倒计时 |
| `/vote pause` / `/vote resume` | 管理员 | 暂停 / 继续，暂停期间仍可引用已发图片投票 |
| `/vote finish` | 管理员 | 立即停止后续发送并出结果 |
| `/vote stop` | 管理员 | 取消本次投票，保留已收到的投票 |
| `/vote export` | 管理员 | 用最近一次完成或取消的会话重新生成报告 |
| `/vote cleanup <短ID 或 项目名 或 all confirm>` | 管理员 | 只删除本插件生成的报告目录 |

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

页面无外部 CDN 依赖，可以 `file://` 直接打开，支持深色模式、名称搜索、排名与原始顺序切换。清理只删除带本插件 marker 的目录，不会触碰 `input_root`。

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
- 项目目前仅支持 `input_root` 下的第一层子目录；跨目录登记在路线图里。
- 报告里目前只有投票人昵称，头像与按人视图在路线图里。
- `single_html` 模式可选，超过 `single_html_max_mb` 会自动回退目录模式。

