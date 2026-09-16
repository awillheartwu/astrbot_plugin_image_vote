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
  let page = "overview", query = "", selectedPerson = people[0]?.id, personQuery = "", personSort = "high", galleryView = "cards", gallerySort = "original", galleryFilter = "all";
  const expanded = new Set();
  const ordered = [...characters].sort((a,b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));
  const avg = (v) => v == null ? "暂无评分" : Number(v).toFixed(2);
  const score = (v) => v == null ? "暂无评分" : `${Number(v).toFixed(2)} / ${s.score_max}`;
  const pct = (v) => v == null ? "—" : (Number(v) * 100).toFixed(1) + "%";
  const formatTime = (v) => v && !Number.isNaN(Date.parse(v)) ? new Date(v).toLocaleString("zh-CN", {hour12:false}) : "—";
  const assetUrl = value => d.image_assets?.[value] || value || "";
  const image = (row, main = false) => `<img src="${esc(assetUrl(main ? row.main_image : row.thumbnail))}" alt="${esc(row.display_title)}" loading="lazy">`;
  const avatar = (person) => person.avatar ? `<img class="avatar" src="${esc(assetUrl(person.avatar))}" alt="">` : `<span class="placeholder" aria-hidden="true">${esc((person.name || "?").slice(0,1))}</span>`;
  // All charts use report data and inline SVG: no network or export dependencies.
  document.documentElement.dataset.theme ||= "dark";
  const coverFor = c => imagesFor(c).find(r => r.send_status === "sent") || imagesFor(c)[0];
  const totalCounts = characters.reduce((counts, c) => {
    Object.entries(c.score_distribution || {}).forEach(([key, value]) => counts[key] = (counts[key] || 0) + Number(value));
    return counts;
  }, {});
  const highMin = Number(s.score_max) > Number(s.score_min) ? Math.round((Number(s.score_min) + .8 * (Number(s.score_max)-Number(s.score_min))) * 100) / 100 : null;
  const isHigh = value => value != null && highMin != null && Number(value) >= highMin;
  const scoreClass = value => isHigh(value) ? "score-high" : "";
  const highLegend = () => highMin == null ? "" : `<p class="score-legend"><span aria-hidden="true"></span>金色：高分 ${highMin}–${s.score_max} 分（评分区间的上 20%）</p>`;
  function metric(value, label, tone = "violet") {
    return `<div class="metric-card tone-${tone}"><span class="metric-label">${label}</span><b>${value}</b><i aria-hidden="true"></i></div>`;
  }
  function histogram(counts, title = "评分分布", width = 340) {
    const min = Number(s.score_min), max = Number(s.score_max);
    const step = Math.max(1, Math.ceil((max-min+1)/11)), bins = [];
    for (let start=min; start<=max; start+=step) {
      const end=Math.min(max,start+step-1);
      let count=0;
      for(let n=start;n<=end;n++) count+=Number(counts[n] || 0);
      bins.push({label:start===end?`${start}`:`${start}–${end}`,count, high:isHigh(start)});
    }
    const peak=Math.max(3,Math.ceil(Math.max(0,...bins.map(b=>b.count))/3)*3);
    const plot={x:32,y:20,w:Math.max(220,width-48),h:150}, cell=plot.w/bins.length;
    const grids=Array.from({length:4},(_,i)=>{
      const y=plot.y+plot.h-i*plot.h/3;
      return `<line x1="32" y1="${y}" x2="${width-16}" y2="${y}" class="chart-grid"/><text x="24" y="${y+4}" text-anchor="end">${peak*i/3}</text>`;
    }).join("");
    return `<div class="chart histogram" data-counts="${esc(JSON.stringify(counts))}" data-title="${esc(title)}"><svg viewBox="0 0 ${width} 206" role="img" aria-label="${esc(title)}，横轴为分数，纵轴为票数"><title>${esc(title)}</title>${grids}${bins.map((b,i)=>{
      const h=b.count/peak*plot.h,x=plot.x+i*cell+cell*.2,y=plot.y+plot.h-h;
      return `<g tabindex="0" role="img" aria-label="${b.label}分：${b.count}票"><title>${b.label}分：${b.count}票</title><rect class="chart-bar ${b.high ? "chart-high" : ""}" x="${x}" y="${y}" width="${cell*.6}" height="${h}" rx="3"/><text class="chart-value" x="${x+cell*.3}" y="${y-5}" text-anchor="middle">${b.count || ""}</text><text x="${x+cell*.3}" y="190" text-anchor="middle">${b.label}</text></g>`;
    }).join("")}</svg>${highLegend()}<details class="chart-data"><summary>查看分布数据</summary><div>${bins.map(b=>`<span>${b.label}分 <b>${b.count}票</b></span>`).join("")}</div></details></div>`;
  }
  function ring(value, label, detail) {
    const available=value!=null && Number.isFinite(Number(value));
    const fraction=available?Math.min(1,Math.max(0,Number(value))):0;
    return `<div class="ring-layout"><div class="ring-chart"><svg viewBox="0 0 140 140" role="img" aria-label="${esc(label)}：${available?pct(fraction):"暂无数据"}"><circle class="ring-track" cx="70" cy="70" r="56"/><circle class="ring-fill" cx="70" cy="70" r="56" pathLength="100" stroke-dasharray="${fraction*100} 100" transform="rotate(-90 70 70)"/></svg><div><strong>${available?pct(fraction):"—"}</strong><span>${esc(label)}</span></div></div><p>${detail}</p></div>`;
  }
  function coveragePanel() {
    const sent=characters.filter(c=>imagesFor(c).some(r=>r.send_status==="sent"));
    const rated=sent.filter(c=>c.vote_count>0).length;
    return `<section class="surface coverage-panel"><div class="panel-heading"><span class="eyebrow">PARTICIPATION</span><h2>人物获票情况</h2></div>${ring(sent.length?rated/sent.length:null,"人物获票率",`<b>${rated}</b> 个人物已获票<br><b>${sent.length-rated}</b> 个人物已展示，暂无评分`)}<p class="panel-footnote">分母为已成功展示的人物数；不代表群成员参与率。</p></section>`;
  }
  function comparison(own) {
    if ((stats.unique_voters || 0)<2) return '<p class="notice">本轮只有一位参与者，个人评分与本轮均分一致，无需重复比较。</p>';
    return `<section class="surface comparison-panel"><div class="panel-heading"><span class="eyebrow">SCORE COMPARISON</span><h2>个人评分与本轮均分</h2></div><p class="chart-legend"><span>个人评分</span><span>本轮均分（含本人）</span></p><div class="comparison-list">${own.map(v=>{
      const mean=byCharacter.get(v.character)?.average_score;
      return `<div class="comparison-row"><span>${esc(v.character)}</span><div><i style="width:${Math.max(0,Math.min(100,v.score/(Number(s.score_max) || 1)*100))}%"></i><i class="comparison-mean" style="width:${mean==null?0:Math.max(0,Math.min(100,mean/(Number(s.score_max) || 1)*100))}%"></i></div><b>${v.score} / ${mean==null?"—":avg(mean)}</b></div>`;
    }).join("")}</div><p class="panel-footnote">仅比较该参与者已评分人物；条形长度从 0 起算，上限 ${s.score_max} 分。</p></section>`;
  }
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
    const leader = ordered.find(c => c.vote_count > 0 && coverFor(c));
    const cover = leader ? coverFor(leader) : rows.find(row => row.send_status === "sent") || rows[0];
    return `<header class="report-header"><span class="brand">LIRATING <small>人物投票报告</small></span><button data-action="theme" class="quiet">切换主题</button></header><section class="report-intro ${page === "overview" ? "with-cover" : "compact"}">${cover ? `<div class="report-intro-cover" aria-hidden="true">${image(cover,true)}</div>` : ""}<div class="intro-content"><div class="eyebrow">CHARACTER VOTING JOURNAL</div><h1>${esc(s.project_name)} <span class="badge">${esc(s.status_label || s.status || "")}</span></h1><p>按人物汇总评分，记录每一次选择。</p><div class="report-meta"><span># ${esc(s.short_id || "—")}</span><span>${stats.unique_voters ?? 0} 位参与者</span><span>${characters.length} 个人物</span><span>${s.score_min}–${s.score_max} 分制</span><span>${esc(formatTime(s.finished_at || s.started_at))}</span>${metrics.partial ? '<span class="badge neutral">图片未全部展示</span>' : ""}</div></div></section><nav class="report-view-nav" aria-label="报告导航">${navigation.map(([key,label]) => `<button data-page="${key}" ${page === key ? 'aria-current="page"' : ""} class="${page === key ? "active" : ""}">${label}${key === "images" ? ` <span>${rows.length}</span>` : ""}</button>`).join("")}</nav>`;
  }
  function characterBadge(character) {
    if (!imagesFor(character).some((row) => row.send_status === "sent")) return '<span class="badge warning">未成功展示</span>';
    if (!character.vote_count) return '<span class="badge neutral">已展示，暂无评分</span>';
    return character.low_sample ? `<span class="badge warning">仅 ${character.vote_count} 票</span>` : "";
  }
  function characterCard(c) {
    const cover=coverFor(c);
    return `<article class="character-card podium-card"><div class="podium-media">${cover?`<button class="character-cover" data-image="${esc(cover.candidate_id)}" aria-label="查看 ${esc(c.character)} 的封面">${image(cover,true)}</button>`:'<div class="image-error">无图片</div>'}<span class="rank-medal rank-${c.rank}" aria-label="排名 ${c.rank}">${c.rank}</span></div><div class="podium-caption"><button data-character="${esc(c.character)}" class="text-link">${esc(c.character)}</button><div><strong class="${scoreClass(c.average_score)}">${avg(c.average_score)}<small> / ${s.score_max}</small></strong><span>${c.vote_count} 票</span></div>${characterBadge(c)}</div></article>`;
  }
  function rankingTable() {
    return `<section id="full-ranking" class="surface"><div class="section-title"><div><span class="eyebrow">THE FULL RANKING</span><h2>完整人物排名</h2></div><span class="badge neutral">${characters.length} 个人物</span></div><div class="table-wrap"><table><caption class="sr-only">本轮全部人物最终排名</caption><thead><tr><th scope="col">排名</th><th scope="col">人物</th><th scope="col">均分</th><th scope="col">票数</th><th scope="col">获票覆盖</th></tr></thead><tbody>${ordered.map(c=>{
      const cover=coverFor(c),coverage=c.coverage==null?null:Math.max(0,Math.min(1,c.coverage));
      return `<tr><td><span class="table-rank rank-${c.rank}">${c.rank ?? "—"}</span></td><td><div class="rank-identity">${cover?image(cover):""}<div><button class="text-link ranking-name" data-character="${esc(c.character)}">${esc(c.character)}</button>${characterBadge(c)}</div></div></td><td class="num score-cell ${scoreClass(c.average_score)}">${avg(c.average_score)}</td><td>${c.vote_count}</td><td><div class="coverage-track"><i style="width:${(coverage || 0)*100}%"></i></div><small>${pct(coverage)}</small></td></tr>`;
    }).join("") || '<tr><td colspan="5">暂无人物</td></tr>'}</tbody></table></div><p class="panel-footnote">按均分、票数、人物首次出现顺序排列。获票覆盖 = 人物票数 / 本轮参与者人数；无评分不参与排名。</p></section>`;
  }
  function aiPanel() {
    const leader=ordered.find(c=>c.vote_count>0);
    const unrated=characters.filter(c=>!c.vote_count && imagesFor(c).some(r=>r.send_status==="sent")).length;
    const digest=[leader ? `${leader.character} 位列第一，均分 ${avg(leader.average_score)}，共 ${leader.vote_count} 票。` : "本轮暂无有效人物评分。", `共有 ${unrated} 个人物已展示但暂无评分。`];
    if ((stats.unique_voters || 0)===1) digest.push("本轮只有一位参与者，结果反映个人评分。");
    const analysis=d.ai_analysis;
    const structured=analysis && typeof analysis.headline==="string" && Array.isArray(analysis.insights) && analysis.insights.every(i=>typeof i.title==="string" && typeof i.text==="string");
    return `<section class="surface ai-panel"><div class="panel-heading"><span class="eyebrow">INSIGHTS & NOTES</span><h2>本轮速览</h2></div><ul class="report-digest">${digest.map(t=>`<li>${esc(t)}</li>`).join("")}</ul>${structured ? `<h3 class="ai-headline">${esc(analysis.headline)}</h3><details class="ai-expanded"><summary>展开 AI 数据观察 · ${analysis.insights.length} 条</summary>${analysis.insights.map(i=>`<article><h3>${esc(i.title)}</h3><p>${esc(i.text)}</p></article>`).join("")}${analysis.closing?`<p class="muted">${esc(analysis.closing)}</p>`:""}</details>` : d.ai_summary ? `<details class="ai-expanded"><summary>展开 AI 完整解读</summary><p class="ai-copy">${esc(d.ai_summary)}</p></details>` : '<p class="muted">本报告未附带 AI 解读。</p>'}${d.ai_summary?'<small>AI 仅依据统计生成，仅供参考。</small>':""}<div class="insight-signature">LIRATING <span>每一次选择，都有迹可循。</span></div></section>`;
  }
  function overview() {
    const featured = ordered.filter(c=>c.vote_count).slice(0,3);
    const count=Object.values(totalCounts).reduce((sum,n)=>sum+n,0);
    const mean=count?Object.entries(totalCounts).reduce((sum,[n,c])=>sum+Number(n)*c,0)/count:null;
    return `<div class="report-metrics">${metric(characters.length,"人物数量")}${metric(stats.unique_voters ?? 0,"参与者","blue")}${metric(stats.total_valid_votes ?? 0,"有效人物票","green")}${metric(avg(mean),`平均分 / ${s.score_max}`)}${metric(`${metrics.sent_count ?? 0} / ${rows.length}`,"图片已展示","blue")}</div>${stats.unique_voters === 1 ? '<p class="notice">本轮仅 1 位参与者，排名反映个人评分，不代表群体共识。</p>' : ""}<div class="overview-top"><section class="surface podium-panel"><div class="section-title"><div><span class="eyebrow">HIGHEST RATED</span><h2>高分人物 <small>TOP ${featured.length}</small></h2></div><a class="text-link" href="#full-ranking">完整排名 →</a></div>${featured.length?`<div class="character-ranking">${featured.map(characterCard).join("")}</div>`:'<div class="empty">本轮尚无有效评分，图片可在「全部图片」中浏览。</div>'}</section><section class="surface distribution-panel"><div class="panel-heading"><span class="eyebrow">SCORE DISTRIBUTION</span><h2>总体分值分布</h2></div>${histogram(totalCounts)}<p class="panel-footnote">每张最终人物票计入一次 · 共 ${count} 票</p></section>${coveragePanel()}</div><div class="overview-bottom">${aiPanel()}${rankingTable()}</div>`;
  }
  function imageTile(row) {
    return `<button data-image="${esc(row.candidate_id)}">${image(row)}<h3>${esc(row.display_title)}</h3><small>#${row.display_index} · ${row.send_status === "sent" ? "已展示" : row.send_status === "send_failed" ? "发送失败" : "未展示"}</small></button>`;
  }
  function galleryList(filtered) {
    return `<div class="table-wrap gallery-list"><table><caption class="sr-only">人物列表，点击查看人物图片及评分详情</caption><thead><tr><th scope="col">人物</th><th scope="col">排名</th><th scope="col">均分</th><th scope="col">票数</th><th scope="col">图片</th><th scope="col">详情</th></tr></thead><tbody>${filtered.map(c=>`<tr><td><div class="rank-identity">${coverFor(c)?image(coverFor(c)):""}<div><button class="text-link ranking-name" data-detail="${esc(c.character)}">${esc(c.character)}</button>${characterBadge(c)}</div></div></td><td>${c.rank ?? "—"}</td><td class="num ${scoreClass(c.average_score)}">${avg(c.average_score)}</td><td>${c.vote_count}</td><td>${imagesFor(c).length}</td><td><button class="text-link" data-detail="${esc(c.character)}" aria-label="查看 ${esc(c.character)} 详情">查看详情 →</button></td></tr>`).join("")}</tbody></table></div>`;
  }
  function groupedImages() {
    const needle = query.toLowerCase();
    const filtered = characters.filter(c => (c.character.toLowerCase().includes(needle) || imagesFor(c).some(r => r.display_title.toLowerCase().includes(needle))) && (galleryFilter === "all" || (galleryFilter === "high" ? isHigh(c.average_score) : !c.vote_count)));
    if (gallerySort === "score") filtered.sort((a,b)=>(a.rank ?? Infinity)-(b.rank ?? Infinity));
    if (gallerySort === "name") filtered.sort((a,b)=>a.character.localeCompare(b.character,"zh-CN"));
    const cards=()=>`<div class="character-library">${filtered.map(c => {
      const all=imagesFor(c), open=expanded.has(c.character);
      const pictures=needle && !c.character.toLowerCase().includes(needle)?all.filter(r=>r.display_title.toLowerCase().includes(needle)):all;
      return `<section class="surface character-group"><div class="section-title"><div class="group-identity">${coverFor(c)?image(coverFor(c)):""}<div><h2><button class="text-link" data-detail="${esc(c.character)}">${esc(c.character)}</button></h2><span class="muted">#${c.rank ?? "—"} · <b class="${scoreClass(c.average_score)}">${score(c.average_score)}</b> · ${c.vote_count} 票 · ${all.length} 张图</span></div></div>${characterBadge(c)}</div><div class="report-grid">${(open?pictures:pictures.slice(0,3)).map(imageTile).join("")}</div><div class="group-actions">${pictures.length>3?`<button class="group-expand" data-expand="${esc(c.character)}" aria-expanded="${open}">${open?"收起图片":`全部 ${pictures.length} 张`}</button>`:""}<button class="text-link" data-detail="${esc(c.character)}">人物详情 →</button></div></section>`;
    }).join("")}</div>`;
    return `<div class="library-summary"><span><b>${rows.length}</b> 张图片</span><span><b>${characters.length}</b> 个人物</span><p>图片是人物素材，不单独评分或排名。</p></div><div class="toolbar gallery-toolbar"><label class="sr-only" for="image-search">搜索人物或图片</label><input id="image-search" type="search" placeholder="搜索人物或图片" value="${esc(query)}"><label class="toolbar-field"><span>筛选</span><select id="gallery-filter">${[["all","全部人物"],["high","高分人物"],["unrated","暂无评分"]].map(([v,t])=>`<option value="${v}" ${galleryFilter===v?"selected":""}>${t}</option>`).join("")}</select></label><label class="toolbar-field"><span>排序</span><select id="gallery-sort">${[["original","展示顺序"],["score","评分排名"],["name","人物名称"]].map(([v,t])=>`<option value="${v}" ${gallerySort===v?"selected":""}>${t}</option>`).join("")}</select></label><div class="view-controls" role="group" aria-label="浏览方式"><button data-view="cards" aria-pressed="${galleryView==="cards"}">图册</button><button data-view="list" aria-pressed="${galleryView==="list"}">列表</button></div><span class="count" role="status">${filtered.length} / ${characters.length} 个人物</span></div>${highLegend()}${filtered.length ? galleryView==="list"?galleryList(filtered):cards() : '<div class="empty">没有匹配的人物或图片</div>'}`;
  }
  function peopleMenu() {
    return people.filter((person) => person.name.toLowerCase().includes(personQuery.toLowerCase())).map((person) => `<button data-person="${esc(person.id)}" class="${selectedPerson === person.id ? "active" : ""}" title="${esc(person.name)}">${avatar(person)}<span><b class="person-name">${esc(person.name)}</b><small>已给 ${person.vote_count} 位人物评分</small></span></button>`).join("") || '<p class="muted">未找到参与者</p>';
  }
  function personDetail() {
    const person = people.find((item) => item.id === selectedPerson);
    if (!person) return '<div class="empty">暂无参与者明细</div>';
    const own = votes.filter(v => v.participant_id === person.id).sort((a,b) => personSort === "name" ? a.character.localeCompare(b.character, "zh-CN") : personSort === "low" ? a.score-b.score : b.score-a.score);
    const ownCounts=own.reduce((counts,v)=>{ counts[v.score]=(counts[v.score] || 0)+1; return counts; },{});
    return `<div class="person-heading">${avatar(person)}<div><h2>${esc(person.name)}</h2><span class="muted">本轮最终人物评分</span></div></div><div class="report-metrics person-metrics">${metric(person.vote_count,"已评分人物","blue")}${metric(avg(person.average_score),"该参与者均分")}${metric(pct(person.coverage),"人物覆盖率","green")}</div><div class="person-charts"><section class="surface"><div class="panel-heading"><span class="eyebrow">PERSONAL SCORES</span><h2>个人评分分布</h2></div>${histogram(ownCounts,"个人评分分布")}</section><section class="surface"><div class="panel-heading"><span class="eyebrow">COVERAGE</span><h2>人物评分覆盖</h2></div>${ring(person.coverage,"人物覆盖率",`已给 <b>${person.vote_count}</b> 个人物评分<br>每个人物只计一张最终票`)}</section></div>${comparison(own)}<p class="report-note">覆盖率以至少成功展示一张图片的人物为分母。本轮均分包含该参与者的评分。</p><div class="toolbar"><label for="person-sort">评分排序</label><select id="person-sort">${[["high","评分从高到低"],["low","评分从低到高"],["name","人物名称"]].map(([value,label]) => `<option value="${value}" ${personSort === value ? "selected" : ""}>${label}</option>`).join("")}</select></div><div class="table-wrap"><table><caption class="sr-only">${esc(person.name)}的最终人物评分</caption><thead><tr><th scope="col">人物</th><th scope="col">个人评分</th><th scope="col">本轮均分</th><th scope="col">来源图片</th></tr></thead><tbody>${own.map(v => { const c = byCharacter.get(v.character), source = byImage.get(v.source_candidate_id); return `<tr><td><button class="text-link ranking-name" data-character="${esc(v.character)}">${esc(v.character)}</button></td><td class="num accent ${scoreClass(v.score)}">${v.score}</td><td class="num ${scoreClass(c?.average_score)}">${avg(c?.average_score)}</td><td>${source ? `<button class="source-image" data-image="${esc(source.candidate_id)}">${image(source)}<span>${esc(source.display_title)}</span></button>` : '<span class="muted">来源图片不可用</span>'}</td></tr>`; }).join("") || '<tr><td colspan="4">暂无评分</td></tr>'}</tbody></table></div>`;
  }

  function peoplePage() {
    return `<p class="page-summary">${people.length} 位参与者 · ${characters.length} 个人物 · 个人评分合计 ${votes.length} 票</p><div class="people-layout"><aside><label class="sr-only" for="people-search">搜索参与者</label><input id="people-search" type="search" placeholder="搜索参与者" value="${esc(personQuery)}"><div class="people-menu">${peopleMenu()}</div></aside><section id="person-detail">${personDetail()}</section></div>`;
  }
  function footer() {
    return `<details class="method"><summary>统计口径与场次信息</summary><p>人物是唯一评分单位；同一参与者对同一人物只保留一票。图片仅作为人物素材，不单独排名。普通数字归属当前人物，引用本场图片归属该图片对应人物。</p><p>会话 ${esc(s.short_id)}${s.group_id ? " · 群 " + esc(s.group_id) : ""} · ${esc(s.status_label || s.status)}</p></details>`;
  }
  const chartObserver = new ResizeObserver(entries => {
    for (const {target,contentRect} of entries) {
      const width=Math.round(contentRect.width);
      if(width<268 || target.dataset.width===String(width)) continue;
      target.dataset.width=String(width);
      const template=document.createElement("template");
      template.innerHTML=histogram(JSON.parse(target.dataset.counts),target.dataset.title,width);
      target.querySelector("svg").replaceWith(template.content.querySelector("svg"));
    }
  });
  function observeCharts() {
    chartObserver.disconnect();
    document.querySelectorAll(".histogram").forEach(el=>chartObserver.observe(el));
  }
  function render() {
    const focused = document.activeElement;
    const id = focused?.id, start = focused?.selectionStart, end = focused?.selectionEnd;
    const key = focused?.dataset?.expand;
    root.innerHTML = header() + `<div class="report-body">${page === "overview" ? overview() : page === "images" ? groupedImages() : peoplePage()}</div>` + footer();
    observeCharts();
    const replacement = id ? document.getElementById(id) : key ? [...root.querySelectorAll("[data-expand]")].find(el => el.dataset.expand === key) : null;
    if (replacement) { replacement.focus({preventScroll:true}); if (start != null && replacement.setSelectionRange) replacement.setSelectionRange(start,end); }
  }
  const dialog = document.createElement("dialog"); dialog.className = "report-modal"; document.body.appendChild(dialog);
  function showDialog(content) {
    dialog.innerHTML=content;
    observeCharts();
    if (!dialog.open) dialog.showModal();
    else dialog.querySelector("[data-close]")?.focus({preventScroll:true});
  }
  function groupedVoters(name) {
    const groups=new Map();
    votes.filter(v=>v.character===name).forEach(v=>{
      const person=people.find(p=>p.id===v.participant_id);
      if(!person) return;
      if(!groups.has(v.score)) groups.set(v.score,[]);
      groups.get(v.score).push(person);
    });
    return `<section class="voter-groups"><h3>最终参与者评分</h3>${[...groups].sort(([a],[b])=>b-a).map(([value,persons])=>`<div class="voter-score-group"><div class="voter-score ${scoreClass(value)}"><b>${value}<small> 分</small></b><span>${persons.length} 人</span></div><div class="voter-avatar-list">${persons.map(person=>`<button class="voter-avatar" data-person="${esc(person.id)}" title="${esc(person.name)} · ${value} 分" aria-label="查看 ${esc(person.name)}，评分 ${value} 分">${avatar(person)}<span class="voter-tooltip" role="tooltip">${esc(person.name)}</span></button>`).join("")}</div></div>`).join("") || '<p class="muted">暂无评分</p>'}<p class="panel-footnote">悬停或聚焦头像查看昵称，点击查看参与者详情。</p></section>`;
  }
  function openCharacter(name) {
    const c=byCharacter.get(name); if(!c) return;
    showDialog(`<div class="modal-head"><h2>${esc(name)}</h2><button data-close>关闭</button></div><p><strong class="${scoreClass(c.average_score)}">${score(c.average_score)}</strong> · ${c.vote_count} 票 · ${imagesFor(c).length} 张图片 ${characterBadge(c)}</p><div class="report-grid detail-gallery">${imagesFor(c).map(imageTile).join("")}</div><div class="character-detail-stats"><section class="surface distribution-panel"><div class="panel-heading"><span class="eyebrow">SCORE DISTRIBUTION</span><h3>人物评分分布</h3></div>${histogram(c.score_distribution || {})}</section>${d.participant_details_available?groupedVoters(name):""}</div>`);
  }
  function openImage(id) {
    const row=byImage.get(id); if(!row) return;
    const c=byCharacter.get(row.character), pictures=c?imagesFor(c):[row], index=pictures.indexOf(row);
    showDialog(`<div class="modal-head"><h2>${esc(row.display_title)}</h2><button data-close>关闭</button></div>${image(row,true)}<div class="image-detail-nav"><button data-image="${esc(pictures[Math.max(0,index-1)].candidate_id)}" ${index<=0?"disabled":""}>上一张</button><span>${index+1} / ${pictures.length}</span><button data-image="${esc(pictures[Math.min(pictures.length-1,index+1)].candidate_id)}" ${index>=pictures.length-1?"disabled":""}>下一张</button></div><p>${esc(row.character)} · 原始文件 ${esc(row.source_filename)}</p>${row.image_quality === "thumbnail" ? '<p class="report-note">此图为节省体积的缩略图；该人物的封面保留高清版本。</p>' : ""}<p class="muted">${row.send_status==="sent"?"已展示":row.send_status==="send_failed"?"发送失败":"未展示"}${c?` · 人物均分 ${score(c.average_score)}`:""}</p>${c?`<button class="text-link" data-detail="${esc(c.character)}">查看人物详情与评分</button>`:""}`);
  }
  function handleClick(event) {
    const detailButton=event.target.closest("[data-detail]");
    if(detailButton){openCharacter(detailButton.dataset.detail);return;}
    const viewButton=event.target.closest("[data-view]");
    if(viewButton){galleryView=viewButton.dataset.view;render();root.querySelector(`[data-view="${galleryView}"]`).focus({preventScroll:true});return;}
    if(event.target.closest("[data-close]")){dialog.close();return;}
    const pageButton = event.target.closest("[data-page]");
    if (pageButton) { page = pageButton.dataset.page; render(); root.querySelector(`[data-page="${page}"]`).focus({preventScroll:true}); return; }
    const characterButton = event.target.closest("[data-character]");
    if (characterButton) { query = characterButton.dataset.character; galleryFilter = "all"; expanded.add(query); page = "images"; render(); document.getElementById("image-search").focus(); return; }
    const expandButton = event.target.closest("[data-expand]");
    if (expandButton) { const key = expandButton.dataset.expand; expanded.has(key) ? expanded.delete(key) : expanded.add(key); render(); return; }
    if (event.target.closest('[data-action="theme"]')) { document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; return; }
    const personButton = event.target.closest("[data-person]");
    if (personButton) { selectedPerson = personButton.dataset.person; if(dialog.open) dialog.close(); page = "people"; render(); root.querySelector(".people-menu .active")?.focus({preventScroll:true}); return; }
    const imageButton = event.target.closest("[data-image]");
    if (imageButton) openImage(imageButton.dataset.image);
  }
  root.addEventListener("click", handleClick);
  dialog.addEventListener("click", handleClick);
  root.addEventListener("input", (event) => {
    if (event.target.id === "image-search") { query = event.target.value; render(); }
    if (event.target.id === "people-search") { personQuery = event.target.value; render(); }
  });
  root.addEventListener("change", (event) => {
    const id=event.target.id;
    if(id==="person-sort") personSort=event.target.value;
    else if(id==="gallery-sort") gallerySort=event.target.value;
    else if(id==="gallery-filter") galleryFilter=event.target.value;
    else return;
    render();
  });
  document.addEventListener("error", (event) => {
    if (event.target.tagName === "IMG" && (root.contains(event.target) || dialog.contains(event.target))) {
      const fallback = document.createElement("span"); const isAvatar = event.target.classList.contains("avatar"); fallback.className = isAvatar ? "placeholder" : "image-error"; fallback.textContent = isAvatar ? "?" : "图片不可用"; event.target.replaceWith(fallback);
    }
  }, true);
  render();
})();
