// Cálculo puro: recibe hilos y eventos normalizados + config + "ahora" y devuelve el dashboard.
// No hace red ni lee archivos, para poder probarlo con datos de cualquier fuente.

const DAY = 86_400_000;

const lc = (s) => (s || '').toLowerCase();

/** Partes de fecha/hora de `date` vistas en la zona `tz`. */
function zonedParts(date, tz) {
  const f = new Intl.DateTimeFormat('en-US', {
    timeZone: tz, hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', weekday: 'short',
  });
  const p = Object.fromEntries(f.formatToParts(date).map((x) => [x.type, x.value]));
  return {
    y: +p.year, m: +p.month, d: +p.day, h: +p.hour, min: +p.minute, s: +p.second,
    wd: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(p.weekday),
  };
}

/** Instante UTC de la medianoche local (y,m,d) en `tz`. */
function midnightIn(tz, y, m, d) {
  const guess = Date.UTC(y, m - 1, d);
  const p = zonedParts(new Date(guess), tz);
  const offset = Date.UTC(p.y, p.m - 1, p.d, p.h, p.min, p.s) - guess; // local - UTC
  return new Date(guess - offset);
}

const localDayKey = (date, tz) => {
  const p = zonedParts(date, tz);
  return `${p.y}-${String(p.m).padStart(2, '0')}-${String(p.d).padStart(2, '0')}`;
};

const hhmm = (date, tz) => {
  const p = zonedParts(date, tz);
  return `${String(p.h).padStart(2, '0')}:${String(p.min).padStart(2, '0')}`;
};

function makeMatchers(cfg) {
  const mine = new Set(cfg.myEmails.map(lc));
  const vip = new Set((cfg.vipSenders || []).map(lc));
  const blocked = new Set((cfg.excludeSenders || []).map(lc));
  const senderRx = (cfg.excludeSenderPatterns || []).map((p) => new RegExp(p, 'i'));
  const subjRx = (cfg.excludeSubjectPatterns || []).map((p) => new RegExp(p, 'i'));
  const exclCats = new Set(cfg.excludeCategories || []);
  return {
    isMine: (e) => mine.has(lc(e)),
    isVip: (e) => vip.has(lc(e)),
    /** Devuelve el motivo de exclusión o null. Los VIP nunca se excluyen. */
    excludedBecause(t) {
      if (vip.has(lc(t.from))) return null;
      if (blocked.has(lc(t.from))) return 'remitente bloqueado';
      const cat = t.labels.find((l) => exclCats.has(l));
      if (cat) return `categoría ${cat.replace('CATEGORY_', '').toLowerCase()}`;
      if (senderRx.some((rx) => rx.test(t.from))) return 'remitente automático';
      if (subjRx.some((rx) => rx.test(t.subject || ''))) return 'asunto silenciado';
      return null;
    },
  };
}

function threadUrl(t, cfg) {
  if (t.url) return t.url;
  const user = encodeURIComponent(cfg.myEmails[0]);
  return `https://mail.google.com/mail/?authuser=${user}#all/${t.id}`;
}

function mailItem(t, cfg, now, m, extra = {}) {
  const at = new Date(t.date);
  return {
    threadId: t.id,
    from: t.fromName || t.from,
    fromEmail: t.from,
    subject: (t.subject || '(sin asunto)').trim(),
    date: t.date,
    ageDays: Math.floor((now - at) / DAY),
    unread: t.labels.includes('UNREAD'),
    vip: m.isVip(t.from),
    url: threadUrl(t, cfg),
    ...extra,
  };
}

function computeMail(threads, cfg, now) {
  const m = makeMatchers(cfg);
  const kw = cfg.actionKeywords.map(lc);
  const travelKw = cfg.travelKeywords.map(lc);
  const travelSenders = cfg.travelSenders.map(lc);
  const excludedTally = {};

  const action = [];
  const unanswered = [];
  const travelGroups = new Map();

  for (const t of threads) {
    const age = (now - new Date(t.date)) / DAY;
    const subj = lc(t.subject);
    const lastIsMine = m.isMine(t.from);
    const why = m.excludedBecause(t);

    // --- Viajes: no se filtra por "automático" (las aerolíneas escriben desde no-reply).
    if (age <= cfg.travelWindowDays && !lastIsMine) {
      const bySender = travelSenders.some((s) => lc(t.from).includes(s));
      const byKw = travelKw.find((k) => subj.includes(k));
      if (bySender || byKw) {
        // Agrupa alertas repetidas (ej. "precio de tu vuelo… COP 6,364k") quitando números.
        const key = `${lc(t.from)}|${subj.replace(/[\d.,]+k?/g, '#')}`;
        const g = travelGroups.get(key);
        if (!g || new Date(t.date) > new Date(g.date)) {
          travelGroups.set(key, mailItem(t, cfg, now, m, { count: (g?.count || 0) + 1 }));
        } else {
          g.count += 1;
        }
      }
    }

    if (why) {
      excludedTally[why] = (excludedTally[why] || 0) + 1;
      continue;
    }
    if (lastIsMine) continue;

    // --- Piden acción: no leído o palabra clave, últimos N días.
    if (age <= cfg.actionWindowDays) {
      const reasons = [];
      if (t.labels.includes('UNREAD')) reasons.push('no leído');
      const hit = kw.filter((k) => subj.includes(k));
      if (hit.length) reasons.push(...hit);
      else if (cfg.actionMatchBody && t.hits?.includes('action') && !reasons.length) reasons.push('palabra clave en el cuerpo');
      if (reasons.length) action.push(mailItem(t, cfg, now, m, { reasons }));
    }

    // --- Sin respuesta: el último mensaje no es mío, en bandeja, > N días.
    if (t.labels.includes('INBOX') && age > cfg.unansweredMinDays && age <= cfg.unansweredWindowDays) {
      const direct = (t.to || []).some(m.isMine);
      if (!cfg.unansweredOnlyIfDirect || direct) {
        unanswered.push(mailItem(t, cfg, now, m));
      }
    }
  }

  const byVipThenDate = (a, b) => (b.vip - a.vip) || (new Date(b.date) - new Date(a.date));
  action.sort(byVipThenDate);
  unanswered.sort((a, b) => (b.vip - a.vip) || (b.ageDays - a.ageDays));
  const travel = [...travelGroups.values()].sort((a, b) => new Date(b.date) - new Date(a.date));

  return { action, unanswered, travel, excludedTally };
}

function computeCalendar(events, cfg, now) {
  const tz = cfg.timezone;
  const p = zonedParts(now, tz);
  const todayStart = midnightIn(tz, p.y, p.m, p.d);
  const mondayOffset = (p.wd + 6) % 7;
  const weekStart = new Date(todayStart - mondayOffset * DAY);
  const weekEnd = new Date(weekStart.getTime() + 7 * DAY);
  const todayKey = localDayKey(now, tz);

  const evs = events
    .filter((e) => e.selfStatus !== 'declined')
    .map((e) => {
      const start = new Date(e.start);
      const end = new Date(e.end);
      return {
        id: e.id,
        title: e.title || '(sin título)',
        start: e.start,
        end: e.end,
        allDay: !!e.allDay,
        startLocal: e.allDay ? 'Todo el día' : hhmm(start, tz),
        endLocal: e.allDay ? '' : hhmm(end, tz),
        day: localDayKey(start, tz),
        location: e.location || '',
        attendees: (e.attendees || [])
          .filter((a) => !cfg.myEmails.map(lc).includes(lc(a.email)))
          .map((a) => a.name || a.email),
        url: e.url,
        _s: start, _e: end,
      };
    })
    .filter((e) => e._e > weekStart && e._s < weekEnd)
    .sort((a, b) => a._s - b._s);

  // Choques: pares de eventos con hora (no "todo el día") que se cruzan.
  const conflicts = [];
  const timed = evs.filter((e) => !e.allDay);
  for (let i = 0; i < timed.length; i++) {
    for (let j = i + 1; j < timed.length; j++) {
      const a = timed[i], b = timed[j];
      if (b._s >= a._e) continue;
      if (a._s < b._e && b._s < a._e) {
        const at = new Date(Math.max(a._s, b._s));
        conflicts.push({ at: at.toISOString(), atLocal: hhmm(at, tz), day: localDayKey(at, tz), a: a.title, b: b.title, ids: [a.id, b.id] });
      }
    }
  }
  const conflictIds = new Set(conflicts.flatMap((c) => c.ids));
  const next = timed.find((e) => e._s > now) || null;

  const clean = (e) => {
    const { _s, _e, ...rest } = e;
    return { ...rest, conflict: conflictIds.has(e.id), past: _e <= now };
  };

  return {
    weekStart: localDayKey(weekStart, tz),
    today: evs.filter((e) => e.day === todayKey).map(clean),
    week: evs.map(clean),
    conflicts,
    next: next ? clean(next) : null,
  };
}

function greeting(now, tz) {
  const h = zonedParts(now, tz).h;
  if (h < 12) return 'Buen día';
  if (h < 19) return 'Buenas tardes';
  return 'Buenas noches';
}

function plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

export function buildDashboard({ threads, events, source, partial }, cfg, now = new Date()) {
  const mail = computeMail(threads, cfg, now);
  const cal = computeCalendar(events, cfg, now);
  const todayConflicts = cal.conflicts.filter((c) => c.day === localDayKey(now, cfg.timezone));

  const parts = [
    plural(cal.today.length, 'reunión', 'reuniones'),
    `${plural(mail.action.length, 'correo que pide', 'correos que piden')} acción`,
    `${mail.unanswered.length} sin respuesta`,
  ];
  if (todayConflicts.length === 1) parts.push(`un choque de agenda a las ${todayConflicts[0].atLocal}`);
  else if (todayConflicts.length > 1) parts.push(`${todayConflicts.length} choques de agenda (el primero a las ${todayConflicts[0].atLocal})`);
  let summary = `Hoy tienes ${parts.slice(0, -1).join(', ')} y ${parts.at(-1)}`;
  summary += '.';

  return {
    generatedAt: now.toISOString(),
    source,
    partial: !!partial,
    timezone: cfg.timezone,
    name: cfg.name,
    greeting: `${greeting(now, cfg.timezone)}, ${cfg.name}`,
    summary,
    kpis: {
      meetingsToday: cal.today.length,
      meetingsWeek: cal.week.length,
      unanswered: mail.unanswered.length,
      urgent: mail.action.length,
      travel: mail.travel.length,
      conflicts: cal.conflicts.length,
      nextEvent: cal.next ? { title: cal.next.title, startLocal: cal.next.startLocal, day: cal.next.day, url: cal.next.url } : null,
    },
    calendar: cal,
    mail: {
      action: mail.action,
      unanswered: mail.unanswered,
      travel: mail.travel,
    },
    diagnostics: {
      threadsSeen: threads.length,
      eventsSeen: events.length,
      excluded: mail.excludedTally,
    },
  };
}
