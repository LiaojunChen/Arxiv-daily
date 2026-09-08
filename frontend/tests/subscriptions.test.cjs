const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');

function load(file, dependencies = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', 'src', file), 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, {exports, require: name => dependencies[name]});
  return exports;
}
const { mergeFollowedPapers } = load('utils/subscriptions.ts', {
  './affiliations': load('utils/affiliations.ts'),
  '../../../data/institution_aliases.json': require('../../data/institution_aliases.json'),
});
const paper = {arxiv_id: '2609.00001', authors: ['Alice Smith'], affiliations: ['Massachusetts Institute of Technology']};
const empty = {followed_authors: [], followed_institutions: []};
test('author in the complete candidate pool is found', () => {
  assert.equal(mergeFollowedPapers([], [paper], {...empty, followed_authors: ['Alice Smith']}).length, 1);
});
test('institution aliases resolve', () => {
  for (const alias of ['MIT', '麻省理工学院']) {
    assert.equal(mergeFollowedPapers([], [paper], {...empty, followed_institutions: [alias]}).length, 1);
  }
});
test('clearing subscriptions also filters server results', () => {
  assert.equal(mergeFollowedPapers([paper], [paper], empty).length, 0);
});
test('duplicate source records produce one result', () => {
  assert.equal(mergeFollowedPapers([paper], [paper], {...empty, followed_authors: ['Alice Smith']}).length, 1);
});
test('partial author names do not create accidental matches', () => {
  assert.equal(mergeFollowedPapers([], [paper], {...empty, followed_authors: ['Smith']}).length, 0);
});
