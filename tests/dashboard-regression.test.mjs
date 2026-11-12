import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

// Execute the production inline script, suppressing only its network-backed startup.
// There is deliberately no fetch implementation or live DOM in this context.
function loadDashboard() {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const scripts = [...html.matchAll(/<script\s*>([\s\S]*?)<\/script>/gi)];
  assert.equal(scripts.length, 1, 'Expected exactly one production inline script');
  const source = scripts[0][1];
  const startup = /^\s*init\(\);\s*$/gm;
  assert.equal([...source.matchAll(startup)].length, 1, 'Expected one startup call');

  const elements = new Map();
  const context = vm.createContext({
    window: { matchMedia: () => ({ matches: false }), addEventListener: () => {} },
    document: { getElementById: id => {
      if (!elements.has(id)) elements.set(id, { innerHTML: '' });
      return elements.get(id);
    } },
    fetch: () => { throw new Error('Network access is forbidden in regression tests'); },
  });
  vm.runInContext(source.replace(startup, '') + `
    globalThis.dashboardTest = {
      setState(state) {
        allReviews = state.reviews || [];
        allStores = [];
        currentSV = state.sv || null;
        if (currentSV) initializeCurrentSVScope();
        else { currentSVReviews = []; currentSVStores = []; }
        currentCountry = state.country || 'ALL';
        currentStore = state.store || 'ALL';
        currentPeriod = state.period || 'all';
        customPeriodStart = state.start || '';
        customPeriodEnd = state.end || '';
        currentKeyword = state.keyword || null;
        lowRatingOnly = !!state.low;
        newReviewOnly = !!state.newOnly;
        crawlStatus = state.crawlStatus || null;
        insightsShowAllKeywords = true;
      },
      getCurrentFilteredReviews, getInsightsBaseReviews,
      classifyMonthlyTrendDate, getMonthlyTrend, matchesKeywordCategory,
      renderKeywordCloud, getKstMonth,
      summarizeCollectionRun, latestStoreCollectionLabel,
    };
  `, context, { filename: 'index.html:inline-script' });
  return { app: context.dashboardTest, element: id => elements.get(id) };
}

const review = (id, options = {}) => ({
  id, sv: '이여명', country: 'Taiwan', store_name: 'Taipei A',
  text: 'friendly staff', rating: 5, date: '1 day ago',
  collected_at: '2024-03-01', review_date: '2024-02-29',
  first_seen_run_id: 8, ...options,
});
const ids = reviews => Array.from(reviews, item => item.id);

test('collection summary separates observation, verified completeness and execution failure', () => {
  const { app } = loadDashboard();
  const run = { total_stores: 5, success_count: 3, failed_count: 0, stores: [
    { store_name: 'Verified store', collection_status: 'VERIFIED' },
    { store_name: 'Observed store', collection_status: 'PARTIAL', collected_count: 0 },
    { store_name: 'Blocked store', collection_status: 'FAILED', ok: true },
    { store_name: 'Skipped store', collection_status: 'NOT_CHECKED' },
    { store_name: 'Legacy store', ok: true, collected_count: 0 },
  ] };
  const summary = app.summarizeCollectionRun(run);
  assert.deepEqual({ ...summary.counts }, { VERIFIED: 1, PARTIAL: 1, FAILED: 1, NOT_CHECKED: 1 });
  assert.deepEqual(Array.from(summary.failedNames), ['Blocked store']);
  assert.equal(summary.unrecorded, 1);
  app.setState({ crawlStatus: run });
  assert.equal(app.latestStoreCollectionLabel('Observed store'), '일부 관측');
  assert.equal(app.latestStoreCollectionLabel('Skipped store'), '미시도');
  assert.equal(app.latestStoreCollectionLabel('Outside run'), '미시도');
  assert.equal(app.latestStoreCollectionLabel('Legacy store'), '상태 미기록');
});

test('legacy success counters never create verified stores and legacy failures are not double-counted', () => {
  const { app } = loadDashboard();
  const summary = app.summarizeCollectionRun({ total_stores: 4, success_count: 3, failed_count: 1, stores: [
    { store_name: 'Legacy success', ok: true, collected_count: 0 },
    { store_name: 'Legacy observation', ok: true, collected_count: 2 },
    { store_name: 'Legacy failure', ok: false, collected_count: 0 },
  ], failed_stores: [{ store_name: 'Legacy failure' }] });
  assert.deepEqual({ ...summary.counts }, { VERIFIED: 0, PARTIAL: 1, FAILED: 1, NOT_CHECKED: 0 });
  assert.equal(summary.unrecorded, 2);
});

test('Reviews and Insights share SV, country, store and inclusive period scope', () => {
  const { app } = loadDashboard();
  const reviews = [
    review('start', { review_date: '2024-02-01' }),
    review('end', { review_date: '2024-02-29' }),
    review('outside', { review_date: '2024-03-01' }),
    review('other-store', { store_name: 'Taipei B' }),
    review('other-country', { country: 'Singapore', store_name: 'Singapore A' }),
    review('other-sv', { sv: '강소영', country: 'Mongolia', store_name: 'Ulaanbaatar' }),
  ];
  app.setState({ reviews });
  assert.equal(app.getInsightsBaseReviews().length, 6);
  app.setState({ reviews, sv: '이여명' });
  assert.deepEqual(ids(app.getInsightsBaseReviews()), ['start', 'end', 'outside', 'other-store', 'other-country']);
  app.setState({ reviews, sv: '이여명', country: 'Taiwan', store: 'Taipei A', period: 'custom', start: '2024-02-01', end: '2024-02-29' });
  assert.deepEqual(ids(app.getInsightsBaseReviews()), ['start', 'end']);
  assert.deepEqual(ids(app.getCurrentFilteredReviews()), ['start', 'end']);
  app.setState({ reviews, sv: '강소영' });
  assert.deepEqual(ids(app.getInsightsBaseReviews()), ['other-sv']);
});

test('Reviews keyword, LOW and NEW filters do not change Insights scope', () => {
  const { app } = loadDashboard();
  const reviews = [
    review('match', { rating: 2, first_seen_run_id: 9 }),
    review('high', { rating: 5, first_seen_run_id: 9 }),
    review('older', { rating: 2, first_seen_run_id: 8 }),
    review('different', { text: 'delicious', rating: 2, first_seen_run_id: 9 }),
  ];
  const scope = { reviews, sv: '이여명', country: 'Taiwan', crawlStatus: { id: 9 } };
  app.setState(scope);
  const before = ids(app.getInsightsBaseReviews());
  for (const [filters, expected] of [
    [{ keyword: 'service' }, ['match', 'high', 'older']],
    [{ low: true }, ['match', 'older', 'different']],
    [{ newOnly: true }, ['match', 'high', 'different']],
    [{ keyword: 'service', low: true, newOnly: true }, ['match']],
  ]) {
    app.setState({ ...scope, ...filters });
    assert.deepEqual(ids(app.getCurrentFilteredReviews()), expected);
    assert.deepEqual(ids(app.getInsightsBaseReviews()), before);
  }
});

test('monthly date eligibility rejects imprecise, unsupported and inconsistent dates', () => {
  const { app } = loadDashboard();
  const cases = [
    [review('hour', { date: '2 hours ago', review_date: '2024-03-01' }), null],
    [review('leap'), null],
    [review('week', { date: '1 week ago', review_date: '2024-02-23' }), null],
    [review('month', { date: '1 month ago', review_date: '2024-01-31' }), null],
    [review('year', { date: '1 year ago' }), 'year'],
    [review('recent', { date: 'Recent' }), 'unknown'],
    [review('missing', { date: '' }), 'unsupported'],
    [review('unsupported', { date: 'yesterday' }), 'unsupported'],
    [review('wrong', { review_date: '2024-02-28' }), 'invalid'],
    [review('invalid-date', { collected_at: '2024-02-30' }), 'invalid'],
    [review('missing-date', { review_date: null }), 'invalid'],
  ];
  for (const [item, reason] of cases) {
    const result = app.classifyMonthlyTrendDate(item);
    assert.equal(result.reason, reason, item.id);
    assert.equal(Boolean(result.date), reason === null, item.id);
  }
});

test('monthly grouping reconciles exclusions, fills gaps and handles leap years and invalid ratings', () => {
  const { app } = loadDashboard();
  const reviews = [
    review('dec', { date: '1 day ago', collected_at: '2023-12-02', review_date: '2023-12-01', rating: 5 }),
    review('leap', { rating: 1 }),
    review('bad-rating', { rating: 'bad' }),
    review('too-high', { rating: 6 }),
    review('year', { date: 'a year ago' }),
    review('unknown', { date: 'Unknown' }),
    review('unsupported', { date: '' }),
    review('inconsistent', { review_date: '2024-02-28' }),
  ];
  const result = app.getMonthlyTrend(reviews);
  assert.equal(result.included, 4);
  assert.equal(result.excluded, 4);
  assert.equal(Object.values(result.exclusions).reduce((a, b) => a + b, 0), result.excluded);
  assert.deepEqual(Array.from(result.buckets, b => b.label), ['2023.12', '2024.01', '2024.02']);
  assert.equal(result.buckets[1].count, 0);
  assert.equal(result.buckets[2].end, '2024-02-29');
  assert.equal(result.buckets[2].count, 3);
  assert.equal(result.buckets[2].ratingCount, 1);
  assert.equal(result.buckets[2].ratingSum, 1);
  assert.equal(Array.from(result.buckets).reduce((sum, b) => sum + b.count, 0) + result.excluded, reviews.length);
  // Monthly eligibility must not remove imprecisely dated reviews from Insights.
  app.setState({ reviews });
  assert.equal(app.getInsightsBaseReviews().length, reviews.length);
  assert.equal(app.getCurrentFilteredReviews().length, reviews.length);
  assert.equal(app.getMonthlyTrend([]).buckets.length, 0);
  assert.equal(app.getMonthlyTrend([reviews[0]]).buckets.length, 1);
  assert.equal(app.getKstMonth(new Date('2024-01-31T14:59:59Z')), '2024.01');
  assert.equal(app.getKstMonth(new Date('2024-01-31T15:00:00Z')), '2024.02');
});

test('keyword matching uses boundaries, supports variants and permits genuine overlaps', () => {
  const { app } = loadDashboard();
  for (const [text, category] of [['happy', 'operation'], ['waiter', 'reservation'], ['시간', 'taste'], ['양말', 'value'], ['줄기', 'reservation'], ['또래', 'revisit']]) {
    assert.equal(app.matchesKeywordCategory(text, category), false, `${text}: ${category}`);
  }
  for (const [text, category] of [['app', 'operation'], ['waiting', 'reservation'], ['friendly staff', 'service'], ['delicious food', 'taste'], ['jajangmyeon', 'food'], ['김치찌개', 'food']]) {
    assert.equal(app.matchesKeywordCategory(text, category), true, `${text}: ${category}`);
  }
  assert.equal(app.matchesKeywordCategory('friendly staff and waiting', 'service'), true);
  assert.equal(app.matchesKeywordCategory('friendly staff and waiting', 'reservation'), true);
});

test('keyword output counts reviews once and uses valid-rated matches for averages and low share', () => {
  const { app, element } = loadDashboard();
  const reviews = [
    review('one', { text: 'friendly friendly staff', rating: 1 }),
    review('three', { rating: 3 }),
    review('five', { rating: 5 }),
    ...[null, '', 0, 6, 'bad', true, '0x5'].map((rating, index) => review(`invalid-${index}`, { rating })),
    review('no-valid-rating', { text: 'app', rating: null }),
  ];
  app.setState({ reviews });
  app.renderKeywordCloud(app.getInsightsBaseReviews());
  const html = element('keyword-cloud').innerHTML;
  const row = key => {
    const match = html.match(new RegExp(`<button[^>]*applyKeywordFromInsight\\('${key}'\\)[\\s\\S]*?<\\/button>`));
    assert.ok(match, `Missing ${key} row`);
    return match[0];
  };
  assert.match(row('service'), /10건/);
  assert.match(row('service'), /평균 별점 3\.00/);
  assert.match(row('service'), /저평점 66\.7%/);
  assert.match(row('operation'), /1건/);
  assert.match(row('operation'), /평균 별점 -/);
  assert.match(row('operation'), /저평점 -/);
  app.renderKeywordCloud([]);
  assert.match(element('keyword-cloud').innerHTML, /표시할 데이터가 없습니다/);
});
