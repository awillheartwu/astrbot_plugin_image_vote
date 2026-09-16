/* Panel page checks: layout at narrow/medium/wide widths plus empty and state rendering.
   No screenshots required; pass --shots <dir> to also write PNGs.
   Run: NODE_PATH=<playwright package root> node tools/check_panel_ui.cjs */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const panelDir = process.env.PANEL_DIR || path.join(root, 'pages/image-vote');
const schema = JSON.parse(fs.readFileSync(path.join(root, '_conf_schema.json'), 'utf8'));
const shotsArg = process.argv.indexOf('--shots');
const shotsDir = shotsArg >= 0 ? process.argv[shotsArg + 1] : null;
if (shotsDir) fs.mkdirSync(shotsDir, { recursive: true });

const values = {};
for (const group of Object.values(schema)) {
  for (const [key, def] of Object.entries(group.items || {})) values[key] = def.default ?? '';
}
const svg = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="48" height="64"><rect width="48" height="64" fill="#6d56ed"/></svg>');

const session = (over) => ({
  id: 'sess-1', project_name: '帝国编年史015', group_id: '123456', short_id: 'A7F3B21C',
  status: 'RUNNING', sent_count: 12, candidate_count: 45, vote_count: 9, participant_count: 4,
  report_state: 'missing', report_available: false, report_error: null, created_at: '2026-09-16T01:20:00+08:00',
  active_candidate: { id: 'c12', name: 'Elis-3' }, active_character: 'Elis', seconds_until_next: 12,
  error_message: null, character_count: 17, score_min: 0, score_max: 10, interval_seconds: 5,
  final_grace_seconds: 20, ...over,
});

const history = [
  session({ id: 'h1', short_id: 'AE71C5C7', status: 'COMPLETED', report_state: 'ready', report_available: true, vote_count: 46, participant_count: 6 }),
  session({ id: 'h2', short_id: 'B7061F3F', status: 'CANCELLED', report_state: 'missing', vote_count: 0, participant_count: 0 }),
  session({ id: 'h3', short_id: '7A31379F', status: 'COMPLETED', report_state: 'cleaned', vote_count: 1, participant_count: 1 }),
  session({ id: 'h4', short_id: 'AD630492', status: 'FAILED', report_state: 'failed', report_error: 'report generation failed: disk full', vote_count: 53, participant_count: 3 }),
  session({ id: 'h5', short_id: 'PAUSED01', status: 'PAUSED', report_state: 'generating', vote_count: 8, participant_count: 2, error_message: '连续 2 条消息发送失败，已自动暂停' }),
];

const scenarios = {
  rich: {
    projects: [
      { name: '帝国编年史015', path: '/AstrBot/data/vote-projects/帝国编年史015', source: 'registered', settings: { description: '45 张人物图，5 秒人物间隔', interval_seconds: 5 } },
      { name: '爱与嫉妒', path: '/AstrBot/data/vote-projects/爱与嫉妒', source: 'directory', settings: {} },
      { name: '空目录', path: '/AstrBot/data/vote-projects/空目录', source: 'directory', settings: {}, error: '目录里没有可用的图片文件' },
    ],
    active: [session({}), session({ id: 'sess-2', project_name: '爱与嫉妒', short_id: 'C0FFEE11', status: 'PAUSED', report_state: 'generating', active_character: 'Yaromir', seconds_until_next: null, error_message: '连续 2 条消息发送失败，已自动暂停' })],
    history,
    total: 42,
    groups: [{ umo: 'g1', name: '测试群', id: '123456', platform: 'aiocqhttp' }],
    providers: [{ id: 'deepseek', name: 'DeepSeek' }, { id: 'openai', name: 'OpenAI' }],
  },
  empty: { projects: [], active: [], history: [], total: 0, groups: [], providers: [] },
  offline: { fail: true },
};

function bridgeScript(data) {
  return ({ payload }) => {
    const respond = (value) => Promise.resolve({ status: 'ok', data: value });
    window.AstrBotPluginPage = {
      ready: () => Promise.resolve({ isDark: false }),
      onContext: () => {},
      download: () => {},
      apiGet: (endpoint, params = {}) => {
        if (payload.fail) return Promise.reject(new Error('连接中断'));
        if (endpoint === 'projects') return respond(payload.projects);
        if (endpoint === 'sessions') return respond({ sessions: params.active === 'true' ? payload.active : payload.history, total: payload.total });
        if (endpoint === 'config') return respond({ values: payload.values, schema: payload.schema, revision: 3 });
        if (endpoint === 'providers') return respond(payload.providers);
        if (endpoint === 'groups') return respond(payload.groups);
        if (endpoint === 'thumbnail') return respond({ image: payload.svg });
        return respond({});
      },
      apiPost: () => respond({}),
    };
  };
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const errors = [];
  const checked = [];
  try {
    for (const [name, scenario] of Object.entries(scenarios)) {
      const payload = { values, schema, svg, ...scenario };
      for (const width of [390, 768, 1440]) {
        for (const page of ['run', 'projects', 'history', 'settings']) {
          if (name === 'offline' && page !== 'run') continue;
          const context = await browser.newContext({ viewport: { width, height: 900 } });
          const tab = await context.newPage();
          tab.on('pageerror', (e) => errors.push(name + '/' + width + '/' + page + ': ' + e.message));
          await tab.addInitScript(bridgeScript(payload), { payload });
          // 固定时钟，让截图可逐字节比较
          await tab.addInitScript(() => {
            const RealDate = Date, fixed = new RealDate('2026-09-16T06:00:00+08:00').getTime();
            class FrozenDate extends RealDate {
              constructor(...args) { super(...(args.length ? args : [fixed])); }
              static now() { return fixed; }
            }
            window.Date = FrozenDate;
          });
          await tab.goto('file://' + path.join(panelDir, 'index.html') + '#' + page);
          await tab.waitForSelector('#app .empty, #app .surface, #app .admin-stats, #modal', { timeout: 10000 }).catch(() => {});
          await tab.waitForTimeout(250);
          const overflow = await tab.evaluate(() => ({
            scrollWidth: document.documentElement.scrollWidth,
            innerWidth: window.innerWidth,
            offenders: [...document.querySelectorAll('body *')]
              .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 3)
              .map((el) => el.className || el.tagName),
          }));
          assert.ok(
            overflow.scrollWidth <= overflow.innerWidth + 1,
            name + ' ' + width + 'px ' + page + ' 横向溢出 ' + overflow.scrollWidth + ' > ' + overflow.innerWidth + '（' + overflow.offenders.join(', ') + '）',
          );
          if (shotsDir) await tab.screenshot({ path: path.join(shotsDir, name + '-' + page + '-' + width + '.png'), fullPage: true });
          checked.push(name + '/' + page + '/' + width);
          await context.close();
        }
      }
    }
    assert.deepEqual(errors, []);
    console.log('PASS: ' + checked.length + ' 组页面（390/768/1440 × 运行/项目/历史/设置 × 正常/空态/断连）无横向溢出、无脚本错误');
    if (shotsDir) console.log('截图目录: ' + shotsDir);
  } finally {
    await browser.close();
  }
})();
