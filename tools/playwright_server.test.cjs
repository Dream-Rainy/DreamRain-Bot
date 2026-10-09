'use strict';

const assert = require('node:assert/strict');
const { test } = require('node:test');
const { randomBytes } = require('node:crypto');
const { chromium } = require('playwright');
const { startServer } = require('./playwright_server.cjs');

test('real server fallback, readiness and browser survival across client reconnects', { timeout: 90000 }, async () => {
  const service = await startServer({ mode: 'auto', host: '127.0.0.1', port: 0, healthPort: 0, binaryPort: 0 });
  try {
    const health = await fetch(`http://127.0.0.1:${service.healthPort}`);
    assert.equal(health.status, 200);
    assert.equal((await health.json()).ready, true);
    assert.equal(new URL(service.endpoint).pathname, '/');
    if (!service.info.hardware) {
      assert.equal(service.info.mode, 'cpu');
      assert.ok(service.info.fallbackReason);
      await assert.rejects(startServer({ mode: 'gpu', host: '127.0.0.1', port: 0, healthPort: 0 }), /Hardware compositing|Renderer inspection|browserType/);
    }
    for (let connection = 0; connection < 2; connection++) {
      const browser = await chromium.connect(service.endpoint);
      try {
        const page = await browser.newPage();
        await page.setContent('<p>Reconnect: 中文 / 日本語 / ABC</p>');
        assert.equal(await page.locator('p').textContent(), 'Reconnect: 中文 / 日本語 / ABC');
        assert.ok((await page.screenshot()).length > 100);
        await page.close();
      } finally { await browser.close(); }
    }
    assert.equal((await fetch(`http://127.0.0.1:${service.healthPort}`)).status, 200);
  } finally { await service.stop(); }
});

test('binary delivery isolates pages, consumes bytes once and releases cancelled reservations', { timeout: 90000 }, async (t) => {
  const service = await startServer({ mode: 'cpu', host: '127.0.0.1', port: 0, healthPort: 0, binaryPort: 0 });
  const browser = await chromium.connect(service.endpoint);
  const endpoint = `http://127.0.0.1:${service.binaryPort}`;
  const arm = (page, id) => fetch(endpoint + '/screenshots', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ page: page._guid || page._impl?._guid, id }),
  });
  const id = () => randomBytes(16).toString('hex');
  try {
    const pages = await Promise.all([browser.newPage({ viewport: { width: 160, height: 80 } }), browser.newPage({ viewport: { width: 120, height: 100 } })]);
    await Promise.all(pages.map((page, i) => page.setContent(`<body style="background:${i ? 'blue' : 'red'}">${i}</body>`)));
    const expected = await Promise.all(pages.map(page => page.screenshot()));
    assert.notDeepEqual(expected[0], expected[1]);
    const tokens = [id(), id()];
    for (let i = 0; i < pages.length; i++) assert.equal((await arm(pages[i], tokens[i])).status, 201);
    assert.equal((await arm(pages[0], id())).status, 409);
    const markers = await Promise.all(pages.map(page => page.screenshot()));
    for (let i = 0; i < pages.length; i++) {
      assert.equal(markers[i].toString(), `chiffon-binary-v1:${tokens[i]}:${expected[i].length}`);
      const response = await fetch(endpoint + '/screenshots/' + tokens[i]);
      assert.equal(response.headers.get('content-type'), 'image/png');
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), expected[i]);
      assert.equal((await fetch(endpoint + '/screenshots/' + tokens[i])).status, 404);
    }
    const cancelled = id();
    assert.equal((await arm(pages[0], cancelled)).status, 201);
    assert.equal((await fetch(endpoint + '/screenshots/' + cancelled, { method: 'DELETE' })).status, 204);
    assert.deepEqual(await pages[0].screenshot(), expected[0]);
    // Browser disposal releases a captured but unclaimed buffer.
    const abandoned = id();
    assert.equal((await arm(pages[1], abandoned)).status, 201);
    await pages[1].screenshot();
    await pages[1].close();
    assert.deepEqual(await (await fetch(endpoint)).json(), { protocol: 1, pending: 0, bytes: 0 });
    // Invalid/overfull arm requests cannot allocate an unbounded queue.
    const reservations = Array.from({ length: 16 }, id);
    for (const token of reservations) {
      assert.equal((await arm({ _guid: 'page@' + id() }, token)).status, 201);
    }
    assert.equal((await arm({ _guid: 'page@' + id() }, id())).status, 429);
    assert.equal((await arm({ _guid: '../bad-page' }, id())).status, 400);
    for (const token of reservations) await fetch(endpoint + '/screenshots/' + token, { method: 'DELETE' });
    assert.deepEqual(await (await fetch(endpoint)).json(), { protocol: 1, pending: 0, bytes: 0 });
    t.mock.timers.enable({ apis: ['setTimeout'] });
    try {
      assert.equal((await arm(pages[0], id())).status, 201);
      t.mock.timers.tick(60001);
      assert.deepEqual(await (await fetch(endpoint)).json(), { protocol: 1, pending: 0, bytes: 0 });
    } finally { t.mock.timers.reset(); }
    assert.deepEqual(await pages[0].screenshot(), expected[0]);
  } finally {
    await browser.close();
    await service.stop();
  }
});
