const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');

function mount(fetch) {
  const effects = [], states = [], listeners = new Map();
  let poll;
  const document = {
    visibilityState: 'visible',
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: name => listeners.delete(name),
  };
  const window = {
    ...document,
    setInterval: fn => { poll = fn; return 1; },
    clearInterval: () => { poll = undefined; },
    setTimeout: () => 2,
    clearTimeout: () => {},
  };
  const react = {
    useEffect: fn => effects.push(fn),
    useMemo: () => ({}),
    useState: initial => {
      const index = states.length;
      states.push(typeof initial === 'function' ? initial() : initial);
      return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }];
    },
  };
  const source = fs.readFileSync(path.join(__dirname, '../src/hooks/usePapers.ts'), 'utf8')
    .replaceAll('import.meta.env.BASE_URL', '"/"');
  const code = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, fetch, window, document, AbortController,
    console: {error() {}}, require: name => name === 'react' ? react : {loadSettings: () => ({})} });
  exports.usePapers();
  const unmount = effects[0]();
  return {states, listeners, document, poll: () => poll?.(), unmount};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('open pages refresh on visibility and polling, retain data on network failure', async () => {
  let calls = 0, fail = false;
  const app = mount(async (url, options) => {
    calls++;
    assert.equal(url, '/papers.json');
    assert.equal(options.cache, 'no-cache');
    if (fail) throw Error('network');
    return {ok: true, json: async () => ({run_id: `run-${calls}`, updated_at: `${calls}`})};
  });
  await settle();
  assert.equal(app.states[0].run_id, 'run-1');
  app.document.visibilityState = 'hidden';
  app.poll();
  assert.equal(calls, 1);
  app.document.visibilityState = 'visible';
  app.listeners.get('visibilitychange')();
  await settle();
  assert.equal(app.states[0].run_id, 'run-2');
  fail = true;
  app.poll();
  await settle();
  assert.equal(app.states[0].run_id, 'run-2');
  assert.equal(app.states[2], null);
  app.unmount();
  app.poll();
  assert.equal(calls, 3);
  assert.equal(app.listeners.size, 0);
});

test('refresh does not overlap requests and unmount aborts the pending fetch', async () => {
  let calls = 0, signal;
  const app = mount((_url, options) => {
    calls++;
    signal = options.signal;
    return new Promise((_, reject) => signal.addEventListener('abort', () => reject(Error('aborted'))));
  });
  app.poll();
  app.listeners.get('focus')();
  assert.equal(calls, 1);
  app.unmount();
  await settle();
  assert.equal(signal.aborted, true);
  assert.equal(app.states[0], null);
});
