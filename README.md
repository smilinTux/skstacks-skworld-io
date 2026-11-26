# skstacks.skworld.io

The public site for **SKStacks**, the SKWorld infrastructure framework
([smilinTux/skstacks](https://github.com/smilinTux/skstacks)). Static, served
by GitHub Pages from `main`, in the skworld.io house style.

Live: https://skstacks.skworld.io/

## Layout

- `index.html`, `style.css`: the page. The stat tiles, service catalog, latest
  release and v2 list sit between `<!-- gen:NAME -->` markers and are
  rewritten by `scripts/gen-data.py`; edit everything else by hand.
- `docs.html` + `docs-manifest.json`: the SKWorld repo-docs viewer, rendering
  `smilinTux/skstacks` `docs/*.md` live from the GitHub API, with the committed
  manifest as the rate-limit fallback (`.github/scripts/docs-manifest-gen.py`,
  refreshed daily by `.github/workflows/refresh-docs-manifest.yml`).
- `diagrams/skstacks.architecture.{json,html}`: the Archify architecture
  diagram, derived from the mermaid in skstacks `v2/docs/INSTANCE-MODEL.md`.
  `.github/workflows/archify.yml` fails a PR whose HTML is stale against the
  JSON. `img/diagram-architecture.png` is its inline screenshot.
- `data/services-catalog.json`, `data/summary.json`, `data/updates.json`:
  generated data (also handy for anything that wants the catalog as JSON).
- `og.html` -> `og.png` (1200x630 social card), `robots.txt`, `sitemap.xml`,
  `llms.txt`.

## Regenerate the data

```
python3 scripts/gen-data.py                     # shallow-clones upstream
python3 scripts/gen-data.py --repo ../skstacks  # use a local checkout
python3 scripts/gen-data.py --print             # dry run
```

The generator lists every service directory under `v1/ansible/{core,optional}/`
(the tree decides what exists), takes the one-line purpose and pinned upstream
from the table in `docs/v1-service-catalog.md` (falling back to the service
README and its template `image:` lines), lists the v2 `app.yaml` descriptors,
and reads the newest `skstacks-v*` tag with `git ls-remote`. The category of
each service is the one editorial field (`CATEGORY_OF` in the script); a new
upstream service with no category lands in "Other" and the run warns.
`.github/workflows/refresh-data.yml` runs it daily and commits any change.

## Regenerate the diagram and the social card

```
# Archify v3.2.0 @ 208acba8 (see sk-standards standards/archify-diagrams.md)
ARCHIFY_UPDATE_CHECK_DISABLED=1 node bin/archify.mjs finalize architecture \
  diagrams/skstacks.architecture.json diagrams/skstacks.architecture.html --quality showcase --json

google-chrome --headless=new --no-sandbox --user-data-dir="$(mktemp -d)" \
  --window-size=1200,630 --screenshot="$PWD/og.png" "file://$PWD/og.html"
```

Part of [SKWorld](https://skworld.io/). The SKStacks framework itself is AGPL-3.0.
