/* DOM/interaction regression checks, no screenshots. Requires Playwright + Chrome.
   Run: NODE_PATH=<playwright package root> node tools/check_report_ui.cjs */
const { chromium } = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const svg = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="gray"/></svg>');
const names = ['Alice', 'Zero', '<img src=x onerror=alert(1)>'];
const candidates = Array.from({length: 7}, (_, i) => ({candidate_id: `c${i}`, character: names[i < 5 ? 0 : i - 4], display_title: `Picture ${i}`, source_filename: `${i}.png`, display_index: i+1, send_status:'sent', thumbnail:svg, main_image:svg}));
const data = {
  session:{project_name:'Test <report>', score_min:0, score_max:10, short_id:'TEST', status_label:'已完成'},
  candidates,
  characters:names.map((character,i)=>({character, candidate_ids:candidates.filter(c=>c.character===character).map(c=>c.candidate_id), average_score:i===0?8:i===1?0:null, vote_count:i<2?1:0, rank:i<2?i+1:null, candidate_count:i===0?5:1, score_distribution:i===0?{8:1}:i===1?{0:1}:{}, coverage:1, low_sample:i<2})),
  statistics:{unique_voters:1,total_valid_votes:2},metrics:{sent_count:7},
  participant_details_available:true,participants:[{id:'p1',name:'Reader',vote_count:2,average_score:4,coverage:2/3}],
  votes:[{participant_id:'p1',character:'Alice',score:8,source_candidate_id:'c4'},{participant_id:'p1',character:'Zero',score:0,source_candidate_id:'missing'}]
};
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try {
  const page=await browser.newPage(); const errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function mount(payload){
   await page.setContent('<div id="report-app"></div><script id="report-data" type="application/json"></script>');
   await page.locator('#report-data').evaluate((el,d)=>el.textContent=JSON.stringify(d),payload);
   await page.addStyleTag({path:path.join(root,'assets/report.css')});
   await page.addScriptTag({path:path.join(root,'assets/report.js')});
  }
  await mount(data);
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  assert.equal(await page.locator('.histogram g').count(),11);
  assert.equal(await page.locator('.histogram g').first().getAttribute('aria-label'),'0分：1票');
  assert.equal(await page.locator('.coverage-panel .ring-chart strong').innerText(),'66.7%');
  assert.equal(await page.locator('#full-ranking tbody tr').count(),3);
  assert.match(await page.locator('.notice').innerText(),/个人评分/);
  assert.equal(await page.locator('.ranking-name').last().innerText(),names[2]);
  await page.locator('[data-page="images"]').click();
  assert.equal(await page.locator('.character-group').first().locator('[data-image]').count(),3);
  await page.locator('[data-expand]').click();
  assert.equal(await page.locator('.character-group').first().locator('[data-image]').count(),5);
  assert.equal(await page.locator('[data-expand]').getAttribute('aria-expanded'),'true');
  assert.equal(await page.evaluate(()=>document.activeElement.dataset.expand),'Alice');
  await page.locator('[data-expand]').click();
  await page.locator('#image-search').pressSequentially('Picture 4');
  assert.equal(await page.locator('#image-search').inputValue(),'Picture 4');
  assert.equal(await page.locator('.character-group [data-image]').count(),1);
  await page.locator('.character-group [data-image]').click();
  assert.equal(await page.locator('dialog').evaluate(el=>el.open),true);
  await page.keyboard.press('Escape');
  await page.locator('[data-page="people"]').click();
  assert.equal(await page.locator('#person-detail tbody tr').first().locator('td').first().innerText(),'Alice');
  assert.equal(await page.locator('.source-image').getAttribute('data-image'),'c4');
  assert.match(await page.locator('#person-detail').innerText(),/来源图片不可用/);
  await page.locator('#person-sort').selectOption('low');
  assert.equal(await page.locator('#person-detail tbody tr').first().locator('td').first().innerText(),'Zero');
  await page.locator('#people-search').pressSequentially('Reader');
  assert.equal(await page.locator('#people-search').inputValue(),'Reader');
  await page.locator('[data-action="theme"]').click();
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  await page.locator('#person-detail [data-character]').first().click();
  assert.equal(await page.locator('#image-search').inputValue(),'Zero');
  // Multiple participants: comparisons use exactly the selected person's votes.
  await mount({...data,statistics:{unique_voters:2,total_valid_votes:2}});
  await page.locator('[data-page="people"]').click();
  assert.equal(await page.locator('.comparison-row').count(),2);
  assert.match(await page.locator('.chart-legend').innerText(),/含本人/);
  // Configurable bounds, including the legal degenerate 0-only scale.
  for (const [min,max] of [[1,4],[0,100],[0,0]]) {
    const payload=JSON.parse(JSON.stringify(data));
    payload.session.score_min=min; payload.session.score_max=max;
    payload.characters.forEach((c,i)=>{c.score_distribution=i===0?{[min]:1,[max]:1}:{};});
    await mount(payload);
    assert.equal(await page.locator('.histogram g').count(),Math.ceil((max-min+1)/Math.max(1,Math.ceil((max-min+1)/11))));
    assert.equal(await page.locator('svg').evaluateAll(els=>els.some(el=>/NaN|Infinity/.test(el.outerHTML))),false);
    await page.locator('.chart-data summary').click();
    assert.equal(await page.locator('.chart-data').getAttribute('open'),'');
  }
  await mount({...data,participant_details_available:false,participants:[],votes:[]});
  assert.equal(await page.locator('[data-page="people"]').count(),0);
  await mount({...data,characters:[],candidates:[],participants:[],votes:[],statistics:{},metrics:{}});
  assert.match(await page.locator('.report-body').innerText(),/尚无有效评分/);
  assert.equal(await page.locator('.coverage-panel .ring-chart strong').innerText(),'—');
  await page.locator('[data-page="people"]').click();
  assert.match(await page.locator('#person-detail').innerText(),/暂无参与者明细/);
  assert.deepEqual(errors,[]);
  console.log('PASS: ranking, zero scores, escaped names, expansion, live search focus, dialog, source attribution, sorting, theme, privacy and empty states. No visual acceptance performed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
