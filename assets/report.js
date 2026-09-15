/* Offline character-grouped report viewer. No remote assets or runtime dependencies. */
(function () {
  "use strict";
  const node = document.getElementById("report-data"), root = document.getElementById("report-app");
  if (!node || !root) return;
  let d;
  try { d = JSON.parse(node.textContent); } catch (_) { return; }
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
  const s = d.session || {}, rows = d.candidates || [], characters = d.characters || [];
  const people = d.participants || [], votes = d.votes || [], metrics = d.metrics || {}, stats = d.statistics || {};
  const byImage = new Map(rows.map((row) => [row.candidate_id, row]));
  const byCharacter = new Map(characters.map((item) => [item.character, item]));
  const imagesFor = (character) => (character.candidate_ids || []).map((id) => byImage.get(id)).filter(Boolean);
  let page = "overview", query = "", selectedPerson = people[0]?.id, personQuery = "";
  const avg = (v) => v == null ? "暂无评分" : Number(v).toFixed(2);
  const score = (v) => v == null ? "暂无评分" : `${Number(v).toFixed(2)} / ${s.score_max}`;
  const pct = (v) => v == null ? "—" : (Number(v) * 100).toFixed(1) + "%";
  const formatTime = (v) => v && !Number.isNaN(Date.parse(v)) ? new Date(v).toLocaleString("zh-CN", {hour12:false}) : "—";
  const image = (row, main = false) => `<img src="${esc((main ? row.main_image : row.thumbnail) || "")}" alt="${esc(row.display_title)}" loading="lazy">`;
  const avatar = (person) => person.avatar ? `<img class="avatar" src="${esc(person.avatar)}" alt="">` : `<span class="placeholder" aria-hidden="true">${esc((person.name || "?").slice(0,1))}</span>`;
  function bars(counts = {}) {
    const size = Number(s.score_max) - Number(s.score_min) + 1, step = size > 10 ? Math.ceil(size / 10) : 1, bins = [];
    for (let start = Number(s.score_min); start <= Number(s.score_max); start += step) {
      const end = Math.min(Number(s.score_max), start + step - 1); let count = 0;
      for (let value = start; value <= end; value++) count += Number(counts[value] || 0);
      bins.push([start === end ? `${start}分` : `${start}–${end}分`, count]);
    }
    const max = Math.max(1, ...bins.map((item) => item[1]));
    return bins.map(([label, count]) => `<div class="horizontal-bar"><span>${label}</span><i style="width:${count / max * 100}%"></i><span>${count}票</span></div>`).join("");
  }
  function header() {
    const navigation = [["overview","概览"],["images","全部图片"],...(d.participant_details_available ? [["people","按人查看"]] : [])];
    return `<header class="report-header"><span class="brand">LIRATING</span><button data-action="theme" class="quiet">切换主题</button></header><div class="eyebrow">CHARACTER VOTING JOURNAL</div><h1>${esc(s.project_name)}</h1><p class="muted">${esc(formatTime(s.finished_at || s.started_at))} · 评分范围 ${s.score_min}-${s.score_max}${metrics.partial ? ' · <span class="badge neutral">部分结果</span>' : ""}</p><nav class="report-view-nav" aria-label="报告导航">${navigation.map(([key,label]) => `<button data-page="${key}" class="${page === key ? "active" : ""}">${label}</button>`).join("")}</nav>`;
  }
  function characterBadge(character) {
    if (!imagesFor(character).some((row) => row.send_status === "sent")) return '<span class="badge warning">未成功展示</span>';
    if (!character.vote_count) return '<span class="badge neutral">已展示未获票</span>';
    return character.low_sample ? `<span class="badge warning">仅 ${character.vote_count} 票</span>` : "";
  }
  function characterCard(character) {
    const pictures = imagesFor(character), cover = pictures.find((row) => row.send_status === "sent") || pictures[0];
    return `<article class="surface"><div class="section-title"><div><div class="eyebrow">人物排名 ${character.rank ?? "—"}</div><h2>${esc(character.character)}</h2></div>${characterBadge(character)}</div>${cover ? `<button data-image="${esc(cover.candidate_id)}" class="art-card">${image(cover, true)}</button>` : ""}<div class="facts"><span><b>${score(character.average_score)}</b></span><span><b>${character.vote_count}</b> 票</span><span><b>${character.candidate_count}</b> 张图片</span><span><b>${pct(character.coverage)}</b> 覆盖</span></div></article>`;
  }
  function overview() {
    const ranked = [...characters].filter((item) => item.vote_count).sort((a,b) => (a.rank ?? 1e9) - (b.rank ?? 1e9));
    const featured = ranked.slice(0,3), counts = {};
    characters.forEach((item) => Object.entries(item.score_distribution || {}).forEach(([key,value]) => counts[key] = (counts[key] || 0) + Number(value)));
    return `<div class="facts"><span><b>${characters.length}</b> 个人物</span><span><b>${metrics.sent_count ?? 0} / ${rows.length}</b> 张已展示</span><span><b>${stats.unique_voters ?? 0}</b> 位参与者</span><span><b>${stats.total_valid_votes ?? 0}</b> 人物票</span></div>${featured.length ? `<section class="report-grid">${featured.map(characterCard).join("")}</section>` : '<div class="surface empty"><h2>本轮尚无有效评分</h2></div>'}<div class="insights"><section><h2>人物统计口径</h2><p>同一人物的多张图片组成一个投票批次。每位参与者对每个人物只保留一票；引用任意本场图片都会路由到该图片所属人物。</p>${d.ai_summary ? `<details class="method"><summary>AI 统计解读</summary><p style="white-space:pre-wrap">${esc(d.ai_summary)}</p></details>` : ""}</section><section><h2>总体分值分布</h2>${bars(counts)}</section></div>`;
  }
  function groupedImages() {
    const needle = query.toLowerCase();
    const filtered = characters.filter((character) => character.character.toLowerCase().includes(needle) || imagesFor(character).some((row) => row.display_title.toLowerCase().includes(needle)));
    return `<p class="page-summary">${characters.length} 个人物 · ${rows.length} 张图片 · ${stats.total_valid_votes ?? 0} 人物票</p><div class="toolbar"><input id="image-search" type="search" placeholder="搜索人物或图片" value="${esc(query)}"><span class="count">${filtered.length} / ${characters.length} 个人物</span></div>${filtered.map((character) => `<section class="surface character-group"><div class="section-title"><div><div class="eyebrow">人物排名 ${character.rank ?? "—"}</div><h2>${esc(character.character)}</h2></div><div><b>${score(character.average_score)}</b> · ${character.vote_count}票 · ${character.candidate_count}张图</div></div>${characterBadge(character)}<div class="report-grid">${imagesFor(character).map((row) => `<button data-image="${esc(row.candidate_id)}">${image(row)}<h3>${esc(row.display_title)}</h3><small>#${row.display_index}${row.send_status === "sent" ? " · 已展示" : row.send_status === "send_failed" ? " · 发送失败" : " · 未展示"}</small></button>`).join("")}</div><details class="method"><summary>人物评分分布与参与者</summary>${bars(character.score_distribution)}${d.participant_details_available ? `<div class="data-table">${votes.filter((vote) => vote.character === character.character).sort((a,b) => b.score-a.score).map((vote) => { const person = people.find((item) => item.id === vote.participant_id); return person ? `<div class="person-row">${avatar(person)}<button class="text-link" data-person="${esc(person.id)}">${esc(person.name)}</button><span class="right">${vote.score}分</span></div>` : ""; }).join("") || '<p class="muted">暂无评分</p>'}</div>` : ""}</details></section>`).join("") || '<div class="empty">没有匹配的人物或图片</div>'}`;
  }
  function peopleMenu() {
    return people.filter((person) => person.name.toLowerCase().includes(personQuery.toLowerCase())).map((person) => `<button data-person="${esc(person.id)}" class="${selectedPerson === person.id ? "active" : ""}">${avatar(person)}<span>${esc(person.name)}<small>${person.vote_count}个人物已评分</small></span></button>`).join("") || '<p class="muted">未找到参与者</p>';
  }
  function personDetail() {
    const person = people.find((item) => item.id === selectedPerson);
    if (!person) return '<div class="empty">暂无参与者明细</div>';
    const own = votes.filter((vote) => vote.participant_id === person.id).sort((a,b) => b.score-a.score);
    return `<div class="person-head">${avatar(person)}<div><h2>${esc(person.name)}</h2><span class="muted">本轮最终人物评分</span></div></div><div class="facts"><span><b>${person.vote_count}</b>个人物已评分</span><span><b>${avg(person.average_score)}</b>个人均分</span><span><b>${pct(person.coverage)}</b>评分覆盖</span></div><div class="report-grid">${own.map((vote) => { const character = byCharacter.get(vote.character); const cover = character && imagesFor(character)[0]; return `<article class="surface">${cover ? image(cover) : ""}<h3>${esc(vote.character)}</h3><b class="accent">${vote.score} / ${s.score_max}</b><small> · 本轮均分 ${avg(character?.average_score)}</small></article>`; }).join("")}</div>`;
  }
  function peoplePage() {
    return `<p class="page-summary">${people.length} 位参与者 · ${characters.length} 个人物 · 个人评分合计 ${votes.length} 票</p><div class="people-layout"><aside><input id="people-search" type="search" placeholder="搜索参与者" value="${esc(personQuery)}"><div class="people-menu">${peopleMenu()}</div></aside><section id="person-detail">${personDetail()}</section></div>`;
  }
  function footer() {
    return `<details class="method"><summary>统计口径与场次信息</summary><p>人物是唯一评分单位；同一参与者对同一人物只保留一票。图片仅作为人物素材，不单独排名。普通数字归属当前人物，引用本场图片归属该图片对应人物。</p><p>会话 ${esc(s.short_id)}${s.group_id ? " · 群 " + esc(s.group_id) : ""} · ${esc(s.status)}</p></details>`;
  }
  function render() {
    root.innerHTML = header() + `<div class="report-body">${page === "overview" ? overview() : page === "images" ? groupedImages() : peoplePage()}</div>` + footer();
  }
  const dialog = document.createElement("dialog"); dialog.className = "report-modal"; document.body.appendChild(dialog);
  root.addEventListener("click", (event) => {
    const pageButton = event.target.closest("[data-page]");
    if (pageButton) { page = pageButton.dataset.page; render(); return; }
    if (event.target.closest('[data-action="theme"]')) { document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; return; }
    const personButton = event.target.closest("[data-person]");
    if (personButton) { selectedPerson = personButton.dataset.person; page = "people"; render(); return; }
    const imageButton = event.target.closest("[data-image]");
    if (imageButton) { const row = byImage.get(imageButton.dataset.image); if (!row) return; dialog.innerHTML = `<div class="modal-head"><h2>${esc(row.display_title)}</h2><button data-close>关闭</button></div>${image(row, true)}<p>${esc(row.character)} · 原始文件 ${esc(row.source_filename)}</p>`; dialog.showModal(); }
  });
  root.addEventListener("input", (event) => {
    if (event.target.id === "image-search") { query = event.target.value; render(); }
    if (event.target.id === "people-search") { personQuery = event.target.value; render(); }
  });
  dialog.addEventListener("click", (event) => { if (event.target.closest("[data-close]")) dialog.close(); });
  render();
})();
