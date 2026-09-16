<div align="center">

<img src="logo.png" width="88" alt="LIRATING">

# LIRATING · 人物图片投票

**在 QQ 群里一起看图、给人物打分，把每一次选择留成一份报告。**

[AstrBot 插件](https://github.com/AstrBotDevs/AstrBot) · OneBot v11 / NapCat · [MIT](LICENSE)

</div>

## 从一组图片，到一场共同完成的评选

把作品图片按项目整理好，Lirating 会按人物依次展示。同一个人物可以有多张图片，每位参与者对这个人物只保留一张最终票。

- **群里直接评分**：回复数字给当前人物打分；引用本场图片可以给对应人物补投或改分。
- **按自己的节奏进行**：逐张或合并发送，支持暂停、继续、提前结束；重启后暂停等待管理员恢复。
- **在网页中管理**：选择项目、预检、控制投票、下载历史报告和调整设置。
- **把结果留下来**：人物排名、评分分布、图片图册与参与者明细，支持明暗主题；可选 AI 数据解读。
- **离线也能看**：下载单文件 HTML 或目录 ZIP，保留、分享，不依赖外部 CDN。

## 开始使用

需要 **AstrBot 4.27+** 与 **aiocqhttp / OneBot v11 / NapCat**。历史真机验证使用过 AstrBot 4.27.5、4.28.0；其他平台未验证。

1. 在 AstrBot「插件管理 → 安装插件」填写仓库地址：
   ```text
   https://github.com/awillheartwu/astrbot_plugin_image_vote
   ```
2. 在插件设置中填写**图片项目根目录**；每个子文件夹对应一个项目。Docker 用户需先把图库挂载进容器。
3. 打开插件的 **image-vote 网页**，在「项目」中点击“预检与开始”，选择目标群。也可以在群里发送 `/vote 项目名`。
4. 群成员回复评分，等待本轮结束，在「历史与报告」下载结果。

默认评分 **1–4 分**，可在设置中调整。人物的第一张图成功发出即开始收票，全部图片发完后再等待完整人物间隔。

更深层或分散的图库目录，可在网页中登记为项目，不需要移动原图。预检先显示数量与规则，缩略图随后逐张加载，无需等图片全部加载才开始。

## 群里常用的几条指令

| 指令 | 用途 |
| --- | --- |
| `/vote 项目名` | 开始投票 |
| `/vote list` / `/vote check 项目名` | 查看项目 / 预检 |
| `/vote status` | 查看进度和当前人物 |
| `/vote pause` / `/vote resume` | 暂停 / 继续 |
| `/vote finish` / `/vote stop` | 提前结算 / 取消本轮 |
| `/vote export` | 重新生成最近一场报告 |

开始和控制投票默认需要管理员权限；更完整的命令与路径配置见 [使用手册](https://github.com/awillheartwu/astrbot_plugin_image_vote/blob/dev/docs/USER_GUIDE.md)。

## 报告怎么保存和分享

- **轻量分享**：选择单文件 HTML。默认每个人物保留一张高清封面，其余图片使用缩略图；可切换为全部高清。
- **完整保存**：目录报告下载为 ZIP，解压后保留整个文件夹，打开 `index.html`。
- **保护参与者信息**：公开分享前关闭“报告包含参与者明细”，生成不含昵称、逐人评分和群号的汇总版。
- **AI 解读**：只发送汇总统计，不上传整批图片。普通重导出复用已有解读，需要重新分析时使用 `/vote export --ai`。

原图不会被修改。已有报告不会随插件升级自动更新，需要重新导出。

## 数据放在哪里？

新配置中报告输出目录留空时，报告、数据库、头像和缩略图缓存、下载临时文件集中在插件数据目录。已设置的自定义报告目录会保留，不自动搬迁。

缩略图缓存默认上限 64 MB、保留 7 天；头像和残留临时目录定期维护。**历史报告自动删除默认关闭，投票记录不会自动删除**。可在设置中开启报告保留策略，或从历史页清理报告／彻底删除场次。

缓存上限不等于整个插件磁盘上限。原图、保留的报告和投票历史仍会随使用增长。详细边界见 [数据与维护](https://github.com/awillheartwu/astrbot_plugin_image_vote/blob/dev/docs/DATA_MAINTENANCE.md)。

## 文档与反馈

- [使用手册](https://github.com/awillheartwu/astrbot_plugin_image_vote/blob/dev/docs/USER_GUIDE.md)：路径映射、全部命令、图片策略与 AI 配置。
- [实现与验收状态](https://github.com/awillheartwu/astrbot_plugin_image_vote/blob/dev/docs/IMPLEMENTATION_STATUS.md)：已验证的范围与限制。
- [更新记录](CHANGELOG.md) · [问题反馈](https://github.com/awillheartwu/astrbot_plugin_image_vote/issues)
- 开发者：[架构](https://github.com/awillheartwu/astrbot_plugin_image_vote/blob/dev/docs/ARCHITECTURE.md) · [贡献约定](CONTRIBUTING.md) · [发布流程](https://github.com/awillheartwu/astrbot_plugin_image_vote/blob/dev/docs/RELEASE.md)

反馈问题时请附插件版本、AstrBot 版本、报错日志和复现步骤，记得遮蔽群号、昵称及其他私人信息。
