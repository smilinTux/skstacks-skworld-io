# skstacks.skworld.io

The **primary** site for **SKStacks v2** — an AI-first sovereign infrastructure
framework. One descriptor renders to Docker Swarm, Kubernetes, or RKE2.

Live: https://skstacks.skworld.io · Project repo: https://github.com/smilinTux/skstacks

## Layout

- `index.html` — single-page site (SKWorld design system, inline CSS).
- `script.js` — renders the service grid + completion counter from `data/`,
  and live-fetches GitHub commits/releases for "Latest updates" (graceful
  fallback to `data/updates.json` when the API is rate-limited).
- `data/services-catalog.json` — 31 sk* services (name, layer, capability,
  provider, brief, status, image, repo, skworld_site).
- `data/completion.json` — totals (live-proven / deploy-ready / stub / pct).
- `data/updates.json` — committed fallback snapshot of latest release + commits.
- `assets/og-card.{svg,png}` — social share card.
- `scripts/gen-data.py` — regenerates `data/` from the upstream skstacks repo
  (reads `v2/<layer>/<svc>/app.yaml` + `v2/docs/testing/coverage-matrix.md`).
- `.github/workflows/refresh-data.yml` — runs `gen-data.py` daily (+ manual +
  on push) and commits `data/` if it changed.

## Regenerate data locally

```
python3 scripts/gen-data.py            # clone upstream, write data/
python3 scripts/gen-data.py --print    # dry run
```

🐧 part of the SKWorld ecosystem · skworld.io · GPL-3.0
