import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {transform} from 'esbuild';
import {Miniflare, convertV4MiniflareOptions} from 'miniflare';

test('migrations, preferences, authentication and feedback round trip', async () => {
  const source = await readFile(new URL('../src/index.ts', import.meta.url), 'utf8');
  const {code} = await transform(source, {loader: 'ts', format: 'esm'});
  const mf = new Miniflare(convertV4MiniflareOptions({modules: true, script: code, compatibilityDate: '2026-09-08',
    d1Databases: {DB: 'test-db'}, bindings: {
      ALLOWED_ORIGINS: 'https://example.test', FEEDBACK_ACCESS_CODE: 'test-public', SYNC_API_TOKEN: 'test-private',
    }}));
  try {
    const db = await mf.getD1Database('DB');
    await db.exec((await readFile(new URL('../migrations/0001_initial.sql', import.meta.url), 'utf8')).replaceAll('\n', ' '));
    await db.prepare(`INSERT INTO feedback_events (event_key,paper_id,run_id,action,paper_title,client_hash)
      VALUES ('legacy','old','old','like','Old paper','old')`).run();
    await db.exec((await readFile(new URL('../migrations/0002_preferences.sql', import.meta.url), 'utf8')).replaceAll('\n', ' '));
    const post = (path, body, headers={}) => mf.dispatchFetch(`https://worker.test${path}`, {method: 'POST',
      headers: {'content-type': 'application/json', origin: 'https://example.test', 'x-feedback-access-code': 'test-public', ...headers},
      body: JSON.stringify(body)});
    const get = path => mf.dispatchFetch(`https://worker.test${path}`, {headers: {authorization: 'Bearer test-private'}});
    assert.equal((await post('/v1/preferences', {}, {origin: 'https://evil.test'})).status, 403);
    assert.equal((await post('/v1/preferences', {}, {'x-feedback-access-code': 'wrong'})).status, 401);
    assert.equal((await post('/v1/preferences', {followed_authors: 'bad', followed_institutions: []})).status, 400);
    assert.equal((await post('/v1/preferences', {followed_authors: ['Alice Smith'], followed_institutions: ['MIT'], ai_api_key: 'must-not-store'})).status, 200);
    let prefs = await (await get('/v1/internal/preferences')).json();
    assert.deepEqual(prefs.preferences, {followed_authors: ['Alice Smith'], followed_institutions: ['MIT']});
    assert.equal(prefs.revision, 1);
    await post('/v1/preferences', {followed_authors: [], followed_institutions: []});
    prefs = await (await get('/v1/internal/preferences')).json();
    assert.equal(prefs.revision, 2);
    assert.deepEqual(prefs.preferences.followed_authors, []);
    for (const action of ['read', 'bookmark', 'dismiss', 'not_interested']) {
      const response = await post('/v1/feedback', {paper_id: '2609.00001', run_id: 'run', client_id: 'browser', action,
        paper: {title: 'World models', abstract: 'A useful abstract.', keywords: ['world model']}});
      assert.equal(response.status, 201);
    }
    const {events} = await (await get('/v1/internal/feedback')).json();
    assert.deepEqual(events.map(e => e.action), ['like', 'read', 'bookmark', 'dismiss', 'not_interested']);
    assert.equal(events[1].paper.abstract, 'A useful abstract.');
    const ack = await mf.dispatchFetch('https://worker.test/v1/internal/ack', {method: 'POST',
      headers: {authorization: 'Bearer test-private', 'content-type': 'application/json'},
      body: JSON.stringify({feedback_ids: events.map(e => e.feedback_id)})});
    assert.equal(ack.status, 200);
    assert.deepEqual((await (await get('/v1/internal/feedback')).json()).events, []);
    assert.equal((await post('/v1/preferences', {padding: 'x'.repeat(70000)})).status, 400);
  } finally { await mf.dispose(); }
});
