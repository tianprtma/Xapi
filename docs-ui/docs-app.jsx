/* global React */
// DocsApp — three-pane API reference prototype. Rendered twice on the canvas
// with `variant="terminal"` and `variant="console"` to compare treatments.

const { useState, useMemo, useEffect, useRef } = React;
const DATA = window.XDOC_DATA;

// ── small helpers ────────────────────────────────────────────────────────────
const cn = (...xs) => xs.filter(Boolean).join(' ');

function useCopy() {
  const [copied, setCopied] = useState(false);
  return [copied, (text) => {
    try { navigator.clipboard.writeText(text); } catch {}
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }];
}

// Method pill / colors
const METHOD_HUE = { GET: 195, POST: 145, DEL: 12, PUT: 50, PATCH: 280 };
function MethodPill({ method, size = 'md' }) {
  const m = (method || 'GET').toUpperCase().slice(0, 4);
  const hue = METHOD_HUE[m] ?? 200;
  return (
    <span className={cn('method-pill', `method-pill-${size}`)}
      style={{ '--mh': hue }}>{m}</span>
  );
}

// ── Topbar ───────────────────────────────────────────────────────────────────
function Topbar({ variant, onSearch, onToggleTheme, theme, query }) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        {variant === 'terminal' ? (
          <div className="brand brand-terminal">
            <span className="brand-glyph">▮</span>
            <span className="brand-name">xapi</span>
            <span className="brand-tag">(cookie auth)</span>
          </div>
        ) : (
          <div className="brand brand-console">
            <span className="brand-mark">𝕏</span>
            <div className="brand-stack">
              <span className="brand-name">Xapi</span>
              <span className="brand-tag">X v2 mirror · cookie auth_token · v2.3.0</span>
            </div>
          </div>
        )}
      </div>

      <div className="topbar-search">
        <span className="topbar-search-prefix">{variant === 'terminal' ? '$' : '⌕'}</span>
        <input
          className="topbar-search-input"
          placeholder={variant === 'terminal' ? 'grep endpoints…' : 'Search endpoints, fields, errors…'}
          value={query}
          onChange={(e) => onSearch(e.target.value)}
          spellCheck={false}
        />
        <kbd className="topbar-kbd">⌘ K</kbd>
      </div>

      <div className="topbar-right">
        <button className="topbar-btn" onClick={onToggleTheme} title="Toggle theme">
          {theme === 'dark' ? '◐' : '◑'}
        </button>
        <a className="topbar-link" href="#">Status</a>
        <a className="topbar-link" href="#">Changelog</a>
        <button className="topbar-cta">Get a token <span>↗</span></button>
      </div>
    </header>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ variant, sidebarVariant, query, current, onSelect, openMap, onToggleSection }) {
  const q = query.trim().toLowerCase();
  const sections = useMemo(() => {
    if (!q) return DATA.sections;
    return DATA.sections.map((s) => ({
      ...s,
      items: s.items.filter((it) =>
        it.label.toLowerCase().includes(q) ||
        (it.path || '').toLowerCase().includes(q) ||
        (it.method || '').toLowerCase().includes(q))
    })).filter((s) => s.items.length);
  }, [q]);

  const compact = sidebarVariant === 'compact';
  const flat = sidebarVariant === 'flat';

  return (
    <aside className={cn('sidebar', `sidebar-${sidebarVariant}`)}>
      {!compact && (
        <div className="sidebar-stat-row">
          <span className="sidebar-stat-dot" />
          <span className="sidebar-stat-label">api · production</span>
          <span className="sidebar-stat-value">99.98% / 30d</span>
        </div>
      )}

      <nav className="sidebar-nav">
        {sections.map((sec) => {
          const open = openMap[sec.id] !== false;
          return (
            <div key={sec.id} className="sidebar-section">
              {!flat && (
                <button
                  className={cn('sidebar-section-head', open && 'is-open')}
                  onClick={() => onToggleSection(sec.id)}
                >
                  {variant === 'terminal' ? (
                    <span className="sidebar-icon">{open ? '─' : '+'}</span>
                  ) : (
                    <span className={cn('sidebar-caret', open && 'is-open')}>›</span>
                  )}
                  <span className="sidebar-section-label">{sec.label}</span>
                  <span className="sidebar-section-count">{sec.items.length}</span>
                </button>
              )}
              {(flat || open) && (
                <ul className="sidebar-items">
                  {sec.items.map((it) => (
                    <li key={it.id}>
                      <button
                        className={cn('sidebar-item', current === it.id && 'is-current')}
                        onClick={() => onSelect(it.id)}
                      >
                        {it.method ? (
                          <span className="sidebar-item-method">
                            <MethodPill method={it.method} size="sm" />
                          </span>
                        ) : (
                          <span className="sidebar-item-bullet">{variant === 'terminal' ? '·' : '•'}</span>
                        )}
                        <span className="sidebar-item-label">{it.label}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
        {!sections.length && (
          <div className="sidebar-empty">
            <span className="sidebar-empty-glyph">∅</span>
            <span>No endpoints match “{q}”.</span>
          </div>
        )}
      </nav>

      <div className="sidebar-foot">
        <div className="sidebar-foot-row">
          <span className="sidebar-foot-dim">env</span>
          <span>{DATA.base.replace(/^https?:\/\//, '')}</span>
        </div>
        <div className="sidebar-foot-row">
          <span className="sidebar-foot-dim">build</span>
          <span>2.3.0 · fastapi</span>
        </div>
      </div>
    </aside>
  );
}

// ── Main content ─────────────────────────────────────────────────────────────
function MainContent({ variant, currentId, heroStyle, onSelect }) {
  const item = lookupItem(currentId);
  const ep = DATA.endpoints[currentId];

  if (currentId === 'overview' || !item) {
    return <OverviewPage variant={variant} heroStyle={heroStyle} onSelect={onSelect} />;
  }
  if (item.kind === 'page') {
    return <StubPage variant={variant} item={item} />;
  }
  if (ep) {
    return <EndpointPage variant={variant} ep={ep} item={item} />;
  }
  // sidebar item with method/path but no detailed definition
  return <EndpointStub variant={variant} item={item} />;
}

function lookupItem(id) {
  for (const sec of DATA.sections) {
    for (const it of sec.items) if (it.id === id) return it;
  }
  return null;
}

function Crumbs({ items }) {
  return (
    <div className="crumbs">
      {items.map((c, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="crumbs-sep">/</span>}
          <span className={i === items.length - 1 ? 'crumbs-current' : 'crumbs-link'}>{c}</span>
        </React.Fragment>
      ))}
    </div>
  );
}

// ── Overview / landing ───────────────────────────────────────────────────────
function OverviewPage({ variant, heroStyle, onSelect }) {
  return (
    <div className="page page-overview">
      <Crumbs items={['docs', 'overview']} />
      <Hero variant={variant} heroStyle={heroStyle} />

      <Section title="Quickstart" subtitle="Mirror X v2 dengan cookie auth_token. Setup di bawah 60 detik.">
        <div className="quick-grid">
          <QuickCard step="01" title="Ambil auth_token" body="Login ke x.com di browser. DevTools → Application → Cookies → salin nilai cookie `auth_token`.">
            <code className="quick-code">export AUTH_TOKEN="abc123…"</code>
          </QuickCard>
          <QuickCard step="02" title="Kirim Authorization" body="Pakai bearer header atau query string `?auth_token=` di setiap call.">
            <code className="quick-code">Authorization: Bearer $AUTH_TOKEN</code>
          </QuickCard>
          <QuickCard step="03" title="Validasi token" body="GET /login untuk pastikan cookie masih hidup. Return profile + screen_name.">
            <code className="quick-code">GET /login → 200 valid</code>
          </QuickCard>
        </div>
      </Section>

      <Section title="Resource families" subtitle="13 surfaces dari mirror v2. Klik card untuk masuk ke endpoint pertama.">
        <div className="ep-grid">
          {DATA.sections.filter((s) => s.id !== 'start' && s.id !== 'meta').map((s) => (
            <button key={s.id} className="ep-card" onClick={() => onSelect(s.items[0].id)}>
              <div className="ep-card-head">
                <span className="ep-card-icon">{s.icon}</span>
                <span className="ep-card-title">{s.label}</span>
                <span className="ep-card-count">{s.items.length}</span>
              </div>
              <ul className="ep-card-list">
                {s.items.slice(0, 4).map((it) => (
                  <li key={it.id}>
                    {it.method && <MethodPill method={it.method} size="sm" />}
                    <span className="ep-card-list-label">{it.label}</span>
                  </li>
                ))}
              </ul>
            </button>
          ))}
        </div>
      </Section>

      <Section title="Conventions" subtitle="Hal-hal yang berlaku di seluruh API.">
        <div className="conv-grid">
          <ConvRow k="Base URL" v={DATA.base} />
          <ConvRow k="Auth" v="Authorization: Bearer <auth_token>  ·  ?auth_token=…" />
          <ConvRow k="Schema" v="REST + JSON · UTF-8 · ISO-8601 timestamps" />
          <ConvRow k="Raw payload" v="?raw=1 → bypass formatter v2 (disable di prod via ENABLE_RAW=0)" />
          <ConvRow k="Pagination" v="Cursor via meta.next_token / pagination_token" />
          <ConvRow k="Errors" v="problem+json on 4xx/5xx · 401 = invalid token · 502 = upstream" />
          <ConvRow k="Engine" v="GraphQL (httpx) + Playwright fallback untuk CF-gated routes" />
        </div>
      </Section>
    </div>
  );
}

function Hero({ variant, heroStyle }) {
  if (heroStyle === 'banner') return <HeroBanner variant={variant} />;
  if (heroStyle === 'status') return <HeroStatus variant={variant} />;
  return <HeroPrompt variant={variant} />;
}

function HeroPrompt({ variant }) {
  const base = DATA.base.replace(/^https?:\/\//, '');
  return (
    <div className="hero hero-prompt">
      <div className="hero-eyebrow">
        <span className="hero-dot" /> Xapi · cookie-auth mirror
      </div>
      <h1 className="hero-title">
        X API v2, powered by<br />your auth_token cookie.
      </h1>
      <p className="hero-sub">
        FastAPI mirror of X API v2 — backed by GraphQL via httpx and Playwright fallback for CF-gated endpoints. No OAuth2, no dev portal.
      </p>
      <div className="hero-prompt-line">
        <span className="hero-prompt-prefix">$</span>
        <span className="hero-prompt-cmd">curl -H "Authorization: Bearer $AUTH_TOKEN" {base}/2/users/me</span>
        <span className="hero-cursor" />
      </div>
      <div className="hero-meta">
        <span><b>13</b> resource families</span>
        <span><b>3</b> example languages</span>
        <span><b>0</b> dev portal apps</span>
        <span className="hero-meta-last">base · {DATA.base}</span>
      </div>
    </div>
  );
}

function HeroBanner({ variant }) {
  const ascii = [
    "╔══════════════════════════════════════════════════════════════════╗",
    "║   X · A · P · I · — · C · O · O · K · I · E · — · A · U · T · H ║",
    "╚══════════════════════════════════════════════════════════════════╝",
  ];
  return (
    <div className="hero hero-banner">
      <pre className="hero-ascii">{ascii.join('\n')}</pre>
      <h1 className="hero-title hero-title-banner">FastAPI mirror of X API v2.</h1>
      <p className="hero-sub">Drop in your `auth_token` cookie. Get back v2-shaped JSON. GraphQL under the hood, Playwright when needed.</p>
    </div>
  );
}

function HeroStatus({ variant }) {
  const cells = [
    { l: 'uptime · 30d', v: '99.98%', s: 'ok' },
    { l: 'p50 latency', v: '184 ms', s: 'ok' },
    { l: 'p99 latency', v: '912 ms', s: 'warn' },
    { l: 'last incident', v: '14 d ago', s: 'ok' },
    { l: 'tokens active', v: '12,841', s: 'ok' },
    { l: 'rate of 5xx', v: '0.04%', s: 'ok' },
  ];
  return (
    <div className="hero hero-status">
      <div className="hero-status-head">
        <h1 className="hero-title">X API · v2 · unofficial reference</h1>
        <p className="hero-sub">Live numbers from the public health endpoint. The reference below mirrors what the production system actually accepts today.</p>
      </div>
      <div className="hero-status-grid">
        {cells.map((c) => (
          <div key={c.l} className={cn('hero-status-cell', `is-${c.s}`)}>
            <div className="hero-status-label">{c.l}</div>
            <div className="hero-status-val">{c.v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Section({ title, subtitle, children, kicker }) {
  return (
    <section className="content-section">
      <header className="content-section-head">
        {kicker && <div className="content-section-kicker">{kicker}</div>}
        <h2 className="content-section-title">{title}</h2>
        {subtitle && <p className="content-section-sub">{subtitle}</p>}
      </header>
      {children}
    </section>
  );
}

function QuickCard({ step, title, body, children }) {
  return (
    <div className="quick-card">
      <div className="quick-step">{step}</div>
      <div className="quick-title">{title}</div>
      <div className="quick-body">{body}</div>
      <div className="quick-cmd">{children}</div>
    </div>
  );
}

function ConvRow({ k, v }) {
  return (
    <div className="conv-row">
      <div className="conv-k">{k}</div>
      <div className="conv-v">{v}</div>
    </div>
  );
}

// ── Endpoint page ────────────────────────────────────────────────────────────
function EndpointPage({ variant, ep, item }) {
  const allParams = [
    ...(ep.params || []),
    ...((ep.body || []).map((b) => ({ ...b, loc: 'body' }))),
  ];
  const pathP = allParams.filter((p) => p.loc === 'path');
  const queryP = allParams.filter((p) => p.loc === 'query');
  const bodyP = allParams.filter((p) => p.loc === 'body');

  return (
    <div className="page page-endpoint">
      <Crumbs items={['docs', sectionLabelFor(item.id), ep.name]} />

      <div className="ep-head">
        <div className="ep-head-route">
          <MethodPill method={ep.method} size="lg" />
          <code className="ep-head-path">{ep.path}</code>
        </div>
        <h1 className="ep-head-title">{ep.name}</h1>
        <p className="ep-head-summary">{ep.summary}</p>
        <div className="ep-head-meta">
          <span className="ep-meta-chip"><span className="ep-meta-k">auth</span>{ep.auth}</span>
          <span className="ep-meta-chip"><span className="ep-meta-k">scopes</span>
            {ep.scope.map((s) => <code key={s} className="ep-meta-scope">{s}</code>)}
          </span>
        </div>
      </div>

      {pathP.length > 0 && (
        <ParamTable variant={variant} title="Path parameters" rows={pathP} />
      )}
      {queryP.length > 0 && (
        <ParamTable variant={variant} title="Query parameters" rows={queryP} />
      )}
      {bodyP.length > 0 && (
        <ParamTable variant={variant} title="Request body" rows={bodyP} />
      )}

      <ResponsesBlock variant={variant} responses={ep.responses} />

      <Section title="Notes">
        <ul className="notes-list">
          <li>All requests must be made over HTTPS. Plain HTTP is rejected at the edge.</li>
          <li>Responses are gzip-encoded when <code>Accept-Encoding: gzip</code> is sent.</li>
          <li>Server time is UTC. Clients should send local time only in user-controlled fields.</li>
        </ul>
      </Section>
    </div>
  );
}

function sectionLabelFor(id) {
  for (const sec of DATA.sections) {
    if (sec.items.some((it) => it.id === id)) return sec.label;
  }
  return '';
}

function ParamTable({ variant, title, rows }) {
  return (
    <section className="content-section">
      <h3 className="param-title">{title}</h3>
      <div className="param-table">
        <div className="param-row param-row-head">
          <div>name</div><div>type</div><div>req</div><div>description</div>
        </div>
        {rows.map((r) => (
          <div key={r.name} className="param-row">
            <div className="param-name"><code>{r.name}</code></div>
            <div className="param-type"><code>{r.type}</code></div>
            <div className="param-req">{r.required ? <span className="req-yes">required</span> : <span className="req-no">optional</span>}</div>
            <div className="param-desc">{r.desc}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ResponsesBlock({ variant, responses }) {
  const [active, setActive] = useState(0);
  const r = responses[active];
  return (
    <section className="content-section">
      <h3 className="param-title">Responses</h3>
      <div className="resp-tabs">
        {responses.map((rs, i) => (
          <button
            key={rs.code}
            className={cn('resp-tab', `resp-tab-${statusClass(rs.code)}`, i === active && 'is-active')}
            onClick={() => setActive(i)}
          >
            <span className="resp-tab-code">{rs.code}</span>
            <span className="resp-tab-label">{rs.label}</span>
          </button>
        ))}
      </div>
      <pre className="resp-body"><code>{r.body}</code></pre>
    </section>
  );
}

function statusClass(code) {
  if (code < 300) return 'ok';
  if (code < 400) return 'redir';
  if (code < 500) return 'client';
  return 'server';
}

// Stub for sidebar items that have a method but no detailed def
function EndpointStub({ variant, item }) {
  return (
    <div className="page page-endpoint">
      <Crumbs items={['docs', sectionLabelFor(item.id), item.label]} />
      <div className="ep-head">
        <div className="ep-head-route">
          <MethodPill method={item.method} size="lg" />
          <code className="ep-head-path">{item.path}</code>
        </div>
        <h1 className="ep-head-title">{item.label}</h1>
        <p className="ep-head-summary">Documented surface. Full reference is on the working tree — pick another endpoint from the sidebar to see the format in detail.</p>
      </div>
      <div className="stub-note">
        <div className="stub-note-line">$ open <code>{item.path}</code></div>
        <div className="stub-note-line stub-note-dim">// table of parameters, response schema and language-specific examples render here</div>
        <div className="stub-note-line stub-note-dim">// referenced by the right pane and the try-it console</div>
      </div>
    </div>
  );
}

function StubPage({ variant, item }) {
  const page = (DATA.pages || {})[item.id];
  if (!page) {
    return (
      <div className="page page-stub">
        <Crumbs items={['docs', item.label]} />
        <h1 className="ep-head-title" style={{ marginTop: 8 }}>{item.label}</h1>
        <p className="ep-head-summary">A reference page for <code>{item.label.toLowerCase()}</code>. Pick an endpoint from the sidebar to see the live format.</p>
      </div>
    );
  }
  return (
    <div className="page page-stub">
      <Crumbs items={['docs', page.title]} />
      <div className="ep-head">
        <h1 className="ep-head-title">{page.title}</h1>
        {page.lead && <p className="ep-head-summary">{page.lead}</p>}
      </div>
      {page.sections.map((s, i) => (
        <Section key={i} kicker={s.kicker} title={s.title}>
          {s.body && <p className="content-section-sub" style={{ marginBottom: s.code ? 12 : 0 }}>{s.body}</p>}
          {s.code && <pre className="resp-body"><code>{s.code}</code></pre>}
        </Section>
      ))}
    </div>
  );
}

// ── Right pane — code / response / try-it ────────────────────────────────────
const LANGS = [
  { id: 'curl', label: 'cURL' },
  { id: 'javascript', label: 'JavaScript' },
  { id: 'python', label: 'Python' },
];

function CodePane({ variant, currentId, codeTheme }) {
  const ep = DATA.endpoints[currentId];
  const [tab, setTab] = useState('request');
  const [lang, setLang] = useState('curl');

  // reset tab to request when navigating endpoints
  useEffect(() => { setTab('request'); setLang('curl'); }, [currentId]);

  if (!ep) {
    return <CodePaneIdle variant={variant} />;
  }

  return (
    <div className={cn('codepane', `codetheme-${codeTheme}`)}>
      <div className="codepane-head">
        <div className="codepane-tabs">
          {['request', 'response', 'headers', 'try'].map((t) => (
            <button key={t}
              className={cn('codepane-tab', tab === t && 'is-active')}
              onClick={() => setTab(t)}
            >
              {t === 'try' ? 'try it' : t}
            </button>
          ))}
        </div>
        <div className="codepane-route">
          <MethodPill method={ep.method} size="sm" />
          <code>{ep.path}</code>
        </div>
      </div>

      {tab === 'request' && <RequestTab ep={ep} lang={lang} setLang={setLang} />}
      {tab === 'response' && <ResponseTab ep={ep} />}
      {tab === 'headers' && <HeadersTab ep={ep} />}
      {tab === 'try' && <TryItTab ep={ep} />}
    </div>
  );
}

function CodePaneIdle({ variant }) {
  return (
    <div className="codepane codepane-idle">
      <div className="codepane-idle-prompt">$ pick an endpoint</div>
      <div className="codepane-idle-hint">request, response, headers and a try-it console render here once you select something from the sidebar.</div>
      <div className="codepane-idle-grid">
        <div>request</div><div>·</div>
        <div>response</div><div>·</div>
        <div>headers</div><div>·</div>
        <div>try it</div><div>·</div>
      </div>
    </div>
  );
}

function RequestTab({ ep, lang, setLang }) {
  const [copied, copy] = useCopy();
  const code = ep.examples[lang];
  return (
    <>
      <div className="codepane-toolbar">
        <div className="lang-switch">
          {LANGS.map((l) => (
            <button key={l.id}
              className={cn('lang-btn', lang === l.id && 'is-active')}
              onClick={() => setLang(l.id)}
            >{l.label}</button>
          ))}
        </div>
        <button className="copy-btn" onClick={() => copy(code)}>
          {copied ? '✓ copied' : 'copy'}
        </button>
      </div>
      <pre className="codepane-code"><code>{code}</code></pre>
    </>
  );
}

function ResponseTab({ ep }) {
  const [copied, copy] = useCopy();
  const r = ep.mockOk;
  return (
    <>
      <div className="codepane-toolbar">
        <div className="resp-status">
          <span className={cn('resp-status-dot', `is-${statusClass(r.status)}`)} />
          <span>HTTP/2 {r.status} {r.status === 200 ? 'OK' : r.status === 201 ? 'Created' : ''}</span>
        </div>
        <button className="copy-btn" onClick={() => copy(r.body)}>{copied ? '✓ copied' : 'copy'}</button>
      </div>
      <pre className="codepane-code"><code>{r.body}</code></pre>
    </>
  );
}

function HeadersTab({ ep }) {
  const r = ep.mockOk;
  const rows = Object.entries(r.headers);
  return (
    <div className="headers-list">
      {rows.map(([k, v]) => (
        <div key={k} className="header-row">
          <span className="header-k">{k}</span>
          <span className="header-v">{v}</span>
        </div>
      ))}
    </div>
  );
}

function TryItTab({ ep }) {
  const [token, setToken] = useState('xubt_••••••');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  function run() {
    setRunning(true);
    setResult(null);
    const delay = 320 + Math.random() * 260;
    setTimeout(() => {
      setRunning(false);
      setResult({
        ok: true,
        status: ep.mockOk.status,
        ms: Math.round(delay),
        body: ep.mockOk.body,
      });
    }, delay);
  }

  return (
    <div className="tryit">
      <div className="tryit-row">
        <span className="tryit-k">Authorization</span>
        <input className="tryit-input" value={token} onChange={(e) => setToken(e.target.value)} />
      </div>
      <div className="tryit-row tryit-row-route">
        <MethodPill method={ep.method} size="sm" />
        <code className="tryit-path">{ep.path}</code>
        <button className="tryit-run" onClick={run} disabled={running}>
          {running ? 'running…' : 'send →'}
        </button>
      </div>

      <div className="tryit-result">
        {!result && !running && (
          <div className="tryit-empty">// response will appear here</div>
        )}
        {running && (
          <div className="tryit-running">
            <span className="tryit-spin" /> awaiting api.x-unofficial.dev
          </div>
        )}
        {result && (
          <>
            <div className="tryit-result-head">
              <span className={cn('resp-status-dot', `is-${statusClass(result.status)}`)} />
              <span>HTTP {result.status} · {result.ms} ms</span>
            </div>
            <pre className="codepane-code codepane-code-flush"><code>{result.body}</code></pre>
          </>
        )}
      </div>
    </div>
  );
}

// ── DocsApp shell ────────────────────────────────────────────────────────────
function DocsApp({ variant, tweaks }) {
  const [current, setCurrent] = useState(variant === 'terminal' ? 'create-post' : 'overview');
  const [query, setQuery] = useState('');
  const [theme, setTheme] = useState('dark');
  const [openMap, setOpenMap] = useState(() => {
    const o = {};
    DATA.sections.forEach((s) => { o[s.id] = true; });
    return o;
  });

  const toggleSection = (id) => setOpenMap((m) => ({ ...m, [id]: !m[id] }));

  // Surface css vars from tweaks
  const cssVars = {
    '--tw-accent': tweaks.accent,
    '--tw-mono': tweaks.fontPair === 'plex' ? '"IBM Plex Mono", ui-monospace, monospace'
              : tweaks.fontPair === 'geist' ? '"Geist Mono", ui-monospace, monospace'
              : '"JetBrains Mono", ui-monospace, monospace',
    '--tw-sans': tweaks.fontPair === 'plex' ? '"IBM Plex Sans", system-ui, sans-serif'
              : tweaks.fontPair === 'geist' ? '"Geist", system-ui, sans-serif'
              : '"JetBrains Mono", ui-monospace, monospace',
    '--tw-density-pad': tweaks.density === 'compact' ? '10px' : '16px',
    '--tw-density-row': tweaks.density === 'compact' ? '34px' : '40px',
    '--tw-body-size': tweaks.density === 'compact' ? '13px' : '14px',
  };

  return (
    <div
      className={cn('docs-app', `theme-${theme}`)}
      data-variant={variant}
      data-density={tweaks.density}
      style={cssVars}
    >
      <Topbar
        variant={variant}
        query={query}
        onSearch={setQuery}
        theme={theme}
        onToggleTheme={() => setTheme((t) => t === 'dark' ? 'light' : 'dark')}
      />
      <div className="docs-body">
        <Sidebar
          variant={variant}
          sidebarVariant={tweaks.sidebar}
          query={query}
          current={current}
          onSelect={setCurrent}
          openMap={openMap}
          onToggleSection={toggleSection}
        />
        <main className="main">
          <MainContent variant={variant} currentId={current} heroStyle={tweaks.hero} onSelect={setCurrent} />
        </main>
        <CodePane variant={variant} currentId={current} codeTheme={tweaks.codeTheme} />
      </div>
    </div>
  );
}

Object.assign(window, { DocsApp });
