#!/usr/bin/env node
// Autorización OAuth de una sola vez. Pide SOLO permisos de lectura y escribe el refresh token en .env.
import http from 'node:http';
import { readFile, writeFile } from 'node:fs/promises';

const ENV = new URL('../.env', import.meta.url);
try { process.loadEnvFile(ENV); } catch { /* aún no existe */ }
const { GOOGLE_CLIENT_ID: id, GOOGLE_CLIENT_SECRET: secret } = process.env;
if (!id || !secret) {
  console.error('Primero pon GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en .env (ver README).');
  process.exit(1);
}

const PORT = 53682;
const redirect = `http://127.0.0.1:${PORT}/callback`;
const scopes = [
  'https://www.googleapis.com/auth/gmail.readonly',
  'https://www.googleapis.com/auth/calendar.readonly',
];
const url = 'https://accounts.google.com/o/oauth2/v2/auth?' + new URLSearchParams({
  client_id: id, redirect_uri: redirect, response_type: 'code',
  scope: scopes.join(' '), access_type: 'offline', prompt: 'consent',
});

console.log('Abre esta URL en el navegador y autoriza:\n\n' + url + '\n');

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, redirect);
  if (u.pathname !== '/callback') { res.writeHead(404).end(); return; }
  const code = u.searchParams.get('code');
  if (!code) { res.end('Sin código: ' + (u.searchParams.get('error') || '')); return; }
  const r = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ code, client_id: id, client_secret: secret, redirect_uri: redirect, grant_type: 'authorization_code' }),
  });
  const j = await r.json();
  if (!j.refresh_token) { res.end('Error: ' + JSON.stringify(j)); console.error(j); process.exit(1); }

  let env = '';
  try { env = await readFile(ENV, 'utf8'); } catch {}
  env = env.replace(/^GOOGLE_REFRESH_TOKEN=.*\n?/m, '');
  env = env.trimEnd() + `\nGOOGLE_REFRESH_TOKEN=${j.refresh_token}\n`;
  await writeFile(ENV, env, { mode: 0o600 });

  res.end('Listo. Ya puedes cerrar esta pestaña y ejecutar: npm run refresh');
  console.log('Refresh token guardado en .env');
  server.close();
});
server.listen(PORT, '127.0.0.1');
