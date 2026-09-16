/* Real AstrBot PageBridge client. No mock or unauthenticated fallback. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s),
    esc = (v) =>
      String(v ?? "").replace(
        /[&<>"']/g,
        (c) =>
          ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
          })[c],
      );
  const bridge = window.AstrBotPluginPage;
  let page = "run",
    projects = [],
    active = [],
    sessions = [],
    total = 0,
    offset = 0,
    config = null,
    draft = {},
    groupList = [],
    providers = [],
    settingsTab = "voting",
    configSearch = "",
    projectSearch = "",
    groupFilter = "",
    busy = false,
    connected = false,
    refreshing = false;
  let dialogOrigin = null,
    previewProject = null,
    editProject = null,
    browseRoot = "",
    browseRelative = "",
    refreshTimer = null,
    requestEpoch = 0;
  const titles = {
    run: ["投票工作区", "从一组图片，到一份共同完成的评选记录。"],
    projects: ["图片项目", "登记容器内的图片目录，预检后开始投票。"],
    history: ["历史与报告", "回看每一场投票，管理它生成的报告。"],
    settings: [
      "设置",
      "默认参数与本轮参数分开，让每次更改都有清晰的生效范围。",
    ],
  };
  const formatTime = (v) =>
    v && !Number.isNaN(Date.parse(v))
      ? new Date(v).toLocaleString("zh-CN", { hour12: false })
      : "—";
  const status = {
    PREPARING: "准备中",
    RUNNING: "轮播中",
    PAUSED: "已暂停",
    FINALIZING: "正在结算",
    COMPLETED: "已完成",
    CANCELLED: "已取消",
    FAILED: "失败",
  };
  const reportStatus = {
    generating: "生成中",
    ready: "可查看",
    missing: "无报告",
    cleaned: "已清理",
    failed: "生成失败",
  };
  const dirty = () =>
    config && JSON.stringify(draft) !== JSON.stringify(config.values);
  function toast(text) {
    const el = $("#toast");
    el.textContent = text;
    el.style.display = "block";
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => (el.style.display = "none"), 4000);
  }
  async function api(endpoint, body = null) {
    if (!bridge) throw Error("请从 AstrBot 插件页面打开");
    const response = await (body === null
      ? bridge.apiGet(endpoint)
      : bridge.apiPost(endpoint, body));
    if (response?.status === "error") throw Error(response.message);
    return response?.status === "ok" ? response.data : response;
  }
  async function get(endpoint, params = {}) {
    if (!bridge) throw Error("请从 AstrBot 插件页面打开");
    const response = await bridge.apiGet(endpoint, params);
    if (response?.status === "error") throw Error(response.message);
    return response?.status === "ok" ? response.data : response;
  }
  function connection(ok) {
    connected = ok;
    $("#connection").textContent = ok
      ? "已连接 · " + new Date().toLocaleTimeString()
      : "连接中断 · 暂停操作";
  }
  function nav() {
    return `<nav class="tabs" aria-label="工作区页面">${[
      ["run", "运行"],
      ["projects", "项目"],
      ["history", "历史与报告"],
      ["settings", "设置"],
    ]
      .map(
        ([id, label]) =>
          `<a href="#${id}" class="${id === page ? "active" : ""}" ${id === page ? 'aria-current="page"' : ""}>${label}</a>`,
      )
      .join("")}</nav>`;
  }
  // Small inline control icons, no network assets or new runtime dependency.
  const controlPaths = {
    refresh:'M20 7v5h-5 M4 17v-5h5 M6 7a7 7 0 0 1 12-1l2 3 M4 15l2 3a7 7 0 0 0 12-1',
    add:'M12 5v14 M5 12h14',
    play:'M8 5l11 7-11 7Z',
    edit:'m14 5 5 5 M4 20l4-1L20 7l-4-4L4 15Z',
    download:'M12 3v12 m-5-5 5 5 5-5 M5 16v5h14v-5',
    filter:'M4 6h16 M7 12h10 M10 18h4',
    save:'M5 3h12l4 4v14H3V3Z M7 3v6h10V3 M7 21v-7h10v7',
  };
  function decorateControls() {
    const names={refresh:'refresh',register:'add',start:'play',preflight:'play',edit:'edit',download:'download','filter-history':'filter',export:'refresh','save-config':'save'};
    document.querySelectorAll('button[data-action]').forEach(button=>{
      const name=names[button.dataset.action];
      if(!name || button.querySelector('.control-icon')) return;
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
      svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.classList.add('control-icon');
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',controlPaths[name]);svg.append(path);button.prepend(svg);
    });
  }
  function frame(body) {
    return `<div class="page-heading"><div><div class="eyebrow">IMAGE VOTE / WORKSPACE</div><h1 class="admin-title">${titles[page][0]}</h1><p>${titles[page][1]}</p></div><div class="actions" style="margin:0"><button data-action="refresh">刷新</button>${page === "run" ? '<button class="primary" data-action="start">开始投票</button>' : page === "projects" ? '<button class="primary" data-action="register">登记项目</button>' : ""}</div></div>${nav()}${!connected ? '<p class="error-banner">无法确认最新状态，请刷新连接后操作。未保存的配置草稿仍然保留。</p>' : ""}${body}`;
  }
  function render() {
    if (!config) return;
    const body =
      page === "run"
        ? runPage()
        : page === "projects"
          ? projectsPage()
          : page === "history"
            ? historyPage()
            : settingsPage();
    $("#app").innerHTML = frame(body);
    if (busy) $("#app").classList.add("loading");
    else $("#app").classList.remove("loading");
    decorateControls();
    loadThumbnails();
  }
  function runPage() {
    return `<div class="admin-stats"><span><b>${active.length}</b>场进行中</span><span><b>${projects.length}</b>个项目</span></div>${active.length ? active.map((r) => `<section class="run-grid"><div class="surface"><div class="label-row"><div><h2>${esc(r.project_name)}</h2><p class="subtle">群 ${esc(r.group_id)} · ${esc(r.short_id)}</p></div><span class="badge">${status[r.status] || esc(r.status)}</span></div>${r.active_candidate ? `<img class="run-image" data-thumb-session="${esc(r.id)}" data-thumb-candidate="${esc(r.active_candidate.id)}" alt="${esc(r.active_candidate.name)}">` : '<p class="muted">尚未成功发送图片</p>'}<div class="label-row"><b>${esc(r.active_character || "等待人物首图")}</b><span>${r.sent_count} / ${r.candidate_count} 张已发送</span></div><div class="progress"><i style="width:${r.candidate_count ? (r.sent_count / r.candidate_count) * 100 : 0}%"></i></div><p class="subtle">${r.vote_count} 张人物票 · ${r.participant_count} 人参与${r.seconds_until_next != null ? " · 下一人物约 " + Math.ceil(r.seconds_until_next) + " 秒" : ""}</p>${r.error_message ? `<p class="state-details">${esc(r.error_message)}</p>` : ""}<div class="actions">${["RUNNING", "PAUSED"].includes(r.status) ? `<button class="primary" data-control="${r.status === "PAUSED" ? "resume" : "pause"}" data-id="${esc(r.id)}">${r.status === "PAUSED" ? "继续" : "暂停"}</button><button data-control="finish" data-id="${esc(r.id)}">提前结束</button><button class="quiet danger" data-control="stop" data-id="${esc(r.id)}">取消本轮</button>` : '<span class="muted">正在收尾，请稍候</span>'}</div></div><aside class="surface"><h3>本轮参数</h3><div class="kv"><span>人物数</span><b>${r.character_count}</b><span>评分范围</span><b>${r.score_min}–${r.score_max}</b><span>人物间隔</span><b>${r.interval_seconds} 秒</b><span>最终等待</span><b>${r.final_grace_seconds} 秒</b><span>报告状态</span><b>${reportStatus[r.report_state]}</b></div><div class="notice">同一个人物就是一个投票窗口：该人物全部图片发完后，等待完整间隔再开始下一个人物。</div></aside></section>`).join("") : '<section class="surface empty"><h2>现在没有进行中的投票</h2><p>选择一个项目，预检后开始下一场。</p><button class="primary" data-action="start">选择项目</button></section>'}`;
  }
  function projectsPage() {
    return `<div class="toolbar project-toolbar"><input id="project-search" type="search" aria-label="搜索项目名称" placeholder="搜索项目名称" value="${esc(projectSearch)}"><span class="count">${projects.length} 个项目</span></div><div id="project-list" class="project-grid">${projectCards()}</div>`;
  }
  function projectCards() {
    return (
      projects
        .filter((p) =>
          p.name.toLowerCase().includes(projectSearch.toLowerCase()),
        )
        .map(
          (p) =>
            `<article class="surface project-card"><div class="project-media ${p.error ? "is-empty" : ""}"><span class="cover-fallback">${p.error ? "暂无预览" : "正在读取封面"}</span>${p.error ? "" : `<img data-thumb-project="${esc(p.name)}" alt="${esc(p.name)} 项目封面">`}<span class="project-source">${p.source === "registered" ? "已登记" : "目录项目"}</span></div><div class="project-content"><h2>${esc(p.name)}</h2><p class="project-description ${p.settings.description ? "" : "is-muted"}">${esc(p.settings.description || "添加项目说明，方便下次找到它。")}</p><details class="project-location"><summary>项目目录</summary><p class="project-path">${esc(p.path)}</p></details>${p.error ? `<p class="error">${esc(p.error)}</p>` : ""}<div class="project-options"><span>${p.settings.interval_seconds ? esc(p.settings.interval_seconds) + " 秒间隔" : "默认间隔"}</span><span>${p.settings.recursive == null ? "默认扫描" : p.settings.recursive ? "含子目录" : "当前目录"}</span></div><div class="actions project-actions"><button class="primary" data-project="${esc(p.name)}" data-action="preflight">预检与开始</button><button data-project="${esc(p.name)}" data-action="edit">${p.source === "registered" ? "编辑" : "登记设置"}</button>${p.source === "registered" ? `<button class="quiet danger" data-project="${esc(p.name)}" data-action="unregister">取消登记</button>` : ""}</div></div></article>`,
        )
        .join("") ||
      '<div class="empty">还没有项目。请登记一个容器内图片目录。</div>'
    );
  }
  function historyPage() {
    return `<div class="toolbar history-filter"><input id="group-filter" placeholder="按群号筛选" aria-label="按群号筛选" value="${esc(groupFilter)}"><button data-action="filter-history">筛选</button></div><div class="table-wrap"><table><thead><tr><th>项目 / 场次</th><th>群</th><th>投票</th><th>报告</th><th>操作</th></tr></thead><tbody>${sessions.map((r) => `<tr><td><b>${esc(r.project_name)}</b><br><small>${esc(formatTime(r.created_at))} · ${esc(r.short_id)}<br>${r.vote_count} 票 · ${r.sent_count}/${r.candidate_count} 张已发送</small></td><td>${esc(r.group_id)}</td><td><span class="status-label status-${esc(r.status.toLowerCase())}">${status[r.status] || esc(r.status)}</span></td><td><span class="badge neutral">${reportStatus[r.report_state]}</span>${r.report_error ? `<p class="error">${esc(r.report_error)}</p>` : ""}</td><td><div class="history-tools">${r.report_available || r.report_state === "ready" ? `<button class="download-action" data-action="download" data-id="${esc(r.id)}">下载</button><button class="quiet danger" data-action="cleanup" data-id="${esc(r.id)}">清理</button>` : ""}${["COMPLETED", "CANCELLED"].includes(r.status) && r.report_state !== "generating" ? `<button data-action="export" data-id="${esc(r.id)}">${r.report_state === "ready" ? "重新生成" : "生成报告"}</button>` : ""}${["COMPLETED", "CANCELLED", "FAILED"].includes(r.status) ? `<button class="quiet danger" data-action="purge" data-id="${esc(r.id)}">彻底删除</button>` : ""}</div></td></tr>`).join("")}</tbody></table>${sessions.length ? "" : '<div class="empty">没有符合条件的历史记录</div>'}</div><div id="pagination"><button data-action="previous" ${offset === 0 ? "disabled" : ""}>上一页</button><span class="subtle">共 ${total} 场 · 第 ${Math.floor(offset / 30) + 1} 页</span><button data-action="next" ${offset + 30 >= total ? "disabled" : ""}>下一页</button></div>`;
  }
  const categories = [
    ["voting", "投票规则"],
    ["paths", "项目与输出"],
    ["report", "报告与分享"],
    ["ai", "AI 总结"],
    ["permissions", "使用权限"],
    ["maintenance", "恢复与维护"],
  ];
  function field(key, definition) {
    const value = draft[key],
      id = "field-" + key,
      label = definition.description || key;
    const optionLabel = (option) => key === "report_image_policy"
      ? ({ character_cover: "每个人物一张高清，其余缩略图（省体积）", all: "全部图片保留高清（便于放大）" }[option] || option)
      : option;
    let input;
    if (definition.type === "bool")
      input = `<input id="${id}" type="checkbox" data-field="${key}" ${value ? "checked" : ""}>`;
    else if (definition.options)
      input = `<select id="${id}" data-field="${key}">${definition.options.map((o) => `<option value="${esc(o)}" ${String(value) === String(o) ? "selected" : ""}>${esc(optionLabel(o))}</option>`).join("")}</select>`;
    else if (key === "ai_provider_id")
      input = `<select id="${id}" data-field="${key}"><option value="">跟随群的默认模型</option>${providers.map((p) => `<option value="${esc(p.id)}" ${value === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}${value && !providers.some((p) => p.id === value) ? `<option selected value="${esc(value)}">${esc(value)}（当前不可用）</option>` : ""}</select>`;
    else if (definition.type === "text" || definition.type === "list")
      input = `<textarea id="${id}" data-field="${key}" data-type="${definition.type}">${esc(Array.isArray(value) ? value.join("\n") : value)}</textarea>`;
    else
      input = `<input id="${id}" data-field="${key}" type="${definition.type === "int" ? "number" : "text"}" value="${esc(value)}">`;
    return `<div class="form-row"><div><label for="${id}">${esc(label)}</label><p class="field-description">${esc(definition.hint || "")}${["score_min", "score_max", "default_interval_seconds", "final_grace_seconds"].includes(key) ? " 用于以后开始的投票。" : ""}</p></div><div>${input}</div></div>`;
  }
  function settingsPage() {
    const definitions = {
      ...config.schema[settingsTab]?.items,
      ...(settingsTab === "report" ? config.schema.notice?.items : {}),
    };
    const all = Object.values(config.schema).flatMap((g) =>
      Object.entries(g.items || {}),
    );
    const entries = configSearch
      ? all.filter(([key, f]) =>
          `${key} ${f.description} ${f.hint}`
            .toLowerCase()
            .includes(configSearch.toLowerCase()),
        )
      : Object.entries(definitions);
    return `<div class="savebar"><p id="dirty-label">${dirty() ? "有未保存的修改" : "已与实际配置同步"}<br><small>评分与间隔用于以后开始的投票；报告参数用于下次生成。</small></p><div class="actions" style="margin:0"><button data-action="discard" ${dirty() ? "" : "disabled"}>放弃修改</button><button id="save-config" class="primary" data-action="save-config" ${dirty() ? "" : "disabled"}>保存配置</button></div></div><div class="toolbar"><input id="config-search" aria-label="搜索配置" placeholder="搜索配置名称或说明" value="${esc(configSearch)}"></div><div class="settings-layout"><nav class="settings-nav" aria-label="配置分组">${categories.map(([key, label]) => `<button data-category="${key}" class="${key === settingsTab ? "active" : ""}">${label}</button>`).join("")}</nav><section class="settings-form">${entries.map(([key, f]) => field(key, f)).join("") || '<p class="empty">没有匹配的配置项</p>'}${settingsTab === "ai" ? '<div class="actions"><button data-action="prompt-preview">预览提示词</button><button data-action="prompt-default">恢复默认提示词</button></div>' : ""}<p id="config-error" class="error" role="alert"></p></section></div>`;
  }
  async function refresh(force = false) {
    if (refreshing) return;
    refreshing = true;
    try {
      const [p, a, h, c] = await Promise.all([
        get("projects"),
        get("sessions", { active: "true" }),
        get("sessions", {
          limit: 30,
          offset,
          group_id: groupFilter || undefined,
        }),
        get("config"),
      ]);
      projects = p;
      active = a.sessions;
      sessions = h.sessions;
      total = h.total;
      if (!config || force || !dirty()) {
        config = c;
        draft = structuredClone(c.values);
      }
      connection(true);
      render();
    } catch (e) {
      connection(false);
      if (config) render();
      else
        $("#app").innerHTML =
          `<div class="empty"><h2>无法打开工作区</h2><p>${esc(e.message)}</p><button data-action="refresh">重试</button></div>`;
      toast(e.message);
    } finally {
      refreshing = false;
    }
  }
  async function mutate(fn) {
    if (busy || !connected) return;
    busy = true;
    $("#app").classList.add("loading");
    try {
      await fn();
      await refresh();
    } catch (e) {
      toast(e.message);
      if (page === "settings" && $("#config-error"))
        $("#config-error").textContent = e.message;
    } finally {
      busy = false;
      $("#app").classList.remove("loading");
    }
  }
  function modal(title, html, cls = "") {
    const el = $("#modal");
    if (!el.open) dialogOrigin = document.activeElement;
    el.className = cls;
    el.innerHTML = `<div class="modal-head"><h2 id="modal-title">${esc(title)}</h2><button data-action="close">关闭</button></div>${html}`;
    decorateControls();
    if (!el.open) el.showModal();
  }
  function close() {
    $("#modal").close();
  }
  $("#modal").addEventListener("close", () => {
    if (dialogOrigin?.isConnected) dialogOrigin.focus();
  });
  function confirmAction(title, text, action, attrs = "") {
    modal(
      title,
      `<p>${esc(text)}</p><div class="actions"><button data-action="close">返回</button><button class="primary" data-action="${action}" ${attrs}>确认</button></div>`,
    );
  }
  async function chooseProject() {
    if (!projects.length) {
      location.hash = "projects";
      return;
    }
    modal(
      "选择投票项目",
      `<div class="directory-list">${projects.map((p) => `<button data-action="preflight" data-project="${esc(p.name)}">${esc(p.name)}</button>`).join("")}</div>`,
    );
  }
  async function preflight(name) {
    previewProject = name;
    modal("正在预检", "<p>读取项目图片与输出目录状态…</p>");
    try {
      const [p, g] = await Promise.all([
        get("projects/preview", { name }),
        get("groups", { refresh: "true" }),
      ]);
      groupList = g;
      if (!$("#modal").open) return;
      modal(
        "预检 · " + name,
        `<div class="facts"><span><b>${p.character_count}</b>个人物</span><span><b>${p.count}</b>张图片</span><span><b>${(p.total_size / 1024 / 1024).toFixed(1)}</b>MB</span><span><b>${Math.ceil(p.estimated_seconds / 60)}</b>分钟</span></div><p class="subtle">人物按首次出现排序，组内保持原顺序 · 评分 ${p.score_min}–${p.score_max} · 人物间隔 ${p.interval_seconds}秒（${p.interval_source === "project" ? "项目设置" : "全局默认"}）</p><div class="project-thumbs">${p.first.map((c, i) => `<img data-thumb-project="${esc(name)}" data-thumb-index="${i + 1}" alt="${esc(c.display_title)}">`).join("")}</div><details><summary>扫描明细</summary><p>首批：${p.first.map((c) => esc(c.source_filename)).join("、")}</p><p>末批：${p.last.map(esc).join("、")}</p><p>非图片文件：${p.invalid_files.map(esc).join("、") || "无"}</p><p>${p.warnings.map(esc).join("；")}</p></details>${!p.output_writable ? '<p class="error">输出目录不可写，请先调整路径设置。</p>' : ""}<label>目标群<select id="start-group">${g.map((x) => `<option value="${esc(x.umo)}">${esc(x.name)} · ${esc(x.id)} · ${esc(x.platform)}</option>`).join("")}</select></label>${!g.length ? '<p class="error">没有可用群，请检查 OneBot 连接与群白名单。</p>' : ""}<p id="start-error" class="error" role="alert"></p><div class="actions"><button data-action="close">返回</button><button class="primary" data-action="confirm-start" ${!g.length || !p.count || !p.output_writable ? "disabled" : ""}>开始向选定群发送图片</button></div>`,
      );
      decorateControls();
      loadThumbnails();
    } catch (e) {
      modal("预检失败", `<p class="error">${esc(e.message)}</p>`);
    }
  }
  function edit(name) {
    editProject = name || null;
    const p = projects.find((p) => p.name === name);
    modal(
      p ? "编辑项目" : "登记项目",
      `<form id="project-form"><label>项目名称<input name="name" maxlength="64" required value="${esc(p?.name || "")}"></label><label>容器内绝对路径<input name="path" id="project-path" required value="${esc(p?.path || "")}"></label><button type="button" data-action="browse">浏览目录</button><label>发送间隔（留空跟随默认）<input name="interval" type="number" min="1" value="${p?.settings.interval_seconds || ""}"></label><label>递归扫描<select name="recursive"><option value="">跟随默认</option><option value="true" ${p?.settings.recursive === true ? "selected" : ""}>开启</option><option value="false" ${p?.settings.recursive === false ? "selected" : ""}>关闭</option></select></label><label>说明<textarea name="description">${esc(p?.settings.description || "")}</textarea></label><p id="project-error" class="error" role="alert"></p><div class="actions"><button type="button" data-action="close">取消</button><button class="primary" type="submit">保存登记</button></div></form><section id="browser"></section>`,
    );
  }
  async function browse(root = "", relative = "") {
    const b = await get("browse", root ? { root, relative } : {});
    browseRoot = b.root || "";
    browseRelative = b.relative || "";
    $("#browser").innerHTML =
      `<h3>选择容器目录</h3><p class="subtle">${esc(b.path || "从允许浏览的根目录开始")}</p><div class="directory-list">${!root ? b.roots.map((r) => `<button type="button" data-root="${esc(r)}">${esc(r)}</button>`).join("") : `<button type="button" data-browse="..">返回上层</button>${b.directories.map((x) => `<button type="button" data-browse="${esc(x.relative)}">${esc(x.name)}</button>`).join("")}<button class="primary" type="button" data-choose-path="${esc(b.path)}">使用此目录</button>`}</div><p class="subtle">新增挂载目录可先在设置的「网页目录浏览根目录」中添加。</p>`;
  }
  const thumbCache = new Map();
  async function loadThumbnails() {
    const nodes = [
      ...document.querySelectorAll("[data-thumb-project],[data-thumb-session]"),
    ];
    for (const el of nodes) {
      if (el.dataset.loaded) continue;
      el.dataset.loaded = "yes";
      const params = el.dataset.thumbProject
        ? {
            project: el.dataset.thumbProject,
            index: el.dataset.thumbIndex || 1,
          }
        : {
            session_id: el.dataset.thumbSession,
            candidate_id: el.dataset.thumbCandidate,
          };
      const key = JSON.stringify(params);
      try {
        let value = thumbCache.get(key);
        if (!value) {
          value = await get("thumbnail", params);
          if (thumbCache.size > 60) thumbCache.clear();
          thumbCache.set(key, value);
        }
        if (el.isConnected) {
          el.onload = () => el.parentElement.classList.add("cover-loaded");
          el.onerror = () => { el.style.display="none"; const label=el.parentElement.querySelector(".cover-fallback"); if(label) label.textContent="图片暂不可用"; };
          el.src = value.image;
        }
      } catch (e) {
        if (el.isConnected) {
          el.removeAttribute("src");
          el.alt = "图片暂不可用";
          el.style.display = "none";
          const label=el.parentElement.querySelector(".cover-fallback");
          if(label) label.textContent="图片暂不可用";
        }
      }
    }
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.action === "close") {
      close();
      return;
    }
    if (b.dataset.category) {
      settingsTab = b.dataset.category;
      configSearch = "";
      render();
      return;
    }
    if (b.dataset.control) {
      const action = b.dataset.control,
        id = b.dataset.id;
      if (["finish", "stop"].includes(action)) {
        confirmAction(
          action === "finish" ? "提前结束这场投票？" : "取消这场投票？",
          action === "finish"
            ? "停止后续图片发送，按已收评分结算。"
            : "停止轮播并保留评分，不自动生成报告。",
          "confirm-control",
          `data-control-action="${action}" data-id="${esc(id)}"`,
        );
        return;
      }
      await mutate(() => api("sessions/control", { session_id: id, action }));
      return;
    }
    try {
      if (b.dataset.root) {
        await browse(b.dataset.root);
        return;
      }
      if (b.dataset.browse) {
        if (b.dataset.browse === "..") {
          const parts = browseRelative.split("/").filter((x) => x && x !== ".");
          parts.pop();
          if (!parts.length && browseRelative === ".") await browse();
          else await browse(browseRoot, parts.join("/"));
        } else await browse(browseRoot, b.dataset.browse);
        return;
      }
      if (b.dataset.choosePath) {
        $("#project-path").value = b.dataset.choosePath;
        $("#browser").innerHTML = "";
        return;
      }
      switch (b.dataset.action) {
        case "refresh":
          await refresh();
          break;
        case "start":
          await chooseProject();
          break;
        case "preflight":
          await preflight(b.dataset.project);
          break;
        case "register":
          edit();
          break;
        case "edit":
          edit(b.dataset.project);
          break;
        case "browse":
          await browse();
          break;
        case "confirm-start":
          b.disabled = true;
          try {
            await api("sessions/start", {
              project: previewProject,
              umo: $("#start-group").value,
            });
            close();
            location.hash = "run";
            await refresh();
            toast("投票已开始");
          } catch (error) {
            $("#start-error").textContent = error.message;
            b.disabled = false;
          }
          break;
        case "unregister":
          confirmAction(
            "取消项目登记？",
            "只移除登记项，不删除原始图片和历史评分。",
            "confirm-unregister",
            `data-project="${esc(b.dataset.project)}"`,
          );
          break;
        case "confirm-unregister":
          await mutate(async () => {
            await api("projects/unregister", {
              name: b.dataset.project,
              confirmed: true,
            });
            close();
          });
          break;
        case "confirm-control":
          await mutate(async () => {
            await api("sessions/control", {
              session_id: b.dataset.id,
              action: b.dataset.controlAction,
              confirmed: true,
            });
            close();
          });
          break;
        case "export":
          modal(
            "生成报告",
            `<p>默认复用已保存的 AI 总结。</p><label><span><input type="checkbox" id="export-ai"> 重新生成 AI 总结（会调用模型）</span></label><div class="actions"><button data-action="close">返回</button><button class="primary" data-action="confirm-export" data-id="${esc(b.dataset.id)}">生成报告</button></div>`,
          );
          break;
        case "confirm-export":
          await mutate(async () => {
            await api("reports/export", {
              session_id: b.dataset.id,
              regenerate_ai: $("#export-ai").checked,
            });
            close();
            toast("报告已开始生成");
          });
          break;
        case "cleanup":
          confirmAction(
            "清理这份报告？",
            "只删除该场次的派生报告，保留投票记录和原图。",
            "confirm-cleanup",
            `data-id="${esc(b.dataset.id)}"`,
          );
          break;
        case "confirm-cleanup":
          await mutate(async () => {
            await api("reports/cleanup", {
              session_id: b.dataset.id,
              confirmed: true,
            });
            close();
          });
          break;
        case "purge":
          confirmAction(
            "彻底删除这场投票？",
            "会同时删除这场投票的投票记录（票与候选）和报告文件，不可恢复；群聊消息与原图不受影响。",
            "confirm-purge",
            `data-id="${esc(b.dataset.id)}"`,
          );
          break;
        case "confirm-purge":
          await mutate(async () => {
            const result = await api("sessions/purge", { session_id: b.dataset.id, confirmed: true });
            close();
            toast(`已彻底删除：投票 ${result.votes} 条 · 候选 ${result.candidates} 条 · 报告 ${result.reports} 个`);
          });
          break;
        case "download":
          await bridge.download("reports/download", {
            session_id: b.dataset.id,
          });
          break;
        case "filter-history":
          groupFilter = $("#group-filter").value.trim();
          offset = 0;
          await refresh();
          break;
        case "next":
          offset += 30;
          await refresh();
          break;
        case "previous":
          offset = Math.max(0, offset - 30);
          await refresh();
          break;
        case "discard":
          draft = structuredClone(config.values);
          render();
          break;
        case "save-config":
          await mutate(async () => {
            const next = await api("config", {
              revision: config.revision,
              values: draft,
            });
            config = next;
            draft = structuredClone(next.values);
            toast("配置已保存并重新读取");
          });
          break;
        case "prompt-default":
          draft.ai_prompt_template = config.schema.ai.items.ai_prompt_template.default;
          render();
          break;
        case "prompt-preview":
          {
            const value = await api("prompt/preview", {
              template: draft.ai_prompt_template,
            });
            modal(
              "提示词预览",
              `<p class="subtle">仅展开变量，没有调用模型。</p><pre style="white-space:pre-wrap">${esc(value.prompt)}</pre>`,
            );
          }
          break;
      }
    } catch (error) {
      toast(error.message);
    }
  });
  document.addEventListener("input", (e) => {
    if (e.target.id === "project-search") {
      projectSearch = e.target.value;
      $("#project-list").innerHTML = projectCards();
      decorateControls();
      loadThumbnails();
    }
    if (e.target.id === "config-search") {
      configSearch = e.target.value;
      const position = e.target.selectionStart;
      render();
      $("#config-search").focus();
      $("#config-search").setSelectionRange(position, position);
    }
    const key = e.target.dataset.field;
    if (key) {
      draft[key] =
        e.target.type === "checkbox"
          ? e.target.checked
          : e.target.type === "number"
            ? Number(e.target.value)
            : e.target.dataset.type === "list"
              ? e.target.value
                  .split("\n")
                  .map((s) => s.trim())
                  .filter(Boolean)
              : e.target.value;
      $("#dirty-label").firstChild.textContent = dirty()
        ? "有未保存的修改"
        : "已与实际配置同步";
      $("#save-config").disabled = !dirty();
    }
  });
  document.addEventListener("submit", async (e) => {
    if (e.target.id !== "project-form") return;
    e.preventDefault();
    const f = new FormData(e.target),
      button = e.target.querySelector("[type=submit]");
    button.disabled = true;
    try {
      await api("projects/register", {
        old_name: editProject,
        name: f.get("name"),
        path: f.get("path"),
        description: f.get("description"),
        interval_seconds: f.get("interval") ? Number(f.get("interval")) : null,
        recursive:
          f.get("recursive") === "" ? null : f.get("recursive") === "true",
      });
      close();
      await refresh();
    } catch (error) {
      $("#project-error").textContent = error.message;
      button.disabled = false;
    }
  });
  addEventListener("hashchange", () => {
    page = ["run", "projects", "history", "settings"].includes(
      location.hash.slice(1),
    )
      ? location.hash.slice(1)
      : "run";
    render();
  });
  addEventListener("beforeunload", (e) => {
    if (dirty()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  async function poll() {
    if (
      !document.hidden &&
      !$("#modal").open &&
      !busy &&
      !refreshing &&
      page !== "settings"
    ) {
      await refresh();
    }
    refreshTimer = setTimeout(poll, 5000);
  }
  async function init() {
    if (!bridge) {
      $("#app").innerHTML =
        '<div class="empty"><h2>请从 AstrBot 插件页面打开</h2><p>这个工作区需要已登录的 AstrBot PageBridge，未提供未鉴权的备用入口。</p></div>';
      $("#connection").textContent = "未连接";
      return;
    }
    try {
      const context = await bridge.ready();
      const theme = (c) =>
        (document.documentElement.dataset.theme = c.isDark ? "dark" : "light");
      theme(context || {});
      if (bridge.onContext) bridge.onContext(theme);
      page = ["run", "projects", "history", "settings"].includes(
        location.hash.slice(1),
      )
        ? location.hash.slice(1)
        : "run";
      providers = await get("providers");
      await refresh();
      poll();
    } catch (error) {
      $("#app").innerHTML =
        `<div class="empty"><h2>连接失败</h2><p>${esc(error.message)}</p><button data-action="refresh">重试</button></div>`;
    }
  }
  init();
})();
