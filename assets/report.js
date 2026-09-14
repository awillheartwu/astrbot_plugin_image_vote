/* Offline report viewer. No remote assets, fetch, or runtime dependencies. */
(function () {
  "use strict";
  const node = document.getElementById("report-data"),
    root = document.getElementById("report-app");
  if (!node || !root) return;
  let d;
  try {
    d = JSON.parse(node.textContent);
  } catch (e) {
    return;
  }
  const esc = (v) =>
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
  const rows = d.candidates || [],
    people = d.participants || [],
    votes = d.votes || [],
    s = d.session,
    m = d.metrics || {},
    stats = d.statistics;
  const byId = new Map(rows.map((r) => [r.candidate_id, r])),
    low = d.methodology?.minimum_votes || 5;
  let page = "overview",
    query = "",
    sort = "rank",
    filter = "all",
    layout = "gallery",
    selected = rows[0]?.candidate_id,
    person = people[0]?.id,
    personQuery = "",
    personSort = "score",
    currentDetail = null,
    returnImage = null;
  const avg = (v) => (v == null ? "暂无评分" : Number(v).toFixed(2)),
    pct = (v) => (v == null ? "—" : (v * 100).toFixed(1) + "%");
  const formatTime = (v) =>
    v && !Number.isNaN(Date.parse(v))
      ? new Date(v).toLocaleString("zh-CN", { hour12: false })
      : "—";
  const title = (r) => esc(r.display_title);
  const img = (r, cls = "", main = false) =>
    `<img class="${cls}" src="${esc((main ? r.main_image : r.thumbnail) || "")}" alt="${title(r)}" loading="lazy">`;
  const badge = (r) =>
    (r.send_status === "pending"
      ? '<span class="badge neutral">未展示</span>'
      : r.send_status === "send_failed"
        ? '<span class="badge warning">发送失败</span>'
        : !r.vote_count
          ? '<span class="badge neutral">已展示未获票</span>'
          : "") +
    (r.low_sample
      ? ` <span class="badge warning">仅 ${r.vote_count} 票</span>`
      : "");
  const avatar = (p) =>
    p.avatar
      ? `<img class="avatar" src="${esc(p.avatar)}" alt="">`
      : `<span class="placeholder" aria-hidden="true">${esc(p.name.slice(0, 1))}</span>`;
  function bars(counts = {}) {
    const size = s.score_max - s.score_min + 1,
      step = size > 10 ? Math.ceil(size / 10) : 1,
      bins = [];
    for (let start = s.score_min; start <= s.score_max; start += step) {
      const end = Math.min(s.score_max, start + step - 1);
      let n = 0;
      for (let i = start; i <= end; i++) n += Number(counts[i] || 0);
      bins.push([start === end ? start + "分" : start + "–" + end + "分", n]);
    }
    const max = Math.max(1, ...bins.map((b) => b[1]));
    return (
      bins
        .map(
          ([label, n]) =>
            `<div class="horizontal-bar"><span>${label}</span><i style="width:${(n / max) * 100}%"></i><span>${n}票</span></div>`,
        )
        .join("") +
      (size > 10
        ? `<details class="full-data"><summary>精确分值明细</summary><p>${Array.from({ length: size }, (_, i) => `${s.score_min + i}分 ${counts[s.score_min + i] || 0}票`).join(" · ")}</p></details>`
        : "")
    );
  }
  function head() {
    return `<header class="report-header"><span class="brand">LIRATING</span><button data-action="theme" class="quiet">${document.documentElement.dataset.theme === "dark" ? "浅色模式" : "深色模式"}</button></header><div class="eyebrow">THE VOTING JOURNAL</div><h1>${esc(s.project_name)}</h1><p class="muted">${esc(formatTime(s.finished_at || s.started_at))} · 评分范围 ${s.score_min}-${s.score_max} ${m.partial ? '<span class="badge neutral">部分结果</span>' : ""} ${s.status === "CANCELLED" ? '<span class="badge warning">已取消场次的保留结果</span>' : ""}</p><nav class="report-view-nav" aria-label="报告导航">${[["overview", "概览"], ["images", "全部图片"], ...(d.participant_details_available ? [["people", "按人查看"]] : [])].map(([key, label]) => `<button data-page="${key}" class="${page === key ? "active" : ""}" ${page === key ? 'aria-current="page"' : ""}>${label}</button>`).join("")}</nav>`;
  }
  function cover(r) {
    return `<button class="art-card" data-detail="${esc(r.candidate_id)}" aria-label="查看 ${title(r)}">${img(r, "", true)}<span class="art-caption"><span class="rank">排名 ${r.rank ?? "—"}</span><h3>${title(r)}</h3><p>${avg(r.average_score)} / ${s.score_max} · ${r.vote_count}票</p></span></button>`;
  }
  function overview() {
    let featured = (d.insights?.featured || [])
        .map((id) => byId.get(id))
        .filter(Boolean),
      qualified = featured.length > 0;
    if (!qualified) featured = rows.filter((r) => r.vote_count).slice(0, 3);
    const dispersed = (d.insights?.dispersed || [])
        .map((id) => byId.get(id))
        .filter(Boolean),
      counts = {};
    rows.forEach((r) =>
      Object.entries(r.score_distribution).forEach(
        ([k, v]) => (counts[k] = (counts[k] || 0) + v),
      ),
    );
    const cards =
      featured.length === 3
        ? cover(featured[0]) +
          `<div class="art-stack">${featured.slice(1).map(cover).join("")}</div>`
        : featured.map(cover).join("");
    return `<div class="facts"><span><b>${m.sent_count ?? "—"} / ${rows.length}</b> 张已展示</span><span><b>${stats.unique_voters}</b> 位参与者</span><span><b>${stats.total_valid_votes}</b> 张有效票</span><span><b>${avg(m.votes_per_sent_candidate)}</b> 每张平均票数</span></div>${featured.length ? `<section class="report-cover ${featured.length === 1 ? "one" : featured.length === 2 ? "two" : ""}">${cards}</section><div class="gallery-note"><span>${qualified ? "展示至少 " + low + " 票的高分项" : "样本较少，请结合票数阅读结果"}</span><button class="text-link" data-page="images">完整排名 →</button></div>` : '<div class="surface empty"><h2>本轮尚无有效评分</h2><button data-page="images">查看图片清单</button></div>'}<div class="insights"><section><div class="section-title"><h2>本轮看点</h2></div><h3>分数与票数一起看</h3><p class="muted">${m.low_sample_count || 0} 张图片少于 ${low} 票，${m.unrated_count || 0} 张已展示但暂无评分。</p><h3>评分较分散的图片</h3>${dispersed.map((r) => `<p><button class="text-link" data-detail="${esc(r.candidate_id)}">${title(r)}</button> · 标准差 ${avg(r.standard_deviation)} · ${r.vote_count}票</p>`).join("") || '<p class="muted">暂无达到样本门槛的图片。</p>'}${
      (d.insights?.low_rated || []).length
        ? `<details class="method"><summary>本轮相对较低分的图片</summary>${d.insights.low_rated
            .map((id) => byId.get(id))
            .filter(Boolean)
            .map(
              (r) =>
                `<p><button class="text-link" data-detail="${esc(r.candidate_id)}">${title(r)}</button> · ${avg(r.average_score)} / ${s.score_max} · ${r.vote_count}票</p>`,
            )
            .join(
              "",
            )}<p>仅在至少 ${low} 票的图片中比较，不将零票或未展示图片视为低分。</p></details>`
        : ""
    }${d.ai_summary ? `<details class="method"><summary>AI 统计解读</summary><p style="white-space:pre-wrap">${esc(d.ai_summary)}</p></details>` : ""}</section><section><div class="section-title"><h2>分值分布</h2></div>${bars(counts)}<p class="report-note">分歧表示评分分散，不代表发生争论。</p></section></div><section style="margin-top:32px"><div class="section-title"><h2>每张图片获得了多少票</h2><small>按展示顺序</small></div><div class="flow-bars">${[
      ...rows,
    ]
      .sort((a, b) => a.display_index - b.display_index)
      .map(
        (r) =>
          `<div title="${title(r)}"><span>${r.vote_count}</span><i style="height:${Math.max(2, (r.vote_count / Math.max(1, ...rows.map((x) => x.vote_count))) * 65)}px;opacity:${r.send_status === "sent" ? ".7" : ".2"}"></i><span>#${r.display_index}</span></div>`,
      )
      .join("")}</div></section>${characters()}`;
  }
  function characters() {
    const chars = d.characters || [];
    return !chars.length || chars.length >= rows.length
      ? ""
      : `<details class="method"><summary>角色汇总（多张图片合并）</summary><div class="table-wrap"><table><thead><tr><th>角色</th><th>图片数</th><th>票数</th><th>均分</th></tr></thead><tbody>${chars.map((c) => `<tr><td>${esc(c.character)}</td><td>${c.candidate_count}</td><td>${c.vote_count}</td><td>${avg(c.average_score)}</td></tr>`).join("")}</tbody></table></div></details>`;
  }
  function filtered() {
    return rows
      .filter(
        (r) =>
          r.display_title.toLowerCase().includes(query.toLowerCase()) &&
          (filter === "all" ||
            (filter === "few" && r.low_sample) ||
            (filter === "zero" && r.send_status === "sent" && !r.vote_count) ||
            (filter === "failed" && r.send_status === "send_failed") ||
            (filter === "pending" && r.send_status === "pending")),
      )
      .sort((a, b) =>
        sort === "index"
          ? a.display_index - b.display_index
          : sort === "votes"
            ? b.vote_count - a.vote_count
            : sort === "std"
              ? (b.standard_deviation ?? -1) - (a.standard_deviation ?? -1)
              : (a.rank ?? 1e12) - (b.rank ?? 1e12),
      );
  }
  function detail(r) {
    if (!r) return "";
    currentDetail = r.candidate_id;
    const pv = votes
      .filter((v) => v.candidate_id === r.candidate_id)
      .sort((a, b) => b.score - a.score);
    return `<section class="surface detail"><div class="detail-nav"><button data-step="-1" aria-label="上一张图片">上一张</button><button data-step="1" aria-label="下一张图片">下一张</button></div><div class="detail-head"><div><div class="eyebrow">IMAGE ${r.display_index}</div><h2>${title(r)}</h2></div><button data-action="enlarge" data-id="${esc(r.candidate_id)}" class="quiet">查看大图</button></div><div class="score-line"><b>${avg(r.average_score)} / ${s.score_max}</b><span>${r.vote_count}票</span></div>${badge(r)}${img(r, "detail-img", true)}${bars(r.score_distribution)}<p class="report-note">${r.vote_count < 2 ? "样本不足，暂不比较分歧" : "标准差 " + avg(r.standard_deviation)} · 评分覆盖 ${pct(r.coverage)}</p>${
      d.participant_details_available
        ? `<h3>参与者评分</h3><div class="data-table">${
            pv
              .map((v) => {
                const p = people.find((p) => p.id === v.participant_id);
                return p
                  ? `<div class="person-row">${avatar(p)}<button class="text-link" data-person="${esc(p.id)}">${esc(p.name)}</button><span class="right">${v.score}分</span></div>`
                  : "";
              })
              .join("") || '<p class="muted">暂无评分</p>'
          }</div>`
        : '<p class="report-note">本报告不包含参与者明细。</p>'
    }<details class="full-data"><summary>原始文件信息</summary><p>${esc(r.source_filename)}</p></details></section>`;
  }
  function results() {
    const list = filtered();
    if (!list.some((r) => r.candidate_id === selected))
      selected = list[0]?.candidate_id;
    if (!list.length)
      return '<div class="empty"><h3>没有符合条件的图片</h3><button data-action="clear">清除筛选</button></div>';
    if (layout === "gallery")
      return `<div class="report-grid">${list.map((r) => `<button data-detail="${esc(r.candidate_id)}">${img(r)}<h3>${title(r)}</h3><p>${avg(r.average_score)} / ${s.score_max} · ${r.vote_count}票</p>${badge(r)}</button>`).join("")}</div>`;
    return `<div class="split"><div class="table-wrap"><table><thead><tr><th>排名</th><th>图片</th><th>均分 / ${s.score_max}</th><th>票数</th></tr></thead><tbody>${list.map((r) => `<tr class="${r.candidate_id === selected ? "selected" : ""}"><td>${r.rank ?? "—"}</td><td><div class="item-cell">${img(r, "thumb")}<div><button class="row-choice" data-select="${esc(r.candidate_id)}">${title(r)}</button><small>#${r.display_index}</small><div>${badge(r)}</div></div></div></td><td>${avg(r.average_score)}</td><td>${r.vote_count}</td></tr>`).join("")}</tbody></table></div>${detail(byId.get(selected))}</div>`;
  }
  function images() {
    const voted = rows.filter((r) => (r.vote_count || 0) > 0).length;
    return `<p class="page-summary">共 ${rows.length} 张图 · 已展示 ${m.sent_count ?? rows.length} 张 · ${m.total_valid_votes ?? 0} 张有效票 · ${m.unique_voters ?? 0} 位参与者 · 其中 ${voted} 张有票</p><div class="toolbar"><input id="image-search" type="search" aria-label="搜索图片名称" placeholder="搜索图片名称" value="${esc(query)}"><label>排序<select id="image-sort"><option value="rank">排名</option><option value="index">原始顺序</option><option value="votes">票数</option><option value="std">分歧</option></select></label><select id="image-filter" aria-label="筛选图片"><option value="all">全部图片</option><option value="few">少量评分</option><option value="zero">已展示未获票</option><option value="failed">发送失败</option><option value="pending">未展示</option></select><div class="view-controls"><button data-layout="gallery" aria-pressed="${layout === "gallery"}">图册</button><button data-layout="list" aria-pressed="${layout === "list"}">列表</button></div><span id="result-count" class="count">${filtered().length} / ${rows.length} 张</span></div><div id="results">${results()}</div>`;
  }
  function personMenu() {
    return (
      people
        .filter((p) => p.name.toLowerCase().includes(personQuery.toLowerCase()))
        .map(
          (p) =>
            `<button data-person="${esc(p.id)}" class="${person === p.id ? "active" : ""}">${avatar(p)}<span>${esc(p.name)}<small>${p.vote_count}张已评分</small></span></button>`,
        )
        .join("") || '<p class="muted">未找到参与者</p>'
    );
  }
  function personDetail() {
    const p = people.find((p) => p.id === person);
    if (!p) return '<div class="empty">暂无参与者明细</div>';
    const own = votes.filter(
      (v) => v.participant_id === person && byId.has(v.candidate_id),
    );
    own.sort((a, b) =>
      personSort === "index"
        ? byId.get(a.candidate_id).display_index -
          byId.get(b.candidate_id).display_index
        : personSort === "time"
          ? String(b.updated_at || b.created_at || "").localeCompare(
              String(a.updated_at || a.created_at || ""),
            )
          : b.score - a.score,
    );
    return `<div class="person-heading">${avatar(p)}<div><h2>${esc(p.name)}</h2><span class="muted">本轮最终有效评分</span></div></div>${returnImage ? '<button class="text-link" data-action="return-image">返回刚才的图片 →</button>' : ""}<div class="facts"><span><b>${p.vote_count}</b>张已评分</span><span><b>${avg(p.average_score)}</b>个人均分</span><span><b>${pct(p.coverage)}</b>评分覆盖</span></div><div class="toolbar"><label>排序<select id="person-sort"><option value="score">个人分数</option><option value="index">原始顺序</option><option value="time">最后更新时间</option></select></label></div><div class="report-grid">${own
      .map((v) => {
        const r = byId.get(v.candidate_id);
        return `<button data-detail="${esc(r.candidate_id)}">${img(r)}<h3>${title(r)}</h3><b class="accent">${v.score} / ${s.score_max}</b> <small>本轮均分 ${avg(r.average_score)}</small>${v.updated_at ? `<p class="subtle">最后更新 ${esc(formatTime(v.updated_at))}</p>` : ""}</button>`;
      })
      .join(
        "",
      )}</div><p class="report-note">评分覆盖以成功展示的图片数为分母。这里不展示完整改票历史。</p>`;
  }
  function peoplePage() {
    const rated = people.reduce((sum, p) => sum + (p.vote_count || 0), 0);
    return `<p class="page-summary">${people.length} 位参与者 · 共 ${rows.length} 张图 · 个人评分合计 ${rated} 张</p><div class="people-layout"><aside><input id="people-search" type="search" placeholder="搜索参与者" aria-label="搜索参与者" value="${esc(personQuery)}"><div id="people-menu" class="people-menu">${personMenu()}</div></aside><section id="person-detail">${personDetail()}</section></div>`;
  }
  function footer() {
    return `<details class="method"><summary>统计口径与场次信息</summary><p>每人每图保留一条有效评分。排名按平均分、票数、原始顺序排列。零票不排名；少于 ${low} 票提醒样本较少。标准差使用总体公式，单票不称为一致认可。覆盖率衡量本轮参与者对已展示图片的填写情况，不是全群参与率。</p><p>会话 ${esc(s.short_id)}${s.group_id ? " · 群 " + esc(s.group_id) : ""} · ${esc(s.status)}${m.legacy_unexposed_votes ? " · " + m.legacy_unexposed_votes + "张历史未展示图片评分已从覆盖率排除" : ""}</p>${d.fallback_reason ? "<p>单文件超限，已回退目录版。请保留完整目录。</p>" : ""}</details>`;
  }
  function render() {
    root.innerHTML =
      head() +
      `<div class="report-body">${page === "overview" ? overview() : page === "images" ? images() : peoplePage()}</div>` +
      footer();
    if (page === "images") {
      root.querySelector("#image-sort").value = sort;
      root.querySelector("#image-filter").value = filter;
    }
    if (page === "people" && root.querySelector("#person-sort"))
      root.querySelector("#person-sort").value = personSort;
  }
  const dialog = document.createElement("dialog");
  dialog.className = "report-modal";
  dialog.setAttribute("aria-labelledby", "report-dialog-title");
  document.body.appendChild(dialog);
  let origin;
  dialog.addEventListener("close", () => {
    if (origin?.isConnected) origin.focus();
  });
  function show(r, large = false) {
    if (!r) return;
    if (!dialog.open) origin = document.activeElement;
    dialog.innerHTML = `<div class="modal-head"><h2 id="report-dialog-title">${title(r)}</h2><button data-action="close">关闭</button></div>${large ? img(r, "", true) : detail(r)}`;
    if (!dialog.open) dialog.showModal();
  }
  function update() {
    root.querySelector("#results").innerHTML = results();
    root.querySelector("#result-count").textContent =
      filtered().length + " / " + rows.length + " 张";
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || (!root.contains(b) && !dialog.contains(b))) return;
    if (b.dataset.page) {
      page = b.dataset.page;
      render();
    } else if (b.dataset.detail) show(byId.get(b.dataset.detail));
    else if (b.dataset.select) {
      selected = b.dataset.select;
      update();
    } else if (b.dataset.person) {
      if (page !== "people") returnImage = currentDetail;
      person = b.dataset.person;
      page = "people";
      if (dialog.open) dialog.close();
      render();
    } else if (b.dataset.layout) {
      layout = b.dataset.layout;
      render();
    } else if (b.dataset.step) {
      let list = filtered();
      if (!list.some((r) => r.candidate_id === currentDetail)) list = rows;
      const i = list.findIndex((r) => r.candidate_id === currentDetail);
      const next =
        list[(i + Number(b.dataset.step) + list.length) % list.length];
      if (dialog.open) show(next);
      else {
        selected = next.candidate_id;
        update();
      }
    } else if (b.dataset.action === "return-image") {
      selected = returnImage;
      page = "images";
      layout = "list";
      if (!filtered().some((r) => r.candidate_id === selected)) {
        query = "";
        filter = "all";
      }
      render();
    } else if (b.dataset.action === "close") dialog.close();
    else if (b.dataset.action === "enlarge") show(byId.get(b.dataset.id), true);
    else if (b.dataset.action === "theme") {
      document.documentElement.dataset.theme =
        document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      render();
    } else if (b.dataset.action === "clear") {
      query = "";
      filter = "all";
      render();
    }
  });
  root.addEventListener("input", (e) => {
    if (e.target.id === "image-search") {
      query = e.target.value;
      update();
    } else if (e.target.id === "people-search") {
      personQuery = e.target.value;
      root.querySelector("#people-menu").innerHTML = personMenu();
    }
  });
  root.addEventListener("change", (e) => {
    if (e.target.id === "image-sort") {
      sort = e.target.value;
      update();
    } else if (e.target.id === "image-filter") {
      filter = e.target.value;
      update();
    } else if (e.target.id === "person-sort") {
      personSort = e.target.value;
      root.querySelector("#person-detail").innerHTML = personDetail();
      root.querySelector("#person-sort").value = personSort;
    }
  });
  try {
    render();
    document.getElementById("report-fallback").hidden = true;
  } catch (e) {
    root.replaceChildren();
    console.error("Report enhancement unavailable", e);
  }
})();
