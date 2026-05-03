// Concerto UI + API proxy server — standalone, no dependencies
// Usage: node serve.mjs
import { createServer } from 'http';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = 3901;
const MAESTRO_API = 'http://127.0.0.1:3900'; // plugin API for read endpoints

const server = createServer((req, res) => {
  handleRequest(req, res).catch(e => {
    console.error('[Concerto] Unhandled error:', e.message);
    if (!res.headersSent) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
  });
});

async function handleRequest(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204); res.end(); return;
  }

  const url = req.url ?? '/';

  // ---- Proxy GET /api/* to the plugin API on 3900 ----
  if (url.startsWith('/api/') && req.method === 'GET') {
    try {
      const r = await fetch(`${MAESTRO_API}${url}`);
      res.writeHead(r.status, { 'Content-Type': r.headers.get('content-type') || 'application/json' });
      // For SSE, pipe the stream
      if (r.headers.get('content-type')?.includes('text/event-stream')) {
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        const reader = r.body.getReader();
        const pump = async () => {
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) { res.end(); return; }
              res.write(value);
            }
          } catch { res.end(); }
        };
        pump();
        req.on('close', () => reader.cancel());
        return;
      }
      res.end(await r.text());
    } catch (e) {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }

  // ---- POST /api/send — proxy send to agent endpoint (avoids browser CORS) ----
  if (url === '/api/send' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', async () => {
      try {
        const { endpoint, message } = JSON.parse(body);
        if (!endpoint || !message) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ ok: false, error: 'Missing endpoint or message' }));
          return;
        }
        const r = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(message),
          signal: AbortSignal.timeout(5000),
        });
        const result = await r.json().catch(() => ({}));
        res.writeHead(r.status, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(result));
      } catch (e) {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: e.message }));
      }
    });
    return;
  }

  // ---- Serve UI HTML ----
  if (req.method === 'GET') {
    try {
      const html = readFileSync(join(__dirname, 'index.html'), 'utf8');
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(html);
    } catch (e) {
      res.writeHead(500);
      res.end('Error: ' + e.message);
    }
    return;
  }

  res.writeHead(404);
  res.end('Not found');
}

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Concerto UI + proxy: http://127.0.0.1:${PORT}`);
});
