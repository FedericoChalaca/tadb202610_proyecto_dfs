#!/usr/bin/env node
// Lee Gmail + Google Calendar (SOLO LECTURA) y escribe data/dashboard.json.
//
//   node fetch_data.js                 -> usa la API de Google (credenciales en .env)
//   node fetch_data.js --from-raw F    -> usa un volcado normalizado (data/raw.json)
//
// Nunca guarda el cuerpo de los correos: solo remitente, destinatarios, asunto, fecha, etiquetas e ID.

import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { buildDashboard } from './src/compute.js';

const ROOT = new URL('.', import.meta.url);
const DAY = 86_400_000;

const args = process.argv.slice(2);
const rawIdx = args.indexOf('--from-raw');
const rawPath = rawIdx >= 0 ? args[rawIdx + 1] : null;
const quiet = args.includes('--quiet');

let cfg;
try {
  cfg = JSON.parse(await readFile(new URL('config.json', ROOT), 'utf8'));
} catch (e) {
  if (e.code !== 'ENOENT') throw e;
  console.error('Falta config.json. Cópialo desde config.example.json y pon tus datos.');
  process.exit(1);
}

// ---------------------------------------------------------------- Google API

async function accessToken() {
  try { process.loadEnvFile(new URL('.env', ROOT)); } catch { /* sin .env */ }
  const { GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN } = process.env;
  if (!GOOGLE_CLIENT_ID || !GOOGLE_CLIENT_SECRET || !GOOGLE_REFRESH_TOKEN) {
    throw new Error('Faltan GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN en .env. Ejecuta: npm run auth');
  }
  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: GOOGLE_CLIENT_ID,
      client_secret: GOOGLE_CLIENT_SECRET,
      refresh_token: GOOGLE_REFRESH_TOKEN,
      grant_type: 'refresh_token',
    }),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(`OAuth: ${json.error} ${json.error_description || ''}`.trim());
  return json.access_token;
}

async function api(token, url) {
  for (let attempt = 0; attempt < 4; attempt++) {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (res.status === 429 || res.status >= 500) {
      await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
      continue;
    }
    const json = await res.json();
    if (!res.ok) throw new Error(`${res.status} ${url.split('?')[0]}: ${json.error?.message}`);
    return json;
  }
  throw new Error(`Demasiados reintentos: ${url.split('?')[0]}`);
}

const parseAddr = (v = '') => {
  const m = v.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
  return m ? { name: m[1].trim(), email: m[2].trim() } : { name: '', email: v.trim() };
};
const parseList = (v = '') => v.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/).map(parseAddr).map((a) => a.email).filter(Boolean);

async function listThreadIds(token, q, max) {
  const ids = [];
  let pageToken;
  do {
    const u = new URL('https://gmail.googleapis.com/gmail/v1/users/me/threads');
    u.searchParams.set('q', q);
    u.searchParams.set('maxResults', String(Math.min(100, max - ids.length)));
    if (pageToken) u.searchParams.set('pageToken', pageToken);
    const r = await api(token, u);
    ids.push(...(r.threads || []).map((t) => t.id));
    pageToken = r.nextPageToken;
  } while (pageToken && ids.length < max);
  return { ids, truncated: !!pageToken };
}

async function getThread(token, id) {
  const u = new URL(`https://gmail.googleapis.com/gmail/v1/users/me/threads/${id}`);
  u.searchParams.set('format', 'metadata');
  for (const h of ['From', 'To', 'Cc', 'Subject']) u.searchParams.append('metadataHeaders', h);
  const t = await api(token, u);
  const msgs = (t.messages || []).filter((x) => !(x.labelIds || []).includes('DRAFT'));
  const last = msgs.at(-1);
  const H = Object.fromEntries((last.payload?.headers || []).map((h) => [h.name.toLowerCase(), h.value]));
  const from = parseAddr(H.from);
  const labels = new Set(last.labelIds || []);
  if (msgs.some((x) => (x.labelIds || []).includes('UNREAD'))) labels.add('UNREAD');
  if (msgs.some((x) => (x.labelIds || []).includes('INBOX'))) labels.add('INBOX');
  return {
    id: t.id,
    labels: [...labels],
    from: from.email,
    fromName: from.name,
    to: parseList(H.to),
    cc: parseList(H.cc),
    date: new Date(Number(last.internalDate)).toISOString(),
    subject: H.subject || '',
    count: msgs.length,
  };
}

async function pool(items, n, fn) {
  const out = new Array(items.length);
  let i = 0;
  await Promise.all(Array.from({ length: n }, async () => {
    while (i < items.length) { const k = i++; out[k] = await fn(items[k]); }
  }));
  return out;
}

async function fromGoogle() {
  const token = await accessToken();
  const quote = (k) => (/[\s-]/.test(k) ? `"${k}"` : k);
  const noise = '-category:promotions -category:social';
  const queries = {
    action: `newer_than:${cfg.actionWindowDays}d -in:sent ${noise} (is:unread OR ${cfg.actionKeywords.map(quote).join(' OR ')})`,
    unanswered: `in:inbox newer_than:${cfg.unansweredWindowDays}d older_than:${cfg.unansweredMinDays}d ${noise}`,
    travel: `newer_than:${cfg.travelWindowDays}d ${noise} (category:reservations OR ${cfg.travelKeywords.map(quote).join(' OR ')})`,
  };

  const hits = new Map();
  let partial = false;
  for (const [name, q] of Object.entries(queries)) {
    const { ids, truncated } = await listThreadIds(token, q, cfg.maxThreadsPerQuery);
    if (truncated) partial = true;
    for (const id of ids) hits.set(id, [...(hits.get(id) || []), name]);
    if (!quiet) console.log(`  gmail ${name.padEnd(10)} ${ids.length} hilos${truncated ? ' (truncado)' : ''}`);
  }
  const threads = (await pool([...hits.keys()], 8, (id) => getThread(token, id)))
    .map((t) => ({ ...t, hits: hits.get(t.id) }));

  // Semana local (lunes a domingo) con margen de un día a cada lado.
  const now = Date.now();
  const cu = new URL('https://www.googleapis.com/calendar/v3/calendars/primary/events');
  cu.searchParams.set('timeMin', new Date(now - 8 * DAY).toISOString());
  cu.searchParams.set('timeMax', new Date(now + 8 * DAY).toISOString());
  cu.searchParams.set('singleEvents', 'true');
  cu.searchParams.set('orderBy', 'startTime');
  cu.searchParams.set('maxResults', '250');
  const cal = await api(token, cu);
  const events = (cal.items || [])
    .filter((e) => e.status !== 'cancelled')
    .map((e) => ({
      id: e.id,
      title: e.summary,
      start: e.start.dateTime || `${e.start.date}T00:00:00`,
      end: e.end.dateTime || `${e.end.date}T00:00:00`,
      allDay: !e.start.dateTime,
      location: e.location || '',
      attendees: (e.attendees || []).filter((a) => !a.self && !a.resource)
        .map((a) => ({ email: a.email, name: a.displayName || '', status: a.responseStatus })),
      selfStatus: (e.attendees || []).find((a) => a.self)?.responseStatus || 'accepted',
      url: e.htmlLink,
    }));
  if (!quiet) console.log(`  calendar   ${events.length} eventos`);
  return { threads, events, source: 'google-api', partial };
}

// ---------------------------------------------------------------- main

const input = rawPath
  ? { ...JSON.parse(await readFile(rawPath, 'utf8')), source: 'raw:' + rawPath, partial: true }
  : await fromGoogle();

const dash = buildDashboard(input, cfg);
await mkdir(new URL('data/', ROOT), { recursive: true });
await writeFile(new URL('data/dashboard.json', ROOT), JSON.stringify(dash, null, 2));
// Copia como script para que index.html funcione abierto con doble clic (file://), donde fetch() está bloqueado.
await writeFile(new URL('data/dashboard.js', ROOT), `window.DASHBOARD = ${JSON.stringify(dash).replace(/</g, '\\u003c')};\n`);

if (!quiet) {
  const k = dash.kpis;
  console.log(`\n${dash.greeting}. ${dash.summary}`);
  console.log(`KPIs → semana: ${k.meetingsWeek} reuniones · sin contestar: ${k.unanswered} · urgentes: ${k.urgent} · viajes: ${k.travel} · choques: ${k.conflicts}`);
  console.log(`Próximo: ${k.nextEvent ? `${k.nextEvent.day} ${k.nextEvent.startLocal} — ${k.nextEvent.title}` : '—'}`);
  console.log(`Excluidos: ${JSON.stringify(dash.diagnostics.excluded)}`);
  console.log('→ data/dashboard.json');
}
