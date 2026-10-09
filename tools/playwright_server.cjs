'use strict';

const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');

const armedScreenshots = new Map();
let binaryInstalled = false;
const BINARY_PREFIX = 'chiffon-binary-v1:';

function installBinaryScreenshots() {
  // This small hook is specific to our pinned Playwright protocol, not CDP.
  if (require('playwright/package.json').version !== '1.57.0') return false;
  if (binaryInstalled) return true;
  const root = path.dirname(require.resolve('playwright-core/package.json'));
  const { PageDispatcher } = require(path.join(root, 'lib/server/dispatchers/pageDispatcher.js'));
  const screenshot = PageDispatcher.prototype.screenshot;
  PageDispatcher.prototype.screenshot = async function(params, progress) {
    const job = armedScreenshots.get(this._guid);
    if (!job) return screenshot.call(this, params, progress);
    armedScreenshots.delete(this._guid); // One shot only, including lost arm replies.
    job.page = this._page;
    job.page.once('close', job.drop);
    try {
      const result = await screenshot.call(this, params, progress);
      if (!job.publish(result.binary, params.type === 'jpeg' ? 'image/jpeg' : 'image/png')) return result;
      return { binary: Buffer.from(`${BINARY_PREFIX}${job.id}:${result.binary.length}`) };
    } catch (error) {
      job.drop();
      throw error;
    }
  };
  binaryInstalled = true;
  return true;
}

async function startBinaryServer(host, port) {
  const enabled = installBinaryScreenshots();
  const jobs = new Map();
  let storedBytes = 0;
  const json = (response, status, value) => {
    response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    response.end(JSON.stringify(value));
  };
  const binary = http.createServer(async (request, response) => {
    try {
      if (request.method === 'GET' && request.url === '/') {
        json(response, 200, { protocol: enabled ? 1 : 0, pending: jobs.size, bytes: storedBytes });
        return;
      }
      const resource = /^\/screenshots\/([a-f0-9]{32})$/.exec(request.url);
      if (resource && request.method === 'DELETE') {
        jobs.get(resource[1])?.drop();
        response.writeHead(204); response.end(); return;
      }
      if (resource && request.method === 'GET') {
        const job = jobs.get(resource[1]);
        if (!job?.buffer || job.claimed) { json(response, 404, { error: 'Screenshot unavailable' }); return; }
        job.claimed = true;
        job.response = response;
        response.once('finish', job.drop);
        response.once('close', job.drop);
        response.writeHead(200, { 'Content-Type': job.mime, 'Content-Length': job.buffer.length, 'Cache-Control': 'no-store' });
        response.end(job.buffer);
        return;
      }
      if (request.method !== 'POST' || request.url !== '/screenshots') {
        json(response, 404, { error: 'Unknown endpoint' }); return;
      }
      if (!enabled) { json(response, 503, { error: 'Unsupported Playwright version' }); return; }
      const parts = []; let length = 0;
      for await (const part of request) {
        length += part.length;
        if (length > 4096) { json(response, 413, { error: 'Request too large' }); return; }
        parts.push(part);
      }
      const { id, page } = JSON.parse(Buffer.concat(parts).toString());
      if (typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id)
          || typeof page !== 'string' || !/^page@[a-f0-9]{32}$/.test(page)) {
        json(response, 400, { error: 'Invalid request or page identity' }); return;
      }
      if (jobs.has(id) || armedScreenshots.has(page)) { json(response, 409, { error: 'Screenshot already armed' }); return; }
      if (jobs.size >= 16) { json(response, 429, { error: 'Screenshot queue full' }); return; }
      const job = { id, buffer: null };
      job.drop = () => {
        if (armedScreenshots.get(page) === job) armedScreenshots.delete(page);
        if (!jobs.delete(id)) return;
        clearTimeout(job.timer);
        job.page?.removeListener('close', job.drop);
        storedBytes -= job.buffer?.length || 0;
        job.buffer = null;
        if (job.response && !job.response.writableFinished) job.response.destroy();
      };
      job.publish = (buffer, mime) => {
        if (jobs.get(id) !== job || buffer.length > 16 * 1024**2 || storedBytes + buffer.length > 64 * 1024**2) {
          job.drop(); return false; // Oversized/full transfers use the original protocol.
        }
        job.buffer = buffer; job.mime = mime; storedBytes += buffer.length;
        return true;
      };
      // Temporary delivery storage only; no image reuse, disk files or tmpfs.
      job.timer = setTimeout(job.drop, 60000);
      job.timer.unref();
      jobs.set(id, job); armedScreenshots.set(page, job);
      json(response, 201, { protocol: 1, id });
    } catch (error) {
      if (!response.headersSent) json(response, 400, { error: 'Invalid screenshot request' });
      else response.destroy(error);
    }
  });
  binary.requestTimeout = 5000;
  await new Promise((resolve, reject) => {
    binary.once('error', reject);
    binary.listen(port, host, resolve);
  });
  return {
    port: binary.address().port,
    async stop() {
      for (const job of jobs.values()) job.drop();
      const closed = new Promise(resolve => binary.close(resolve));
      binary.closeAllConnections();
      await closed;
    },
  };
}

function launchArgs(mode) {
  if (mode === 'cpu') return ['--disable-gpu', '--disable-gpu-compositing'];
  const args = ['--enable-gpu', '--enable-gpu-rasterization'];
  if (process.platform === 'linux') {
    args.push('--use-angle=vulkan', '--enable-features=Vulkan', '--disable-vulkan-surface');
  }
  return args;
}

async function inspect(endpoint) {
  const browser = await chromium.connect(endpoint, { timeout: 5000 });
  try {
    const page = await browser.newPage({ viewport: { width: 64, height: 64 } });
    try {
      await page.setContent('<canvas width="16" height="16"></canvas>');
      const webglRenderer = await page.evaluate(() => {
        const gl = document.querySelector('canvas').getContext('webgl');
        const extension = gl?.getExtension('WEBGL_debug_renderer_info');
        return extension ? gl.getParameter(extension.UNMASKED_RENDERER_WEBGL) : '';
      });
      await page.screenshot({ timeout: 5000 });
      const session = await browser.newBrowserCDPSession();
      const { gpu } = await session.send('SystemInfo.getInfo');
      const renderer = webglRenderer || gpu.auxAttributes?.glRenderer || '';
      const features = gpu.featureStatus || {};
      const hardware = Boolean(renderer) && !/swiftshader|llvmpipe|lavapipe|softpipe|swrast|software|microsoft basic render/i.test(renderer)
        && String(features.gpu_compositing).startsWith('enabled')
        && String(features.rasterization).startsWith('enabled');
      return { renderer, features, hardware };
    } finally {
      await page.close();
    }
  } finally {
    // This disconnects the client; launchServer owns the shared browser.
    await browser.close();
  }
}

async function startServer({ mode = process.env.PLAYWRIGHT_GPU_MODE || 'auto', host = '0.0.0.0', port = 3000, healthPort = 3001, binaryPort = 3002 } = {}) {
  if (!['auto', 'cpu', 'gpu'].includes(mode)) throw new Error(`Invalid PLAYWRIGHT_GPU_MODE: ${mode}`);
  let server;
  let binary;
  let ready = false;
  let stopping = false;
  let info = { requestedMode: mode, platform: process.platform };
  const health = http.createServer((_request, response) => {
    response.writeHead(ready ? 200 : 503, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ ready, ...info }));
  });
  await new Promise((resolve, reject) => {
    health.once('error', reject);
    health.listen(healthPort, '127.0.0.1', resolve);
  });
  const stop = async () => {
    stopping = true;
    ready = false;
    try {
      if (binary) await binary.stop();
      if (server) await server.close();
    }
    finally { await new Promise(resolve => health.close(resolve)); }
  };
  const launch = async selected => {
    server = await chromium.launchServer({ headless: true, host, port, wsPath: '/', args: launchArgs(selected), timeout: 15000 });
    // The health endpoint stays 503 until both inspection and any fallback finish.
    let timer;
    try {
      const status = await Promise.race([
        inspect(server.wsEndpoint()),
        new Promise((_resolve, reject) => { timer = setTimeout(() => reject(new Error('Renderer inspection timed out')), 10000); }),
      ]);
      if (selected === 'gpu' && !status.hardware) {
        throw new Error(`Hardware compositing/rasterization unavailable: ${JSON.stringify(status)}`);
      }
      info = { ...info, mode: selected, ...status };
    } finally {
      clearTimeout(timer);
    }
  };
  try {
    try {
      await launch(mode === 'cpu' ? 'cpu' : 'gpu');
    } catch (error) {
      if (mode !== 'auto') throw error;
      info.fallbackReason = error.message;
      console.warn(`[playwright] GPU unavailable; falling back to CPU: ${error.message}`);
      if (server) await server.close();
      server = undefined;
      await launch('cpu');
    }
    binary = await startBinaryServer(host, binaryPort);
    server.on('close', () => {
      ready = false;
      if (!stopping) {
        console.error('[playwright] Shared browser exited; stopping service');
        health.close();
        binary.stop().catch(console.error);
        process.exitCode = 1;
      }
    });
    ready = true;
    console.log(`[playwright] Ready ${JSON.stringify(info)}`);
    return { endpoint: server.wsEndpoint(), healthPort: health.address().port, binaryPort: binary.port, info, stop };
  } catch (error) {
    await stop();
    throw error;
  }
}

if (require.main === module) {
  startServer().then(service => {
    for (const signal of ['SIGTERM', 'SIGINT']) {
      process.once(signal, () => service.stop().catch(error => { console.error(error); process.exitCode = 1; }));
    }
  }).catch(error => { console.error(`[playwright] Startup failed: ${error.stack}`); process.exitCode = 1; });
}

module.exports = { startServer };
