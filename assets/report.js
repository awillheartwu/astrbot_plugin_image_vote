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
  let page = "overview", query = "", selectedPerson = people[0]?.id, personQuery = "", personSort = "high";
  const expanded = new Set();
  const ordered = [...characters].sort((a,b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));
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
    const navigation = [["overview","概览"],["images","全部图片"],...(d.participant_details_available ? [["people","按参与者查看"]] : [])];
    const cover = rows.find((row) => row.send_status === "sent");
    return `<header class="report-header"><span class="brand">LIRATING</span><button data-action="theme" class="quiet">切换主题</button></header><section class="report-intro ${page === "overview" ? "with-cover" : ""}"><div><div class="eyebrow">人物投票报告</div><h1>${esc(s.project_name)}</h1>${page === "overview" ? '<p>按人物汇总评分，保留每位参与者的最终选择。</p>' : ""}<div class="report-meta"><span>${esc(s.status_label || s.status || "")}</span><span>评分范围 ${s.score_min}–${s.score_max}</span><span>${esc(formatTime(s.finished_at || s.started_at))}</span>${metrics.partial ? '<span class="badge neutral">图片未全部展示</span>' : ""}</div></div>${page === "overview" && cover ? `<div class="report-intro-cover" aria-hidden="true">${image(cover)}</div>` : ""}</section><nav class="report-view-nav" aria-label="报告导航">${navigation.map(([key,label]) => `<button data-page="${key}" ${page === key ? 'aria-current="page"' : ""} class="${page === key ? "active" : ""}">${label}${key === "images" ? ` (${rows.length})` : ""}</button>`).join("")}</nav>`;
  }
  function characterBadge(character) {
    if (!imagesFor(character).some((row) => row.send_status === "sent")) return '<span class="badge warning">未成功展示</span>';
    if (!character.vote_count) return '<span class="badge neutral">已展示，暂无评分</span>';
    return character.low_sample ? `<span class="badge warning">仅 ${character.vote_count} 票</span>` : "";
  }
  function characterCard(character) {
    const pictures = imagesFor(character), cover = pictures.find((row) => row.send_status === "sent") || pictures[0];
    return `<article class="surface character-card"><div class="section-title"><div><div class="eyebrow">人物排名 ${character.rank ?? "—"}</div><h2>${esc(character.character)}</h2></div>${characterBadge(character)}</div>${cover ? `<button data-image="${esc(cover.candidate_id)}" class="character-cover">${image(cover, true)}</button>` : ""}<div class="facts"><span><b>${score(character.average_score)}</b></span><span><b>${character.vote_count}</b> 票</span><span><b>${character.candidate_count}</b> 张图片</span><span><b>${pct(character.coverage)}</b> 覆盖</span></div></article>`;
  }
  function overview() {
    const featured = ordered.filter((item) => item.vote_count).slice(0,3), counts = {};
    characters.forEach((item) => Object.entries(item.score_distribution || {}).forEach(([key,value]) => counts[key] = (counts[key] || 0) + Number(value)));
    return `<div class="report-metrics"><div><b>${characters.length}</b><span>人物</span></div><div><b>${stats.unique_voters ?? 0}</b><span>参与者</span></div><div><b>${stats.total_valid_votes ?? 0}</b><span>有效人物票</span></div><div><b>${metrics.sent_count ?? 0} / ${rows.length}</b><span>图片已展示</span></div></div>${stats.unique_voters === 1 ? '<p class="notice">本轮仅 1 位参与者，排名反映个人评分，不代表群体共识。</p>' : ""}<section class="report-section"><div class="section-title"><h2>高分人物</h2><a class="text-link" href="#full-ranking">查看完整排名 ↓</a></div>${featured.length ? `<div class="report-grid character-ranking">${featured.map(characterCard).join("")}</div>` : '<div class="surface empty">本轮尚无有效评分，图片仍可在「全部图片」中浏览。</div>'}</section><div class="report-analysis"><section id="full-ranking" class="surface"><div class="section-title"><h2>完整人物排名</h2><span class="muted">${characters.length} 个人物</span></div><p class="report-note">按均分降序；同分时按票数、人物首次出现顺序排列。暂无评分的人物不参与排名。</p><div class="table-wrap"><table><caption class="sr-only">本轮全部人物最终排名</caption><thead><tr><th scope="col">排名</th><th scope="col">人物</th><th scope="col">均分</th><th scope="col">票数</th></tr></thead><tbody>${ordered.map(c => `<tr><td>${c.rank ?? "—"}</td><td><button class="text-link ranking-name" data-character="${esc(c.character)}">${esc(c.character)}</button>${characterBadge(c)}</td><td class="num">${avg(c.average_score)}</td><td>${c.vote_count}</td></tr>`).join("") || '<tr><td colspan="4">暂无人物</td></tr>'}</tbody></table></div></section><div class="report-analysis-side"><section class="surface"><h2>总体分值分布</h2><p class="report-note">每张最终人物票计入一次。</p>${bars(counts)}</section>${d.ai_summary ? `<section class="surface"><h2>AI 统计解读</h2><p class="ai-copy">${esc(d.ai_summary)}</p><small>根据本轮统计自动生成，仅供参考。</small></section>` : ""}</div></div>`;
  }
  function imageTile(row) {
    return `<button data-image="${esc(row.candidate_id)}">${image(row)}<h3>${esc(row.display_title)}</h3><small>#${row.display_index} · ${row.send_status === "sent" ? "已展示" : row.send_status === "send_failed" ? "发送失败" : "未展示"}</small></button>`;
  }
  function groupedImages() {
    const needle = query.toLowerCase();
    const filtered = characters.filter((c) => c.character.toLowerCase().includes(needle) || imagesFor(c).some((r) => r.display_title.toLowerCase().includes(needle)));
    return `<p class="page-summary">图片仅作为人物素材，不单独评分或排名。</p><div class="toolbar"><label class="sr-only" for="image-search">搜索人物或图片</label><input id="image-search" type="search" placeholder="搜索人物或图片" value="${esc(query)}"><span class="count" role="status">${filtered.length} / ${characters.length} 个人物</span></div><div class="character-library">${filtered.map(c => {
      const all = imagesFor(c), open = expanded.has(c.character);
      // A filename search must expose matching images even beyond the preview slice.
      const pictures = needle && !c.character.toLowerCase().includes(needle) ? all.filter(r => r.display_title.toLowerCase().includes(needle)) : all;
      const visible = open ? pictures : pictures.slice(0,3);
      return `<section class="surface character-group"><div class="section-title"><div><h2>${esc(c.character)}</h2><span class="muted">${score(c.average_score)} · ${c.vote_count} 票 · ${all.length} 张图片</span></div>${characterBadge(c)}</div><div class="report-grid">${visible.map(imageTile).join("")}</div>${pictures.length > 3 ? `<button class="group-expand" data-expand="${esc(c.character)}" aria-expanded="${open}">${open ? "收起图片" : `查看全部 ${pictures.length} 张图片`}</button>` : ""}<details class="method"><summary>人物评分分布${d.participant_details_available ? "与参与者" : ""}</summary>${bars(c.score_distribution)}${d.participant_details_available ? `<div class="data-table">${votes.filter(v => v.character === c.character).sort((a,b) => b.score-a.score).map(v => { const person = people.find(p => p.id === v.participant_id); return person ? `<div class="person-row">${avatar(person)}<button class="text-link" data-person="${esc(person.id)}">${esc(person.name)}</button><span class="right">${v.score}分</span></div>` : ""; }).join("") || '<p class="muted">暂无评分</p>'}</div>` : ""}</details></section>`;
    }).join("") || '<div class="empty">没有匹配的人物或图片</div>'}</div>`;
  }
  function peopleMenu() {
    return people.filter((person) => person.name.toLowerCase().includes(personQuery.toLowerCase())).map((person) => `<button data-person="${esc(person.id)}" class="${selectedPerson === person.id ? "active" : ""}">${avatar(person)}<span>${esc(person.name)}<small>已给 ${person.vote_count} 位人物评分</small></span></button>`).join("") || '<p class="muted">未找到参与者</p>';
  }
  function personDetail() {
    const person = people.find((item) => item.id === selectedPerson);
    if (!person) return '<div class="empty">暂无参与者明细</div>';
    const own = votes.filter(v => v.participant_id === person.id).sort((a,b) => personSort === "name" ? a.character.localeCompare(b.character, "zh-CN") : personSort === "low" ? a.score-b.score : b.score-a.score);
    return `<div class="person-heading">${avatar(person)}<div><h2>${esc(person.name)}</h2><span class="muted">本轮最终人物评分</span></div></div><div class="report-metrics person-metrics"><div><b>${person.vote_count}</b><span>已评分人物</span></div><div><b>${avg(person.average_score)}</b><span>该参与者均分</span></div><div><b>${pct(person.coverage)}</b><span>人物覆盖率</span></div></div><p class="report-note">覆盖率以至少成功展示一张图片的人物为分母。本轮均分包含该参与者的评分。</p><div class="toolbar"><label for="person-sort">评分排序</label><select id="person-sort">${[["high","评分从高到低"],["low","评分从低到高"],["name","人物名称"]].map(([value,label]) => `<option value="${value}" ${personSort === value ? "selected" : ""}>${label}</option>`).join("")}</select></div><div class="table-wrap"><table><caption class="sr-only">${esc(person.name)}的最终人物评分</caption><thead><tr><th scope="col">人物</th><th scope="col">个人评分</th><th scope="col">本轮均分</th><th scope="col">来源图片</th></tr></thead><tbody>${own.map(v => { const c = byCharacter.get(v.character), source = byImage.get(v.source_candidate_id); return `<tr><td><button class="text-link ranking-name" data-character="${esc(v.character)}">${esc(v.character)}</button></td><td class="num accent">${v.score}</td><td class="num">${avg(c?.average_score)}</td><td>${source ? `<button class="source-image" data-image="${esc(source.candidate_id)}">${image(source)}<span>${esc(source.display_title)}</span></button>` : '<span class="muted">来源图片不可用</span>'}</td></tr>`; }).join("") || '<tr><td colspan="4">暂无评分</td></tr>'}</tbody></table></div>`;
  }

  function peoplePage() {
    return `<p class="page-summary">${people.length} 位参与者 · ${characters.length} 个人物 · 个人评分合计 ${votes.length} 票</p><div class="people-layout"><aside><label class="sr-only" for="people-search">搜索参与者</label><input id="people-search" type="search" placeholder="搜索参与者" value="${esc(personQuery)}"><div class="people-menu">${peopleMenu()}</div></aside><section id="person-detail">${personDetail()}</section></div>`;
  }
  function footer() {
    return `<details class="method"><summary>统计口径与场次信息</summary><p>人物是唯一评分单位；同一参与者对同一人物只保留一票。图片仅作为人物素材，不单独排名。普通数字归属当前人物，引用本场图片归属该图片对应人物。</p><p>会话 ${esc(s.short_id)}${s.group_id ? " · 群 " + esc(s.group_id) : ""} · ${esc(s.status_label || s.status)}</p></details>`;
  }
  function render() {
    const focused = document.activeElement;
    const id = focused?.id, start = focused?.selectionStart, end = focused?.selectionEnd;
    const key = focused?.dataset?.expand;
    root.innerHTML = header() + `<div class="report-body">${page === "overview" ? overview() : page === "images" ? groupedImages() : peoplePage()}</div>` + footer();
    const replacement = id ? document.getElementById(id) : key ? [...root.querySelectorAll("[data-expand]")].find(el => el.dataset.expand === key) : null;
    if (replacement) { replacement.focus({preventScroll:true}); if (start != null && replacement.setSelectionRange) replacement.setSelectionRange(start,end); }
  }
  const dialog = document.createElement("dialog"); dialog.className = "report-modal"; document.body.appendChild(dialog);
  root.addEventListener("click", (event) => {
    const pageButton = event.target.closest("[data-page]");
    if (pageButton) { page = pageButton.dataset.page; render(); root.querySelector(`[data-page="${page}"]`).focus({preventScroll:true}); return; }
    const characterButton = event.target.closest("[data-character]");
    if (characterButton) { query = characterButton.dataset.character; expanded.add(query); page = "images"; render(); document.getElementById("image-search").focus(); return; }
    const expandButton = event.target.closest("[data-expand]");
    if (expandButton) { const key = expandButton.dataset.expand; expanded.has(key) ? expanded.delete(key) : expanded.add(key); render(); return; }
    if (event.target.closest('[data-action="theme"]')) { document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; return; }
    const personButton = event.target.closest("[data-person]");
    if (personButton) { selectedPerson = personButton.dataset.person; page = "people"; render(); root.querySelector(".people-menu .active")?.focus({preventScroll:true}); return; }
    const imageButton = event.target.closest("[data-image]");
    if (imageButton) { const row = byImage.get(imageButton.dataset.image); if (!row) return; dialog.innerHTML = `<div class="modal-head"><h2>${esc(row.display_title)}</h2><button data-close>关闭</button></div>${image(row, true)}<p>${esc(row.character)} · 原始文件 ${esc(row.source_filename)}</p>`; dialog.showModal(); }
  });
  root.addEventListener("input", (event) => {
    if (event.target.id === "image-search") { query = event.target.value; render(); }
    if (event.target.id === "people-search") { personQuery = event.target.value; render(); }
  });
  root.addEventListener("change", (event) => { if (event.target.id === "person-sort") { personSort = event.target.value; render(); } });
  document.addEventListener("error", (event) => {
    if (event.target.tagName === "IMG" && (root.contains(event.target) || dialog.contains(event.target))) {
      const fallback = document.createElement("span"); fallback.className = "image-error"; fallback.textContent = "图片不可用"; event.target.replaceWith(fallback);
    }
  }, true);
  dialog.addEventListener("click", (event) => { if (event.target.closest("[data-close]")) dialog.close(); });
  render();
})();
