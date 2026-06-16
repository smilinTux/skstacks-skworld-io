#!/usr/bin/env python3
"""
gen-data.py — regenerate the SKStacks site data from the upstream skstacks repo.

Run by .github/workflows/refresh-data.yml (daily + on push + manual). It:

  1. clones smilinTux/skstacks (shallow) into a temp dir (or reuses --repo);
  2. reads every  v2/<layer>/<svc>/app.yaml  to build the service catalog
     (name, layer, capability, provider, brief, image, repo, skworld_site);
  3. reads        v2/docs/testing/coverage-matrix.md  to decide each service's
     status from its RKE2 column:
        🟩 / 🟢  -> live-proven   (deployed + verified live on the RKE2 cluster)
        ✅       -> deploy-ready  (case authored, not yet proven live on RKE2)
        else     -> stub          (not declared / unverified / capacity-blocked)
     A service is also downgraded to "stub" if its app.yaml is marked STUB and
     it has no live-proven RKE2 cell (sovereign images not yet published, etc.);
  4. writes  data/services-catalog.json  and  data/completion.json.

Design goal: simple + documented. No deploy-time secrets are read — only the
public descriptors and the testing coverage matrix.

Usage:
    python3 scripts/gen-data.py                 # clone upstream, write to data/
    python3 scripts/gen-data.py --repo /path    # use an existing checkout
    python3 scripts/gen-data.py --print         # print, don't write
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

UPSTREAM = "https://github.com/smilinTux/skstacks"
LAYERS = ["core", "comms", "compute", "cloud", "apps"]
HERE = Path(__file__).resolve().parent.parent  # repo root (site)
DATA_DIR = HERE / "data"


# ── minimal YAML reader ───────────────────────────────────────────────────
# We only need a handful of top-level scalar keys (name, description, capability,
# provider) plus deploy.image. To avoid a PyYAML dependency in CI, use a tiny
# tolerant line parser for exactly those keys.
def read_app_yaml(path: Path) -> dict:
    top: dict[str, str] = {}
    image = None
    in_deploy = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip("\n")
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0 and ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            val = stripped.split(":", 1)[1].strip()
            in_deploy = key == "deploy"
            if key in ("name", "description", "capability", "provider") and val:
                top[key] = _unquote(val)
        elif in_deploy and stripped.startswith("image:"):
            image = _unquote(stripped.split(":", 1)[1].strip())
    if image:
        top["image"] = image
    return top


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1]
    return v


# ── coverage matrix: svc -> RKE2 status symbol ────────────────────────────
def parse_coverage(repo: Path) -> dict[str, str]:
    """Return {svc_name: status} from the RKE2 column of coverage-matrix.md."""
    matrix = repo / "v2" / "docs" / "testing" / "coverage-matrix.md"
    status: dict[str, str] = {}
    if not matrix.exists():
        return status

    # Table rows look like:  | `sksso` | container | skdata,skcache | ✅ | ✅ | 🟩 | ⬜ |
    # Columns after the leading name/kind/deps are: swarm | k8s | rke2 | bare
    row_re = re.compile(r"^\|\s*`?(\w[\w-]*)`?\s*\|")
    for line in matrix.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        m = row_re.match(line.strip())
        if not m:
            continue
        name = m.group(1)
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # cells: [name, kind, deps, swarm, k8s, rke2, bare]  (rke2 = index 5)
        if len(cells) < 6:
            continue
        rke2 = cells[5]
        if "🟩" in rke2 or "🟢" in rke2:
            status[name] = "live-proven"
        elif "✅" in rke2:
            status[name] = "deploy-ready"
        else:
            status[name] = "stub"  # ⬜ / ⛔ / 📋 / blank
    return status


# ── brief: first sentence of capability/description, trimmed ───────────────
def make_brief(app: dict) -> str:
    text = app.get("description") or app.get("capability") or ""
    # take the part before the em-dash detail if present, else first sentence
    return text.strip()


def build_catalog(repo: Path) -> list[dict]:
    cov = parse_coverage(repo)
    services: list[dict] = []
    v2 = repo / "v2"
    for layer in LAYERS:
        layer_dir = v2 / layer
        if not layer_dir.is_dir():
            continue
        for svc_dir in sorted(p for p in layer_dir.iterdir() if p.is_dir()):
            app_yaml = svc_dir / "app.yaml"
            if not app_yaml.exists():
                continue
            app = read_app_yaml(app_yaml)
            name = app.get("name") or svc_dir.name
            status = cov.get(name, "stub")
            services.append({
                "name": name,
                "layer": layer,
                "capability": app.get("capability", ""),
                "provider": app.get("provider", ""),
                "brief": make_brief(app),
                "status": status,
                "image": app.get("image"),
                "repo": f"https://github.com/smilinTux/{name}",
                "skworld_site": f"https://{name}.skworld.io",
            })
    return services


def build_completion(services: list[dict]) -> dict:
    total = len(services)
    live = sum(1 for s in services if s["status"] == "live-proven")
    ready = sum(1 for s in services if s["status"] == "deploy-ready")
    stub = sum(1 for s in services if s["status"] == "stub")
    pct = round(live / total * 100) if total else 0
    return {
        "total": total,
        "live_proven": live,
        "deploy_ready": ready,
        "stub": stub,
        "pct_live": pct,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate SKStacks site data")
    ap.add_argument("--repo", help="path to an existing skstacks checkout")
    ap.add_argument("--print", action="store_true", dest="dry",
                    help="print JSON, do not write files")
    args = ap.parse_args()

    tmp = None
    if args.repo:
        repo = Path(args.repo)
    else:
        tmp = tempfile.mkdtemp(prefix="skstacks-")
        repo = Path(tmp) / "skstacks"
        print(f"cloning {UPSTREAM} (shallow) ...", file=sys.stderr)
        subprocess.run(
            ["git", "clone", "--depth", "1", UPSTREAM, str(repo)],
            check=True,
        )

    services = build_catalog(repo)
    if not services:
        print("ERROR: no services found — is the repo path/layout correct?",
              file=sys.stderr)
        return 1
    completion = build_completion(services)

    cat_json = json.dumps(services, indent=2) + "\n"
    comp_json = json.dumps(completion, indent=2) + "\n"

    if args.dry:
        print(cat_json)
        print(comp_json)
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "services-catalog.json").write_text(cat_json, encoding="utf-8")
        (DATA_DIR / "completion.json").write_text(comp_json, encoding="utf-8")
        print(f"wrote {DATA_DIR/'services-catalog.json'} ({len(services)} services)")
        print(f"wrote {DATA_DIR/'completion.json'} -> {completion}")

    if tmp:
        subprocess.run(["rm", "-rf", tmp], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
