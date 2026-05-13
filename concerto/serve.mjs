// Concerto UI + send proxy — standalone, no external dependencies
// Usage: node serve.mjs
import { createServer } from 'http';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = 3901;

// Catch-all for unhandled promise rejections so the server never crashes
process.on('unhandledRejection', (err) => {
  console.error('[Concerto] Unhandled rejection (ignored):', err?.message ?? err);
});

const server = createServer((req, res) => {
  const url = req.url ?? '/';

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204); res.end(); return;
  }

  // POST /api/send — proxy a message to an agent transport endpoint
  // Avoids browser CORS when posting from localhost:3901 to localhost:384x
  if (url === '/api/send' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      (async () => {
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
          if (!res.headersSent) {
            res.writeHead(502, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ ok: false, error: e.message }));
          }
        }
      })();
    });
    return;
  }

  // GET — serve the UI HTML
  if (req.method === 'GET') {
    try {
      const html = readFileSync(join(__dirname, 'index.html'), 'utf8');
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(html);
    } catch (e) {
      res.writeHead(500);
      res.end('Error loading UI: ' + e.message);
    }
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

server.on('error', (err) => {
  console.error('[Concerto] Server error:', err.message);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Concerto UI: http://127.0.0.1:${PORT}`);
});
