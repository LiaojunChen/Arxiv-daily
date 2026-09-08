const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function load(fetch) {
  const source = fs.readFileSync(path.join(__dirname, '../src/utils/feedback.ts'), 'utf8')
    .replaceAll('import.meta.env.VITE_FEEDBACK_API_URL', '"https://example.test"');
  const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
  const exports = {};
  vm.runInNewContext(code, {exports, fetch, crypto: {randomUUID: () => 'unique-event'},
    localStorage: {getItem: () => 'client', setItem() {}},
    require: () => ({loadSettings: () => ({feedback_access_code: 'access-code'})})});
  return exports;
}

test('subscription sync sends only follow lists, including clearing, never AI credentials', async () => {
  let body;
  const {syncSubscriptions} = load(async (_url, options) => {
    body = JSON.parse(options.body);
    return {ok: true};
  });
  await syncSubscriptions({followed_authors: [], followed_institutions: [], feedback_access_code: 'access-code', ai_api_key: 'PRIVATE'});
  assert.deepEqual(body, {followed_authors: [], followed_institutions: []});
});

test('feedback preserves distinct actions and useful paper examples', async () => {
  let body;
  const {submitPaperFeedback} = load(async (_url, options) => {
    body = JSON.parse(options.body);
    return {ok: true, json: async () => ({duplicate: false})};
  });
  await submitPaperFeedback({arxiv_id: 'a', title: 'Paper', abstract: 'Actual abstract', keywords: ['vision']}, 'run', 'read');
  assert.equal(body.action, 'read');
  assert.equal(body.paper.abstract, 'Actual abstract');
  assert.equal(body.event_id, 'unique-event');
});

test('failed preference sync is reported instead of pretending it succeeded', async () => {
  const {syncSubscriptions} = load(async () => ({ok: false}));
  await assert.rejects(syncSubscriptions({followed_authors: [], followed_institutions: [], feedback_access_code: 'code'}), /同步失败/);
});
