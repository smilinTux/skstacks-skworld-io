// SKStacks v2 — site interactions
// 1. renders the service grid + completion counter from committed JSON (data/)
// 2. live-fetches GitHub commits + latest release for "Latest updates",
//    with graceful fallback to the committed data/updates.json snapshot.

(() => {
  'use strict';

  const REPO = 'smilinTux/skstacks';
  const API = 'https://api.github.com/repos/' + REPO;

  // tiny HTML escaper — all dynamic text goes through this
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const LAYER_ORDER = ['core', 'comms', 'compute', 'cloud', 'apps'];

  const STATUS_META = {
    'live-proven':  { cls: 'live',    label: '✅ live-proven' },
    'deploy-ready': { cls: 'ready',   label: '🟡 deploy-ready' },
    'stub':         { cls: 'planned', label: '⬜ planned' },
  };

  // ── animated number counter ───────────────────────────────────────────
  const animateCounter = (el, target, suffixHTML) => {
    if (!el) return;
    const duration = 1500;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const v = Math.round(target * eased);
      el.innerHTML = v + (suffixHTML || '');
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  // ── completion section ────────────────────────────────────────────────
  const renderCompletion = (c) => {
    const pct = c.pct_live ?? Math.round(((c.live_proven || 0) / (c.total || 1)) * 100);
    const counter = document.getElementById('completion-counter');
    const fill = document.getElementById('progress-fill');
    const caption = document.getElementById('completion-caption');

    if (caption) {
      caption.innerHTML = '<strong>' + esc(c.live_proven) + ' of ' + esc(c.total) +
        '</strong> services verified live on RKE2';
    }

    const runOnce = () => {
      animateCounter(counter, pct, '<span class="pct-sign">%</span>');
      animateCounter(document.getElementById('bd-live'), c.live_proven || 0, '');
      animateCounter(document.getElementById('bd-ready'), c.deploy_ready || 0, '');
      animateCounter(document.getElementById('bd-stub'), c.stub || 0, '');
      if (fill) requestAnimationFrame(() => { fill.style.width = pct + '%'; });
    };

    if ('IntersectionObserver' in window && counter) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) { runOnce(); io.disconnect(); }
        });
      }, { threshold: 0.35 });
      io.observe(counter);
    } else {
      runOnce();
    }
  };

  // ── service grid + layer filter ───────────────────────────────────────
  const renderServices = (services) => {
    const grid = document.getElementById('services-grid');
    const bar = document.getElementById('filter-bar');
    if (!grid) return;

    services.sort((a, b) => {
      const la = LAYER_ORDER.indexOf(a.layer), lb = LAYER_ORDER.indexOf(b.layer);
      if (la !== lb) return la - lb;
      return a.name.localeCompare(b.name);
    });

    const cardHTML = (s) => {
      const sm = STATUS_META[s.status] || STATUS_META.stub;
      const nm = s.name.replace(/^sk/, '<span>sk</span>');
      const links = [];
      if (s.repo) links.push('<a class="svc-link" href="' + esc(s.repo) + '" target="_blank" rel="noopener">repo ↗</a>');
      if (s.skworld_site) {
        const host = s.skworld_site.replace(/^https?:\/\//, '').replace(/\/$/, '');
        links.push('<a class="svc-link" href="' + esc(s.skworld_site) + '" target="_blank" rel="noopener">' + esc(host) + ' ↗</a>');
      }
      return '' +
        '<article class="svc-card" data-layer="' + esc(s.layer) + '" data-status="' + esc(s.status) + '">' +
          '<div class="svc-head"><div class="svc-name">' + nm + '</div></div>' +
          '<div class="svc-badges">' +
            '<span class="layer-badge" data-layer="' + esc(s.layer) + '">' + esc(s.layer) + '</span>' +
            '<span class="status-badge ' + sm.cls + '">' + sm.label + '</span>' +
          '</div>' +
          '<p class="svc-brief">' + esc(s.brief || s.capability) + '</p>' +
          (s.provider ? '<p class="svc-provider">⚙ ' + esc(s.provider) + '</p>' : '') +
          '<div class="svc-links">' + links.join('') + '</div>' +
        '</article>';
    };

    const draw = (layer) => {
      const list = layer === 'all' ? services : services.filter((s) => s.layer === layer);
      grid.innerHTML = list.map(cardHTML).join('');
    };

    // filter buttons (counts per layer)
    if (bar) {
      const counts = {};
      services.forEach((s) => { counts[s.layer] = (counts[s.layer] || 0) + 1; });
      const layers = ['all'].concat(LAYER_ORDER.filter((l) => counts[l]));
      bar.innerHTML = layers.map((l, i) => {
        const n = l === 'all' ? services.length : counts[l];
        return '<button class="filter-btn' + (i === 0 ? ' active' : '') +
          '" data-filter="' + l + '">' + esc(l) +
          '<span class="fb-count">' + n + '</span></button>';
      }).join('');
      bar.addEventListener('click', (e) => {
        const btn = e.target.closest('.filter-btn');
        if (!btn) return;
        bar.querySelectorAll('.filter-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        draw(btn.dataset.filter);
      });
    }

    draw('all');
  };

  // ── latest updates (release + commits) ────────────────────────────────
  const fmtDate = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? esc(iso) : d.toISOString().slice(0, 10);
  };

  const renderRelease = (rel) => {
    const card = document.getElementById('release-card');
    if (!card || !rel) return;
    const tag = rel.tag || rel.tag_name || 'latest';
    const name = rel.name || rel.tag_name || 'Latest release';
    const url = rel.url || rel.html_url || ('https://github.com/' + REPO + '/releases/latest');
    const body = (rel.body || '').split('\n').slice(0, 4).join('\n').slice(0, 360);
    const date = fmtDate(rel.published || rel.published_at);
    card.innerHTML = '' +
      '<div class="section-eyebrow" style="margin-bottom:.5rem">Latest release</div>' +
      '<a class="release-tag" href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(tag) + '</a>' +
      '<div class="release-name">' + esc(name) + '</div>' +
      (body ? '<div class="release-body">' + esc(body) + '</div>' : '') +
      (date ? '<div class="release-meta">published ' + esc(date) + '</div>' : '') +
      '<a class="btn btn-outline" style="padding:.55rem 1.1rem;font-size:.85rem" href="' + esc(url) + '" target="_blank" rel="noopener">View release ↗</a>';

    // also refresh the hero version + release CTA from live data
    const hv = document.getElementById('hero-version');
    const rc = document.getElementById('release-cta');
    if (hv) hv.textContent = tag;
    if (rc) rc.textContent = '⬇ ' + tag;
  };

  const renderCommits = (commits) => {
    const list = document.getElementById('commits-list');
    if (!list || !commits || !commits.length) return;
    list.innerHTML = commits.slice(0, 8).map((c) => {
      // accept both committed-snapshot shape and raw GitHub API shape
      const sha = (c.sha || '').slice(0, 7) || '·······';
      const msg = (c.message || (c.commit && c.commit.message) || '').split('\n')[0];
      const url = c.url && c.url.indexOf('api.github.com') === -1
        ? c.url
        : (c.html_url || ('https://github.com/' + REPO + '/commits/main'));
      const date = fmtDate(c.date || (c.commit && c.commit.author && c.commit.author.date));
      return '<a class="commit-row" href="' + esc(url) + '" target="_blank" rel="noopener">' +
        '<span class="commit-sha">' + esc(sha) + '</span>' +
        '<span class="commit-msg">' + esc(msg) + '</span>' +
        '<span class="commit-date">' + esc(date) + '</span>' +
      '</a>';
    }).join('');
  };

  const setNote = (text, live) => {
    const note = document.getElementById('updates-note');
    if (note) note.innerHTML = (live ? '<span class="dot-live">●</span> ' : '◌ ') + esc(text);
  };

  // Render committed snapshot first (instant), then try to enhance live.
  const loadUpdates = async () => {
    let snapshot = null;
    try {
      const r = await fetch('data/updates.json', { cache: 'no-cache' });
      if (r.ok) {
        snapshot = await r.json();
        renderRelease(snapshot.release);
        renderCommits(snapshot.commits);
        setNote('showing committed snapshot · checking GitHub…', false);
      }
    } catch (_) { /* ignore */ }

    // Live enhancement from GitHub API.
    try {
      const [relR, comR] = await Promise.all([
        fetch(API + '/releases/latest', { cache: 'no-store' }),
        fetch(API + '/commits?per_page=8', { cache: 'no-store' }),
      ]);
      let gotRelease = false, gotCommits = false;
      if (relR.ok) { renderRelease(await relR.json()); gotRelease = true; }
      if (comR.ok) { renderCommits(await comR.json()); gotCommits = true; }
      if (gotRelease || gotCommits) {
        setNote('live from github.com/' + REPO, true);
      } else {
        throw new Error('api unavailable');
      }
    } catch (_) {
      setNote(snapshot ? 'GitHub rate-limited — showing committed snapshot' : 'updates unavailable', false);
    }
  };

  // ── boot ──────────────────────────────────────────────────────────────
  const boot = async () => {
    // scroll reveal
    const revealEls = document.querySelectorAll('.reveal');
    if ('IntersectionObserver' in window) {
      const obs = new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('visible'); obs.unobserve(e.target); } });
      }, { threshold: 0.1 });
      revealEls.forEach((el) => obs.observe(el));
    } else {
      revealEls.forEach((el) => el.classList.add('visible'));
    }

    // completion (committed JSON, fallback to hardcoded if fetch fails)
    try {
      const r = await fetch('data/completion.json', { cache: 'no-cache' });
      renderCompletion(r.ok ? await r.json() : { total: 31, live_proven: 15, deploy_ready: 2, stub: 14, pct_live: 48 });
    } catch (_) {
      renderCompletion({ total: 31, live_proven: 15, deploy_ready: 2, stub: 14, pct_live: 48 });
    }

    // services grid (committed JSON)
    try {
      const r = await fetch('data/services-catalog.json', { cache: 'no-cache' });
      if (r.ok) renderServices(await r.json());
      else document.getElementById('services-grid').innerHTML =
        '<p style="color:var(--dim)">Could not load the catalog. See <a href="data/services-catalog.json" style="color:var(--cyan)">services-catalog.json</a>.</p>';
    } catch (_) {
      const g = document.getElementById('services-grid');
      if (g) g.innerHTML = '<p style="color:var(--dim)">Could not load the catalog. See <a href="data/services-catalog.json" style="color:var(--cyan)">services-catalog.json</a>.</p>';
    }

    // latest updates (committed snapshot + live GitHub)
    loadUpdates();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
