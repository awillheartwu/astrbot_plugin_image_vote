# 图片投票界面骨架

启动：在仓库根目录运行 `python3 tools/preview_ui.py`，浏览器打开终端打印的地址。

- 报告：`#report/overview`、`#report/images`、`#report/people`。
- 工作区：`#admin/run`、`#admin/projects`、`#admin/history`、`#admin/settings`。
- 全部数据和操作都是当前页面内存中的示例。刷新恢复初始状态，不会连接 AstrBot、读取项目目录或发群消息。
- 示例评分的均分、分布和排名统一计算。三个生成插画复用于部分图片与头像，专门展示少票、零票、未展示等状态。
- 下载按钮导出示例 JSON；正式 HTML/ZIP 导出、真实配置保存、目录浏览、模型选择与 AI 调用尚未接入。

视觉基于设计提案图 1 的概览、图 2 的主从详情和图 3 的深色调色。首轮为可交互骨架，非逐像素复刻，也不替换生产报告模板。确认布局后，再把组件和数据模型吸收到正式报告与 Plugin Pages。
