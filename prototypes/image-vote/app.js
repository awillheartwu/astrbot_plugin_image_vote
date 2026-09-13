/* UI skeleton. All votes, projects and operations are disposable in-memory examples. */
"use strict";
const $ = (s, root = document) => root.querySelector(s);
const escapeHTML = (v) =>
  String(v).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const art = (n) => `assets/${n}.png`;
const people = [
  "星海与风",
  "柠檬汽水",
  "花间旅人",
  "晚风",
  "Mirage",
  "海盐冰",
  "青禾",
  "山间来信",
];
const candidates = [
  {
    id: 1,
    name: "Alice",
    title: "海风与她",
    image: "alice",
    scores: [5, 5, 4, 5, 4, 5, 4, 5],
    sent: true,
  },
  {
    id: 2,
    name: "Grace",
    title: "午后小憩",
    image: "grace",
    scores: [4, 5, 4, 4, 5, 4, 4, 4],
    sent: true,
  },
  {
    id: 3,
    name: "Iris",
    title: "树荫下的回眸",
    image: "iris",
    scores: [5, 2, 4, 2, 5, 3, 4, 1],
    sent: true,
  },
  {
    id: 4,
    name: "Alice",
    title: "海边手记 · 示例复用图",
    image: "alice",
    scores: [5, 4, 4],
    sent: true,
  },
  {
    id: 5,
    name: "Grace",
    title: "等待一封信 · 示例复用图",
    image: "grace",
    scores: [],
    sent: true,
  },
  {
    id: 6,
    name: "Iris",
    title: "下一次旅行 · 示例复用图",
    image: "iris",
    scores: [],
    sent: false,
  },
];
for (const c of candidates) {
  c.votes = c.scores.length;
  c.mean = c.votes ? c.scores.reduce((a, b) => a + b, 0) / c.votes : null;
  c.distribution = [1, 2, 3, 4, 5].map(
    (s) => c.scores.filter((v) => v === s).length,
  );
  c.std = c.votes
    ? Math.sqrt(
        c.scores.reduce((sum, x) => sum + (x - c.mean) ** 2, 0) / c.votes,
      )
    : null;
}
const ranked = candidates
  .filter((c) => c.votes)
  .sort((a, b) => b.mean - a.mean || b.votes - a.votes || a.id - b.id);
ranked.forEach((c, i) => (c.rank = i + 1));
const totalVotes = candidates.reduce((sum, c) => sum + c.votes, 0);
let view = "report/overview",
  selected = 1,
  person = 0,
  search = "",
  sort = "rank",
  filter = "all",
  settingsTab = "voting",
  projectSearch = "";
let runs = [
    {
      id: 1,
      name: "海滨之家",
      group: "图鉴讨论组",
      status: "RUNNING",
      progress: 3,
    },
  ],
  history = [
    {
      name: "海滨之家",
      group: "周末放映室",
      date: "2026-09-12",
      report: "ready",
      status: "部分完成",
    },
  ];
let projects = [
  {
    id: 1,
    name: "海滨之家",
    path: "/vote/projects/seaside",
    description: "留住海风、树影和一个安静的午后。",
    count: 6,
    source: "登记项目",
  },
  {
    id: 2,
    name: "雨后花园",
    path: "/vote/projects/garden",
    description: "下一场图片评选。",
    count: 6,
    source: "目录项目",
  },
];
let saved = {
  scale: "5",
  interval: "20",
  grace: "20",
  quoted: true,
  ack: false,
  input: "/vote/projects",
  output: "/vote/reports",
  recursive: false,
  mode: "directory",
  quality: "82",
  limit: "50",
  autoReport: true,
  notify: true,
  attachment: false,
  participants: true,
  avatars: true,
  ai: true,
  provider: "session",
  top: "3",
  bottom: "3",
  prompt:
    "请根据 {statistics} 总结 {project_name} 的投票结果。只解释统计，不推断图片内容。",
  adminOnly: true,
  groups: "",
  autoResume: false,
  retries: "3",
  threshold: "3",
  cleanup: false,
  retention: "30",
};
let draft = { ...saved };
const dirty = () =>
  Object.keys(saved).some((k) => String(saved[k]) !== String(draft[k]));
const mean = (c) => (c.mean === null ? "—" : c.mean.toFixed(2));
const badge = (c) =>
  !c.sent
    ? '<span class="badge neutral">未展示</span>'
    : !c.votes
      ? '<span class="badge neutral">暂无评分</span>'
      : c.votes < 5
        ? '<span class="badge warning">仅 ' + c.votes + " 票</span>"
        : "";
function avatar(i) {
  return `<img class="avatar" src="${art(["alice", "grace", "iris"][i % 3])}" alt="示例头像" loading="lazy">`;
}
function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.style.display = "block";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.style.display = "none"), 3500);
}
function tabs(items) {
  return `<nav class="tabs ${view.startsWith("report") ? "report-tabs" : ""}" aria-label="页面导航">${items.map(([path, label]) => `<a href="#${path}" class="${view === path ? "active" : ""}" ${view === path ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</nav>`;
}
function reportHeading() {
  return `<div class="page-heading"><div><div class="eyebrow">THE VOTING JOURNAL / 2026.09.12</div><h1>海滨之家 <span class="muted">·</span> 角色图鉴</h1><p>一次关于图片与偏好的共同记录。 <span class="badge neutral">部分结果</span></p></div>${tabs(
    [
      ["report/overview", "概览"],
      ["report/images", "全部图片"],
      ["report/people", "按人查看"],
    ],
  )}</div>`;
}
function facts() {
  return `<div class="facts"><span><b>5 / 6</b> 张已展示</span><span><b>8</b> 位参与者</span><span><b>${totalVotes}</b> 张有效票</span><span><b>1–5</b> 分制</span></div>`;
}
function distribution(c) {
  const max = Math.max(...c.distribution, 1);
  return `<div class="distribution" aria-label="评分分布">${c.distribution.map((n, i) => `<div class="dist-col"><span>${n} 票</span><div class="bar" style="height:${Math.max(2, (n / max) * 58)}px"></div><span>${i + 1} 分</span></div>`).join("")}</div>`;
}
function method() {
  return `<details class="method"><summary>关于这份报告 · 统计口径与示例说明</summary><p>这是一份界面骨架，图片和评分均为示例，部分图片用于演示不同状态而重复使用。平均分、排名和分布均从同一组示例评分计算。排名按平均分、票数、原始顺序排列。少于 5 票标记为少量评分；零票不参与排名。按人查看仅包含最终有效评分，不代表完整改票历史。所有头像也是示例。</p></details>`;
}
function artCard(c) {
  return `<button class="art-card" data-action="open-image" data-id="${c.id}" aria-label="查看 ${c.name} 的评分详情"><img src="${art(c.image)}" alt="${c.name} · ${c.title}"><span class="art-caption"><span class="rank">RANK ${String(c.rank).padStart(2, "0")}</span><h3>${c.name}</h3><p>${mean(c)} / 5 <span class="muted">· ${c.votes} 票</span></p></span></button>`;
}
function overview() {
  const featured = ranked.filter((c) => c.votes >= 5).slice(0, 3);
  const aggregate = {
    distribution: [1, 2, 3, 4, 5].map((s) =>
      candidates.reduce((n, c) => n + c.distribution[s - 1], 0),
    ),
  };
  return `${reportHeading()}${facts()}<section class="gallery" aria-label="本轮高分图片">${artCard(featured[0])}<div class="art-stack">${featured.slice(1).map(artCard).join("")}</div></section><div class="gallery-note"><span>展示至少获得 5 票的高分图片 · 完整排名保留少票项</span><a class="accent" href="#report/images">查看全部 6 张图片 →</a></div><div class="insights"><section><div class="section-title"><h2>本轮看点</h2><span class="subtle">由示例统计生成</span></div><div class="insight"><span class="number">01</span><div><h3>多数评分落在高分区间</h3><p>${aggregate.distribution[3] + aggregate.distribution[4]} / ${totalVotes} 张有效票为 4–5 分。Alice「海风与她」以 ${mean(candidates[0])} 分位列第一，共 8 人评分。</p></div></div><div class="insight"><span class="number">02</span><div><h3>平均分之外，也看看分布</h3><p>Iris 的评分覆盖 1–5 分，标准差 ${candidates[2].std.toFixed(2)}。分数较为分散，值得结合逐人评分阅读。</p><button class="text-link" data-action="open-image" data-id="3">查看这张图片 →</button></div></div><div class="insight"><span class="number">03</span><div><h3>给未充分评分的图片留一点空间</h3><p>1 张图片只有 3 票，1 张已展示但暂无评分，另有 1 张尚未展示。它们分别保留状态，不作低分判断。</p></div></div></section><section><div class="section-title"><h2>评分落在哪里</h2><span class="subtle">最终有效票</span></div>${distribution(aggregate)}<p class="subtle" style="margin-top:24px">一人一图保留一票；重复评分以最后一次为准。</p><div class="section-title" style="margin-top:34px"><h2>从一个人的选择开始</h2></div><p class="muted">同一组图片，每个人都有自己的偏好。</p><div class="people-list">${people
    .slice(0, 3)
    .map(
      (p, i) =>
        `<div class="person-row">${avatar(i)}<button class="text-link" data-action="person" data-id="${i}">${p}</button><span class="right muted">${i < 3 ? 4 : 3} 张评分</span></div>`,
    )
    .join("")}</div></section></div>${method()}`;
}
function filtered() {
  let list = candidates.filter((c) =>
    `${c.name} ${c.title}`.toLowerCase().includes(search.toLowerCase()),
  );
  if (filter === "few") list = list.filter((c) => c.votes > 0 && c.votes < 5);
  if (filter === "zero") list = list.filter((c) => c.sent && !c.votes);
  if (filter === "unsent") list = list.filter((c) => !c.sent);
  return list.sort((a, b) =>
    sort === "index"
      ? a.id - b.id
      : sort === "votes"
        ? b.votes - a.votes || a.id - b.id
        : sort === "std"
          ? (b.std ?? -1) - (a.std ?? -1)
          : (a.rank ?? 999) - (b.rank ?? 999),
  );
}
function detail(c) {
  if (!c)
    return '<section class="surface empty">选择一张图片查看详情</section>';
  return `<aside class="surface detail"><div class="detail-head"><div><div class="eyebrow">IMAGE ${String(c.id).padStart(2, "0")}</div><h2>${c.name}</h2><p class="subtle">${c.title}</p></div><div class="detail-nav"><button data-action="prev" aria-label="上一张图片">←</button><button data-action="next" aria-label="下一张图片">→</button></div></div><div class="score-line"><span class="score-value">${mean(c)} <small>/ 5</small></span><span class="muted">${c.votes} 票</span>${badge(c)}</div><button class="art-card" data-action="enlarge" data-id="${c.id}" aria-label="放大图片"><img class="detail-img" src="${art(c.image)}" alt="${c.name} · ${c.title}" style="height:240px;object-fit:contain"></button>${c.votes ? distribution(c) : `<p class="empty">${c.sent ? "这张图片已展示，暂时没有评分。" : "本轮提前结束，这张图片尚未展示。"}</p>`}<div class="section-title" style="margin-top:28px"><h3 style="margin:0">参与者评分</h3><span class="subtle">${c.votes} 人</span></div><div class="people-list">${c.scores.map((v, i) => `<div class="person-row">${avatar(i)}<button class="text-link" data-action="person" data-id="${i}">${people[i]}</button><b class="right">${v} <span class="muted">分</span></b></div>`).join("")}</div></aside>`;
}
function imageRows() {
  const list = filtered();
  if (!list.some((c) => c.id === selected)) selected = list[0]?.id ?? null;
  return `<div class="table-wrap"><table><thead><tr><th>排名</th><th>图片</th><th>均分</th><th>票数</th><th>分布</th></tr></thead><tbody>${list.map((c) => `<tr class="${c.id === selected ? "selected" : ""}"><td class="muted num">${c.rank ?? "—"}</td><td><div class="item-cell"><img class="thumb" src="${art(c.image)}" alt=""><div><button class="row-choice" data-action="select" data-id="${c.id}">${c.name}</button><small>#${String(c.id).padStart(2, "0")} ${c.title.split(" ·")[0]}</small><div>${badge(c)}</div></div></div></td><td class="num"><b>${mean(c)}</b></td><td class="num">${c.votes}</td><td><div class="mini-dist" aria-label="${c.distribution.map((n, i) => `${i + 1}分${n}票`).join("，")}">${c.distribution.map((n, i) => `<i style="flex:${n};opacity:${0.18 + i * 0.2}"></i>`).join("")}</div></td></tr>`).join("")}</tbody></table>${list.length ? "" : '<div class="empty">没有符合条件的图片。<br><button data-action="clear">清除筛选</button></div>'}</div>${detail(list.find((c) => c.id === selected))}`;
}
function images() {
  return `${reportHeading()}<div class="toolbar"><input id="search" placeholder="搜索图片名称" aria-label="搜索图片名称" value="${escapeHTML(search)}"><label>排序<select id="sort"><option value="rank">排名</option><option value="index">原始顺序</option><option value="votes">票数</option><option value="std">分歧程度</option></select></label><label>筛选<select id="filter"><option value="all">全部图片</option><option value="few">少量评分</option><option value="zero">已展示未获票</option><option value="unsent">未展示</option></select></label><span class="count" id="count"></span></div><div id="image-results" class="split">${imageRows()}</div>${method()}`;
}
function personPage() {
  const votes = candidates.filter((c) => c.scores[person]);
  const avg = votes.reduce((n, c) => n + c.scores[person], 0) / votes.length;
  return `${reportHeading()}<div class="people-layout"><aside><h3>选择参与者</h3><p class="subtle">查看本轮最终有效评分</p><div class="people-menu">${people.map((p, i) => `<button data-action="person" data-id="${i}" class="${i === person ? "active" : ""}">${avatar(i)}<span>${p}<small>${i < 3 ? 4 : 3} 张图片已评分</small></span></button>`).join("")}</div></aside><section><div class="person-heading">${avatar(person)}<div><h2>${people[person]}</h2><span class="muted">本轮个人选择</span></div></div><div class="facts"><span><b>${votes.length} / 5</b> 张已评分</span><span><b>${avg.toFixed(2)}</b> 个人均分</span><span><b>${Math.round((votes.length / 5) * 100)}%</b> 评分覆盖</span></div><div class="section-title"><h2>这位参与者的图片清单</h2><span class="subtle">按个人评分排序</span></div><div class="image-grid">${votes
    .sort((a, b) => b.scores[person] - a.scores[person])
    .map(
      (c) =>
        `<div class="surface"><button class="art-card" data-action="open-image" data-id="${c.id}"><img src="${art(c.image)}" alt="${c.name}"></button><h3>${c.name} · ${c.title.split(" ·")[0]}</h3><span class="accent"><b>${c.scores[person]}</b> / 5</span><small style="float:right">本轮均分 ${mean(c)}</small></div>`,
    )
    .join(
      "",
    )}</div><p class="notice">评分覆盖以本轮成功展示的 5 张图片为分母。这里展示最终评分，不推断参与者的性格或审美水平。</p></section></div>${method()}`;
}
function adminHeading(title, desc, action = "") {
  return `<div class="page-heading"><div><div class="eyebrow">IMAGE VOTE / WORKSPACE</div><h1 class="admin-title">${title}</h1><p>${desc}</p></div>${action}</div>${tabs(
    [
      ["admin/run", "运行"],
      ["admin/projects", "项目"],
      ["admin/history", "历史与报告"],
      ["admin/settings", "设置"],
    ],
  )}`;
}
function runPage() {
  return `${adminHeading("投票工作区", "从一组图片，到一份共同完成的评选记录。", '<button class="primary" data-action="start">开始一场投票</button>')}<div class="admin-stats"><span><b>${runs.length}</b>场进行中</span><span><b>${projects.length}</b>个项目</span><span><b>${history.length}</b>场历史记录</span></div>${runs.length ? runs.map((r) => `<div class="run-grid" style="margin-bottom:24px"><section class="surface"><div class="label-row"><div><h2 style="margin:0">${escapeHTML(r.name)}</h2><span class="subtle">${escapeHTML(r.group)} · 示例会话</span></div><span class="badge ${r.status === "RUNNING" ? "good" : ""}">${r.status === "RUNNING" ? "轮播中" : "已暂停"}</span></div><img class="run-image" src="${art("iris")}" alt="当前展示的示例图片"><div class="label-row"><b>当前 · Iris</b><span class="muted">${r.progress} / 6 张</span></div><div class="progress"><i style="width:${(r.progress / 6) * 100}%"></i></div><div class="label-row subtle"><span>当前图 8 票 · 8 人参与</span><span>${r.status === "RUNNING" ? "下一张 20 秒（演示）" : "暂停期间仍可引用投票"}</span></div><div class="actions"><button class="primary" data-action="pause" data-id="${r.id}">${r.status === "RUNNING" ? "暂停轮播" : "继续轮播"}</button><button data-action="finish" data-id="${r.id}">提前结束</button><button class="quiet danger" data-action="cancel" data-id="${r.id}">取消本轮</button></div></section><aside class="surface"><h3>本轮使用的参数</h3><div class="kv"><span>评分范围</span><b>1–5 分</b><span>发送间隔</span><b>20 秒</b><span>结束后生成报告</span><b>开启</b><span>报告格式</span><b>目录版</b></div><div class="notice">这些是本轮的参数快照。调整默认评分制和间隔，将用于以后开始的投票。</div><h3>当前进度</h3><div class="steps"><div class="step current"><span class="step-number">1</span><div><b>轮播与收集评分</b><p>${r.status === "RUNNING" ? "正在展示图片，等待评分" : "轮播暂停，等待继续"}</p></div></div><div class="step"><span class="step-number">2</span><div><b>汇总最终评分</b><p>轮播结束后计算排名与分布</p></div></div><div class="step"><span class="step-number">3</span><div><b>生成报告</b><p>完成后可在历史与报告中查看</p></div></div></div></aside></div>`).join("") : '<div class="surface empty"><h3>现在没有进行中的投票</h3><p>选择一个项目，预检后开始下一场。</p><a class="button primary" href="#admin/projects">查看项目</a></div>'}`;
}
function projectCards() {
  return (
    projects
      .filter((p) => p.name.includes(projectSearch))
      .map(
        (p) =>
          `<article class="surface"><div class="project-cover">${["alice", "grace", "iris"].map((x) => `<img src="${art(x)}" alt="项目示例图片">`).join("")}</div><div class="label-row"><h2>${escapeHTML(p.name)}</h2><span class="badge neutral">${p.source}</span></div><p class="muted">${escapeHTML(p.description)}</p><div class="project-path">${escapeHTML(p.path)}</div><p class="subtle">${p.count} 张示例图片 · 按原始顺序 · 预计 2 分钟</p><div class="actions"><button class="primary" data-action="preflight" data-id="${p.id}">预检与开始</button><button data-action="edit-project" data-id="${p.id}">编辑登记</button></div></article>`,
      )
      .join("") || '<div class="empty">没有找到这个项目。</div>'
  );
}
function projectsPage() {
  return `${adminHeading("图片项目", "把容器内的图片目录，整理成可直接开始的投票项目。", '<button class="primary" data-action="register">登记项目</button>')}<div class="toolbar"><input id="project-search" placeholder="搜索项目名称" aria-label="搜索项目名称" value="${escapeHTML(projectSearch)}"><span class="count">${projects.length} 个项目</span></div><div class="project-grid" id="project-results">${projectCards()}</div><p class="notice">路径为示例容器路径。此骨架不会读取本地目录，预检结果用于演示页面流程。</p>`;
}
function historyPage() {
  return `${adminHeading("历史与报告", "投票结束后，从这里回看、下载和重新生成结果。")}<div class="table-wrap"><table><thead><tr><th>项目 / 场次</th><th>投票群</th><th>投票状态</th><th>报告状态</th><th>操作</th></tr></thead><tbody>${history.map((h, i) => `<tr><td><b>${escapeHTML(h.name)}</b><br><small>${h.date} · ${totalVotes} 票</small></td><td>${escapeHTML(h.group)}</td><td>${h.status}</td><td><span class="badge ${h.report === "ready" ? "good" : "neutral"}">${h.report === "ready" ? "可查看" : h.report === "cleared" ? "已清理" : "未生成"}</span></td><td>${h.report === "ready" ? `<a class="text-link" href="#report/overview">预览</a> <button class="quiet" data-action="download">导出示例数据</button><button class="quiet danger" data-action="clean" data-id="${i}">清理</button>` : `<button data-action="regenerate" data-id="${i}">生成示例报告</button>`}</td></tr>`).join("")}</tbody></table></div><div class="notice">下载提供真实的示例 JSON 文件。正式版将按报告产物提供 HTML 或完整 ZIP；本轮不连接真实报告目录。</div>`;
}
const groups = [
  ["voting", "投票规则"],
  ["paths", "项目与输出"],
  ["report", "报告与分享"],
  ["ai", "AI 总结"],
  ["permissions", "使用权限"],
  ["maintenance", "恢复与维护"],
];
function field(key, label, hint, type = "text", options = null) {
  let control =
    type === "checkbox"
      ? `<input type="checkbox" id="cfg-${key}" data-field="${key}" ${draft[key] ? "checked" : ""}>`
      : type === "textarea"
        ? `<textarea id="cfg-${key}" data-field="${key}">${escapeHTML(draft[key])}</textarea>`
        : options
          ? `<select id="cfg-${key}" data-field="${key}">${options.map(([v, t]) => `<option value="${v}" ${String(draft[key]) === v ? "selected" : ""}>${t}</option>`).join("")}</select>`
          : `<input id="cfg-${key}" data-field="${key}" type="${type}" value="${escapeHTML(draft[key])}" ${type === "number" ? 'min="1"' : ""}>`;
  return `<div class="form-row"><div><label for="cfg-${key}">${label}</label><p>${hint}</p></div><div>${control}</div></div>`;
}
function settingsFields() {
  switch (settingsTab) {
    case "voting":
      return (
        field("scale", "评分制", "用于以后开始的投票。", "text", [
          ["4", "1–4 分"],
          ["5", "1–5 分"],
          ["10", "1–10 分"],
          ["100", "1–100 分"],
        ]) +
        field(
          "interval",
          "每张图发送间隔",
          "秒；本轮已使用的间隔保持不变。",
          "number",
        ) +
        field(
          "grace",
          "最后一张等待",
          "秒；正式版按实际配置规则校验。",
          "number",
        ) +
        field(
          "quoted",
          "允许引用旧图评分",
          "群成员可以补投或修改此前的评分。",
          "checkbox",
        ) +
        field("ack", "每票回复确认", "默认关闭，减少群消息干扰。", "checkbox")
      );
    case "paths":
      return (
        field("input", "默认图片根目录", "请填写容器内可读取的路径。") +
        field("output", "报告输出目录", "报告图片与 HTML 的保存位置。") +
        field(
          "recursive",
          "默认递归扫描",
          "项目登记可单独覆盖此选项。",
          "checkbox",
        ) +
        '<p class="notice">单个项目的路径与间隔在「项目」中管理。</p>'
      );
    case "report":
      return (
        field(
          "mode",
          "报告格式",
          "目录版适合大项目；单文件版方便群文件分发。",
          "text",
          [
            ["directory", "目录版 · 下载完整 ZIP"],
            ["single_html", "单文件版 · 下载 HTML"],
          ],
        ) +
        field("quality", "派生图质量", "范围 1–100。原图保持不变。", "number") +
        field("limit", "单文件上限", "MB；超限时回退目录版。", "number") +
        field(
          "participants",
          "包含参与者明细",
          "关闭后，分享版只保留汇总结果。",
          "checkbox",
        ) +
        field(
          "avatars",
          "包含参与者头像",
          "正式版下载本地头像，报告离线可用。",
          "checkbox",
        ) +
        field(
          "autoReport",
          "结束后自动生成报告",
          "关闭时可在历史记录中手动生成。",
          "checkbox",
        ) +
        field(
          "notify",
          "在群里通知结束",
          "示例开关，不会发送消息。",
          "checkbox",
        ) +
        field(
          "attachment",
          "把单文件报告发到群里",
          "仅单文件模式可用；目录模式不能发送单个 HTML。",
          "checkbox",
        )
      );
    case "ai":
      return (
        field("ai", "启用 AI 总结", "失败时仍保留纯统计报告。", "checkbox") +
        field(
          "provider",
          "模型来源",
          "骨架尚未连接 AstrBot 模型列表。",
          "text",
          [["session", "跟随当前群的默认模型"]],
        ) +
        field("top", "高分项数量", "AI 只使用结构化统计。", "number") +
        field("bottom", "低分项数量", "不根据文件名推断图片内容。", "number") +
        field(
          "prompt",
          "提示词模板",
          "支持 {project_name} 和 {statistics}。预览不调用模型。",
          "textarea",
        ) +
        '<div class="actions"><button data-action="prompt-preview">预览展开后的提示词</button></div>'
      );
    case "permissions":
      return (
        field(
          "adminOnly",
          "仅管理员可以开始",
          "网页与群指令应共享后端权限检查。",
          "checkbox",
        ) +
        field("groups", "群白名单", "一行一个群号；留空不限制。", "textarea")
      );
    default:
      return (
        field(
          "autoResume",
          "重启后自动继续",
          "默认关闭，保留暂停状态等待管理员恢复。",
          "checkbox",
        ) +
        field("retries", "单张最大发送重试次数", "用于下一次发送。", "number") +
        field(
          "threshold",
          "连续失败暂停阈值",
          "连续失败多少张后暂停；0 为关闭。",
          "number",
        ) +
        field("cleanup", "自动清理过期报告", "只影响派生报告。", "checkbox") +
        field("retention", "报告保留天数", "自动清理开启时生效。", "number")
      );
  }
}
function settingsPage() {
  return `${adminHeading("设置", "让每一场投票，都按你的习惯进行。")}<div class="savebar"><p id="dirty-label">${dirty() ? "有未保存的示例修改" : "示例配置已同步"}<br><small>仅保留在当前页面，刷新后恢复默认</small></p><div class="actions" style="margin:0"><button id="discard" data-action="discard" ${dirty() ? "" : "disabled"}>放弃修改</button><button id="save" class="primary" data-action="save" ${dirty() ? "" : "disabled"}>保存示例配置</button></div></div><div class="settings-layout"><nav class="settings-nav" aria-label="配置分组">${groups.map(([id, label]) => `<button data-action="settings-tab" data-id="${id}" class="${id === settingsTab ? "active" : ""}">${label}</button>`).join("")}</nav><section class="settings-form"><div class="form-head"><h2>${groups.find((g) => g[0] === settingsTab)[1]}</h2><p>清晰的默认值，让下一次开始更简单。</p></div>${settingsFields()}<p id="config-error" class="error" role="alert"></p></section></div>`;
}
function render() {
  view = location.hash.slice(1) || "report/overview";
  const routes = {
    "report/overview": overview,
    "report/images": images,
    "report/people": personPage,
    "admin/run": runPage,
    "admin/projects": projectsPage,
    "admin/history": historyPage,
    "admin/settings": settingsPage,
  };
  if (!routes[view]) {
    location.hash = "report/overview";
    return;
  }
  $("#app").innerHTML = routes[view]();
  $("#report-link").classList.toggle("active", view.startsWith("report"));
  $("#admin-link").classList.toggle("active", view.startsWith("admin"));
  if (view === "report/images") {
    $("#sort").value = sort;
    $("#filter").value = filter;
    $("#count").textContent =
      `${filtered().length} / ${candidates.length} 张图片`;
  }
  document.title = `${view.startsWith("report") ? "海滨之家 · 投票回顾" : "图片投票 · 工作区"} | LIRATING`;
}
function updateResults() {
  $("#image-results").innerHTML = imageRows();
  $("#count").textContent =
    `${filtered().length} / ${candidates.length} 张图片`;
}
function modal(title, body, wide = false) {
  const el = $("#modal");
  el.className = wide ? "lightbox" : "";
  el.innerHTML = `<div class="modal-head"><h2 id="modal-title">${title}</h2><button class="quiet" data-action="close" aria-label="关闭对话框">关闭</button></div>${body}`;
  el.showModal();
}
function closeModal() {
  $("#modal").close();
}
function startModal(id) {
  modal(
    "开始一场示例投票",
    `<p class="subtle">只演示启动流程，不读取目录、不发送群消息。</p><form id="start-form"><label>项目<select name="project">${projects.map((p) => `<option value="${p.id}" ${id === p.id ? "selected" : ""}>${escapeHTML(p.name)}</option>`).join("")}</select></label><label>目标群<select name="group"><option>图鉴讨论组</option><option>周末放映室</option></select></label><div class="notice">示例预检通过 · 6 张图片 · 1–5 分 · 20 秒间隔<br>参数为固定演示快照，未接入保存配置。</div><p id="start-error" class="error" role="alert"></p><div class="actions"><button type="button" data-action="close">返回</button><button class="primary" type="submit">开始示例投票</button></div></form>`,
  );
}
function registerModal(id) {
  const p = projects.find((x) => x.id === id);
  modal(
    p ? "编辑示例登记" : "登记一个项目",
    `<form id="project-form" data-id="${id || ""}"><label>项目名称<input name="name" required maxlength="60" value="${escapeHTML(p?.name || "")}"></label><label>容器内绝对路径<input name="path" required placeholder="/vote/projects/my-project" value="${escapeHTML(p?.path || "")}"></label><label>说明<textarea name="description">${escapeHTML(p?.description || "")}</textarea></label><p class="subtle">目录浏览与真实预检将在后端接入时提供。</p><p id="project-error" role="alert" class="error"></p><div class="actions"><button type="button" data-action="close">取消</button><button class="primary" type="submit">保存示例登记</button></div></form>`,
  );
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-action]");
  if (!b) return;
  const a = b.dataset.action,
    id = Number(b.dataset.id);
  if (a === "close") closeModal();
  else if (a === "open-image") {
    selected = id;
    search = "";
    filter = "all";
    location.hash = "report/images";
    if (view === "report/images") render();
  } else if (a === "select") {
    selected = id;
    updateResults();
  } else if (a === "person") {
    person = id;
    location.hash = "report/people";
    if (view === "report/people") render();
  } else if (a === "enlarge") {
    const c = candidates.find((c) => c.id === id);
    modal(
      escapeHTML(c.name),
      `<img src="${art(c.image)}" alt="${c.name}">`,
      true,
    );
  } else if (a === "prev" || a === "next") {
    const list = filtered(),
      i = list.findIndex((c) => c.id === selected);
    selected =
      list[(i + (a === "next" ? 1 : -1) + list.length) % list.length].id;
    updateResults();
  } else if (a === "clear") {
    search = "";
    filter = "all";
    render();
  } else if (a === "settings-tab") {
    settingsTab = b.dataset.id;
    render();
  } else if (a === "discard") {
    draft = { ...saved };
    render();
    toast("已放弃示例修改");
  } else if (a === "save") {
    const error = validateConfig();
    if (error) {
      $("#config-error").textContent = error;
      return;
    }
    saved = { ...draft };
    render();
    toast("示例配置已保存，仅当前页面有效");
  } else if (a === "pause") {
    const r = runs.find((r) => r.id === id);
    r.status = r.status === "RUNNING" ? "PAUSED" : "RUNNING";
    render();
    toast(r.status === "PAUSED" ? "示例轮播已暂停" : "示例轮播已继续");
  } else if (a === "finish" || a === "cancel") {
    modal(
      a === "finish" ? "提前结束本轮？" : "取消本轮？",
      `<p>${a === "finish" ? "停止后续发送，按已收评分结算并生成示例报告。" : "停止本轮，保留已收评分，不自动生成报告。"}</p><div class="actions"><button data-action="close">返回</button><button class="${a === "finish" ? "primary" : "danger"}" data-action="confirm-${a}" data-id="${id}">确认${a === "finish" ? "结束" : "取消"}</button></div>`,
    );
  } else if (a === "confirm-finish" || a === "confirm-cancel") {
    const r = runs.find((r) => r.id === id);
    history.unshift({
      name: r.name,
      group: r.group,
      date: "2026-09-12",
      status: a === "confirm-finish" ? "提前结束" : "已取消",
      report: a === "confirm-finish" ? "ready" : "none",
    });
    runs = runs.filter((r) => r.id !== id);
    closeModal();
    render();
    toast("示例会话已结束，可在历史与报告中查看");
  } else if (a === "start") startModal();
  else if (a === "preflight") startModal(id);
  else if (a === "register" || a === "edit-project") registerModal(id);
  else if (a === "regenerate") {
    history[id].report = "ready";
    render();
    toast("示例报告状态已更新");
  } else if (a === "clean") {
    modal(
      "清理示例报告？",
      '<p>只移除这条示例记录的报告状态，保留投票记录；不会删除任何文件。</p><div class="actions"><button data-action="close">返回</button><button class="danger" data-action="confirm-clean" data-id="' +
        id +
        '">清理示例报告</button></div>',
    );
  } else if (a === "confirm-clean") {
    history[id].report = "cleared";
    closeModal();
    render();
  } else if (a === "download") {
    const blob = new Blob(
      [
        JSON.stringify(
          { example: true, participants: people, candidates },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob),
      link = document.createElement("a");
    link.href = url;
    link.download = "lirating-example.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    toast("已导出示例数据");
  } else if (a === "prompt-preview") {
    const text = draft.prompt
      .replaceAll("{project_name}", "海滨之家")
      .replaceAll(
        "{statistics}",
        JSON.stringify({ votes: totalVotes, participants: 8, scale: "1-5" }),
      );
    modal(
      "提示词预览",
      `<p class="subtle">本预览没有调用模型。</p><pre style="white-space:pre-wrap;font:inherit">${escapeHTML(text)}</pre>`,
    );
  }
});
function validateConfig() {
  for (const k of [
    "interval",
    "grace",
    "quality",
    "limit",
    "top",
    "bottom",
    "retention",
  ])
    if (!Number.isInteger(Number(draft[k])) || Number(draft[k]) < 1)
      return "请为间隔、数量、质量与保留天数填写正整数。";
  if (Number(draft.quality) > 100) return "图片质量应在 1–100 之间。";
  for (const k of ["retries", "threshold"])
    if (!Number.isInteger(Number(draft[k])) || Number(draft[k]) < 0)
      return "重试次数与暂停阈值不能小于 0。";
  if (!draft.input.startsWith("/") || !draft.output.startsWith("/"))
    return "示例输入与输出路径必须是绝对路径。";
  if (draft.attachment && draft.mode !== "single_html")
    return "发送单文件附件需要先将报告格式改为单文件版。";
  if (draft.avatars && !draft.participants)
    return "关闭参与者明细时，请同时关闭参与者头像。";
  const unknown = (draft.prompt.match(/\{[^}]+\}/g) || []).filter(
    (x) => !["{project_name}", "{statistics}"].includes(x),
  );
  if (unknown.length) return "未知提示词变量：" + unknown.join("、");
  return "";
}
document.addEventListener("input", (e) => {
  if (e.target.id === "search") {
    search = e.target.value;
    updateResults();
  }
  if (e.target.id === "project-search") {
    projectSearch = e.target.value;
    $("#project-results").innerHTML = projectCards();
  }
  const k = e.target.dataset.field;
  if (k) {
    draft[k] = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    $("#save").disabled = !dirty();
    $("#discard").disabled = !dirty();
    $("#dirty-label").innerHTML =
      (dirty() ? "有未保存的示例修改" : "示例配置已同步") +
      "<br><small>仅保留在当前页面，刷新后恢复默认</small>";
  }
});
document.addEventListener("change", (e) => {
  if (e.target.id === "sort") {
    sort = e.target.value;
    updateResults();
  }
  if (e.target.id === "filter") {
    filter = e.target.value;
    updateResults();
  }
});
document.addEventListener("submit", (e) => {
  e.preventDefault();
  const data = new FormData(e.target);
  if (e.target.id === "start-form") {
    const group = data.get("group");
    if (runs.some((r) => r.group === group)) {
      $("#start-error").textContent =
        "这个群已有一场进行中的投票，请选择其他群。";
      return;
    }
    const project = projects.find((p) => p.id === Number(data.get("project")));
    runs.push({
      id: Date.now(),
      name: project.name,
      group,
      status: "RUNNING",
      progress: 1,
    });
    closeModal();
    location.hash = "admin/run";
    render();
    toast("已开始示例投票；没有向群发送消息");
  }
  if (e.target.id === "project-form") {
    const name = data.get("name").trim(),
      path = data.get("path").trim(),
      id = Number(e.target.dataset.id);
    if (!name || !path.startsWith("/") || path.split("/").includes("..")) {
      $("#project-error").textContent = "请填写项目名和有效的容器绝对路径。";
      return;
    }
    if (projects.some((p) => p.name === name && p.id !== id)) {
      $("#project-error").textContent = "项目名已存在。";
      return;
    }
    const p = projects.find((p) => p.id === id);
    const values = {
      name,
      path,
      description: data.get("description").trim(),
      source: "登记项目",
      count: 6,
    };
    if (p) Object.assign(p, values);
    else projects.push({ id: Date.now(), ...values });
    closeModal();
    render();
    toast("示例项目已保存");
  }
});
$("#theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme !== "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  $("#theme").textContent = dark ? "浅色模式" : "深色模式";
  $("#theme").setAttribute(
    "aria-label",
    dark ? "切换浅色主题" : "切换深色主题",
  );
});
addEventListener("hashchange", () => {
  render();
  window.scrollTo(0, 0);
});
render();
