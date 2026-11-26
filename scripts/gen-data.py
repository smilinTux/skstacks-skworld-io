#!/usr/bin/env python3
"""
gen-data.py: regenerate the SKStacks site data from the public skstacks repo.

Run by .github/workflows/refresh-data.yml (daily, on push, and by hand). It:

  1. clones smilinTux/skstacks (shallow) into a temp dir, or reuses --repo;
  2. lists the v1 services, which are what the production framework ships and
     what every skstacks-v2.26.x release tag carries: one directory per service
     under  v1/ansible/core/  and  v1/ansible/optional/  (the tree is the
     authority for what exists);
  3. fills each service's one-line purpose and pinned upstream from the
     "At a glance" table in  docs/v1-service-catalog.md, falling back to the
     service README (purpose) and the image: lines of its templates (upstream)
     for a service the table does not list yet;
  4. lists the v2 descriptors ( v2/<layer>/<svc>/app.yaml ), the multi-platform
     track that is still in development;
  5. reads the newest skstacks-v* tag with  git ls-remote --tags  and its date
     and section headings from CHANGELOG.md;
  6. writes  data/services-catalog.json, data/summary.json, data/updates.json
     and rewrites the generated blocks in index.html and llms.txt (between
     <!-- gen:NAME --> and <!-- /gen:NAME --> markers), so the page renders
     the current catalog with no client-side JavaScript.

Output is a function of the upstream commit only (the "generated" stamp is the
upstream commit date, not today), so a run against an unchanged upstream
writes nothing and the workflow commits nothing.

Only public files are read. No secrets, no network calls beyond the clone and
ls-remote of the public repo.

Usage:
    python3 scripts/gen-data.py                 # clone upstream, write files
    python3 scripts/gen-data.py --repo /path    # use an existing checkout
    python3 scripts/gen-data.py --print         # print JSON, write nothing
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

UPSTREAM = "https://github.com/smilinTux/skstacks"
GH_TREE = "https://github.com/smilinTux/skstacks/tree"
GH_BLOB = "https://github.com/smilinTux/skstacks/blob"
HERE = Path(__file__).resolve().parent.parent  # site repo root
DATA_DIR = HERE / "data"

V1_TIERS = ["core", "optional"]
V2_LAYERS = ["core", "comms", "compute", "cloud", "apps"]

# Category is the one editorial field: the upstream tree only knows "core" and
# "optional". A service missing here lands in "other" and the run prints a
# warning, so a new upstream service shows up on the page either way.
CATEGORIES = [
    ("edge", "Edge and security",
     "Ingress, TLS, floating VIPs, threat blocking, CVE detection and patching."),
    ("identity", "Identity and access",
     "Single sign-on, mesh VPN and remote access."),
    ("ops", "Observability and operations",
     "Metrics, logs, alerts, uptime, flow visibility, health checks and cluster UIs."),
    ("data", "Data and storage",
     "Object storage, databases, vectors, graphs, registries, sync and backup."),
    ("collab", "Collaboration and productivity",
     "Files, wiki, tasks, mail, PDFs, Solid pods and published pages."),
    ("automation", "Automation and development",
     "Git and CI, workflow engines, infrastructure as code and service workers."),
    ("search", "Search and AI",
     "Private metasearch and an AI search front end."),
    ("media", "Media and home",
     "Photos, streaming, media fetching, home and fitness tracking."),
    ("other", "Other", "Services not yet sorted into a category."),
]
CATEGORY_OF = {
    "skfence": "edge", "skfenceha": "edge", "skha": "edge", "sksec": "edge",
    "sksec-web": "edge", "skaegis": "edge", "skbom": "edge",
    "skpatch-hosts": "edge",
    "sksso": "identity", "skmesh": "identity", "skrac": "identity",
    "skdesk": "identity",
    "skmon": "ops", "skpulse": "ops", "skhealth": "ops", "sknet": "ops",
    "skdash": "ops", "skport": "ops", "skwhoami": "ops",
    "skstor": "data", "skmem-pg": "data", "skgraph": "data", "skvector": "data",
    "skreg": "data", "sksync": "data", "skbackup": "data",
    "skhub": "collab", "skbook": "collab", "skboard": "collab",
    "skmail": "collab", "skpdf": "collab", "skpods": "collab",
    "skpages": "collab",
    "skgit": "automation", "skflow": "automation", "skorch": "automation",
    "skform": "automation", "skwrit": "automation", "skpayment": "automation",
    "skpeek": "search", "skseek": "search",
    "skgallery": "media", "skstream": "media", "skfetch": "media",
    "skhome": "media", "skgym": "media",
}


# ── text helpers ───────────────────────────────────────────────────────────
def clean(text: str) -> str:
    """Upstream markdown cell or sentence to plain text for the site.

    Strips links and emphasis, and replaces typographic dashes, which the
    SKWorld writing rule bans on every published page.
    """
    t = text.strip()
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\*\*([^*]*)\*\*", r"\1", t)
    t = t.replace(" — ", ": ").replace("—", ", ")
    t = t.replace(" – ", " - ").replace("–", "-")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def inline_html(text: str) -> str:
    """Escape text and render `code` spans."""
    parts = re.split(r"(`[^`]*`)", text)
    out = []
    for p in parts:
        if len(p) >= 2 and p.startswith("`") and p.endswith("`"):
            out.append("<code>" + html.escape(p[1:-1]) + "</code>")
        else:
            out.append(html.escape(p))
    return "".join(out)


def plain(text: str) -> str:
    return text.replace("`", "")


# ── v1 services ────────────────────────────────────────────────────────────
def parse_catalog_table(repo: Path) -> dict[str, dict]:
    """{service: {purpose, upstream}} from docs/v1-service-catalog.md."""
    doc = repo / "docs" / "v1-service-catalog.md"
    rows: dict[str, dict] = {}
    if not doc.exists():
        return rows
    header: list[str] | None = None
    for line in doc.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("|"):
            header = None if not line.strip() else header
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        if not header or header[0] != "service":
            continue
        m = re.match(r"\[([a-z0-9-]+)\]", cells[0])
        if not m:
            continue
        rec = dict(zip(header, cells))
        rows[m.group(1)] = {
            "purpose": clean(rec.get("what it is", "")),
            "upstream": clean(rec.get("upstream (pinned)", "")),
        }
    return rows


def _tidy(text: str) -> str:
    text = re.sub(r"^\S+ is an? ", "", text)  # "SKPayment is a gateway" -> "gateway"
    return text[:1].upper() + text[1:] if text else text


def readme_purpose(svc_dir: Path) -> str:
    """Fallback one-liner for a service the catalog table does not list yet."""
    readme = svc_dir / "README.md"
    if not readme.exists():
        return ""
    lines = readme.read_text(encoding="utf-8", errors="replace").splitlines()
    # "# name: what it is" and "# name (what it is)" headings carry the
    # cleanest one-liner.
    for line in lines:
        if line.startswith("# "):
            head = clean(line[2:])
            m = re.match(r"[^:(]+:\s*(.{9,})$", head) or re.match(r"[^:(]+\((.{9,})\)$", head)
            if m:
                return _tidy(m.group(1))
            break
    para: list[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            if para:
                break
            continue
        if not s or s.startswith(("|", "```", "-", "*", ">")):
            if para:
                break
            continue
        para.append(s)
    text = clean(" ".join(para))
    text = re.split(r"(?<=[a-z0-9)])\.\s", text, maxsplit=1)[0].rstrip(".")
    if ": " in text:
        left, right = text.split(": ", 1)
        if len(left) < 35:   # "Tool on the swarm: what it does (detail)"
            text = left + ": " + re.split(r"\s\(|, ", right, maxsplit=1)[0]
        elif len(text) > 150:
            text = left
    return _tidy(text)


IMAGE_RE = re.compile(r"^\s*image:\s*(.+?)\s*$")
DEFAULT_RE = re.compile(r"default\(\s*['\"]([^'\"]+)['\"]")


def template_images(svc_dir: Path) -> list[str]:
    found: list[str] = []
    for f in sorted(svc_dir.rglob("*")):
        if not f.is_file() or f.suffix not in (".j2", ".yml", ".yaml"):
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = IMAGE_RE.match(line)
            if not m:
                continue
            val = m.group(1).strip("'\"")
            if "{{" in val:
                d = DEFAULT_RE.search(val)
                if not d:
                    continue
                val = d.group(1)
            if "/" not in val and ":" not in val:
                continue
            ref = val.split("@", 1)[0]
            if ref not in found:
                found.append(ref)
    return found


def build_v1(repo: Path) -> list[dict]:
    table = parse_catalog_table(repo)
    out: list[dict] = []
    for tier in V1_TIERS:
        tier_dir = repo / "v1" / "ansible" / tier
        if not tier_dir.is_dir():
            continue
        for svc_dir in sorted(p for p in tier_dir.iterdir() if p.is_dir()):
            name = svc_dir.name
            row = table.get(name, {})
            purpose = row.get("purpose") or readme_purpose(svc_dir)
            upstream = row.get("upstream", "")
            if not upstream:
                imgs = template_images(svc_dir)
                upstream = ", ".join(imgs[:4]) + (" and more" if len(imgs) > 4 else "")
            cat = CATEGORY_OF.get(name, "other")
            if cat == "other":
                print(f"warning: {name} has no category in CATEGORY_OF", file=sys.stderr)
            if not purpose:
                print(f"warning: {name} has no purpose (catalog table or README)", file=sys.stderr)
            rel = f"v1/ansible/{tier}/{name}"
            out.append({
                "name": name,
                "tier": tier,
                "category": cat,
                "purpose": purpose,
                "upstream": upstream,
                "in_catalog_doc": name in table,
                "path": rel,
                "url": f"{GH_TREE}/main/{rel}",
            })
    return out


# ── v2 descriptors ─────────────────────────────────────────────────────────
def read_app_yaml(path: Path) -> dict:
    """Tiny tolerant reader for the few top-level keys we need (no PyYAML)."""
    top: dict[str, str] = {}
    image = None
    in_deploy = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        s = raw.strip()
        if indent == 0 and ":" in s:
            key, val = (x.strip() for x in s.split(":", 1))
            in_deploy = key == "deploy"
            if key in ("name", "description", "capability", "provider") and val:
                top[key] = val.strip("'\"")
        elif in_deploy and s.startswith("image:"):
            image = s.split(":", 1)[1].strip().strip("'\"")
    if image:
        top["image"] = image
    return top


def build_v2(repo: Path) -> list[dict]:
    out: list[dict] = []
    for layer in V2_LAYERS:
        layer_dir = repo / "v2" / layer
        if not layer_dir.is_dir():
            continue
        for svc_dir in sorted(p for p in layer_dir.iterdir() if p.is_dir()):
            app_yaml = svc_dir / "app.yaml"
            if not app_yaml.exists():
                continue
            app = read_app_yaml(app_yaml)
            name = app.get("name") or svc_dir.name
            out.append({
                "name": name,
                "layer": layer,
                "purpose": clean(app.get("description") or app.get("capability") or ""),
                "provider": clean(app.get("provider", "")),
                "image": app.get("image"),
                "url": f"{GH_TREE}/main/v2/{layer}/{svc_dir.name}",
            })
    return out


# ── release + commits ──────────────────────────────────────────────────────
def vkey(tag: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", tag))


def latest_tags(repo: Path, n: int = 6) -> list[str]:
    res = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", UPSTREAM, "skstacks-v*"],
        capture_output=True, text=True, check=True, cwd=repo)
    tags = [l.split("refs/tags/", 1)[1] for l in res.stdout.splitlines() if "refs/tags/" in l]
    tags = [t for t in tags if re.fullmatch(r"skstacks-v\d+\.\d+\.\d+", t)]
    return sorted(tags, key=vkey, reverse=True)[:n]


def changelog_sections(repo: Path) -> dict[str, dict]:
    cl = repo / "CHANGELOG.md"
    out: dict[str, dict] = {}
    if not cl.exists():
        return out
    cur = None
    for line in cl.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^##\s+(skstacks-v[\d.]+)\s*(?:[-–—]\s*(\d{4}-\d{2}-\d{2}))?", line)
        if m:
            cur = m.group(1)
            out[cur] = {"date": m.group(2), "highlights": []}
            continue
        if line.startswith("## "):
            cur = None
            continue
        if cur and line.startswith("### "):
            out[cur]["highlights"].append(clean(line[4:]))
    return out


def build_updates(repo: Path) -> dict:
    tags = latest_tags(repo)
    if not tags:
        raise SystemExit("ERROR: no skstacks-v* tags found upstream")
    sections = changelog_sections(repo)
    releases = []
    for t in tags:
        sec = sections.get(t, {})
        releases.append({
            "tag": t,
            "date": sec.get("date"),
            "url": f"{GH_TREE}/{t}",
            "highlights": sec.get("highlights", [])[:8],
        })
    log = subprocess.run(
        ["git", "log", "-n", "8", "--format=%H%x09%ad%x09%s", "--date=short"],
        capture_output=True, text=True, check=True, cwd=repo).stdout
    commits = []
    for l in log.splitlines():
        sha, date, msg = l.split("\t", 2)
        commits.append({"sha": sha[:8], "date": date, "message": clean(msg),
                        "url": f"https://github.com/smilinTux/skstacks/commit/{sha}"})
    return {
        "release": releases[0],
        "recent_releases": releases,
        "changelog_url": f"{GH_BLOB}/main/CHANGELOG.md",
        "commits": commits,
    }


# ── HTML / llms.txt blocks ─────────────────────────────────────────────────
def render_catalog(v1: list[dict]) -> str:
    out = []
    for cid, label, blurb in CATEGORIES:
        svcs = [s for s in v1 if s["category"] == cid]
        if not svcs:
            continue
        out.append(f'<div class="cat" id="cat-{cid}">')
        out.append(f'  <div class="cat-head"><h3>{html.escape(label)}</h3>'
                   f'<span class="cat-count">{len(svcs)}</span></div>')
        out.append(f'  <p class="cat-blurb">{html.escape(blurb)}</p>')
        out.append('  <div class="pgrid">')
        for s in svcs:
            core = " k" if s["tier"] == "core" else ""
            up = (f'<span class="phost">{inline_html(s["upstream"])}</span>'
                  if s["upstream"] else "")
            out.append(
                f'    <a class="pcard{core}" href="{html.escape(s["url"])}">'
                f'<span class="pname">{html.escape(s["name"])}'
                f' <span class="tier">{s["tier"]}</span></span>'
                f'<span class="pblurb">{inline_html(s["purpose"])}</span>{up}</a>')
        out.append("  </div>")
        out.append("</div>")
    return "\n".join(out)


def render_v2(v2: list[dict]) -> str:
    out = []
    for layer in V2_LAYERS:
        svcs = [s for s in v2 if s["layer"] == layer]
        if not svcs:
            continue
        out.append(f'<div class="v2row"><span class="v2layer">{layer}</span><ul class="mcp-list">')
        for s in svcs:
            title = html.escape(plain(s["purpose"]), quote=True)
            out.append(f'  <li><a href="{html.escape(s["url"])}" title="{title}">{html.escape(s["name"])}</a></li>')
        out.append("</ul></div>")
    return "\n".join(out)


def render_release(upd: dict) -> str:
    r = upd["release"]
    date = f' <span class="rel-date">{html.escape(r["date"])}</span>' if r.get("date") else ""
    out = [f'<p class="rel-tag"><a href="{html.escape(r["url"])}"><code>{html.escape(r["tag"])}</code></a>{date}</p>']
    if r["highlights"]:
        out.append('<ul class="plist">')
        out += [f"  <li>{inline_html(h)}</li>" for h in r["highlights"]]
        out.append("</ul>")
    prev = upd["recent_releases"][1:]
    if prev:
        out.append('<p class="meta">Earlier: ' + " &middot; ".join(
            f'<a href="{html.escape(p["url"])}">{html.escape(p["tag"].replace("skstacks-", ""))}</a>'
            + (f' ({html.escape(p["date"])})' if p.get("date") else "")
            for p in prev) + "</p>")
    return "\n".join(out)


def render_stats(summary: dict) -> str:
    tiles = [
        ("Latest release", summary["release"].replace("skstacks-", ""),
         summary.get("release_date") or "tagged"),
        ("v1 services", str(summary["v1_total"]),
         f'{summary["v1_core"]} core, {summary["v1_optional"]} optional'),
        ("Categories", str(summary["categories"]), "grouped below"),
        ("v2 descriptors", str(summary["v2_total"]), "in development"),
    ]
    return "\n".join(
        f'<div class="stat-tile"><span class="stat-label">{html.escape(a)}</span>'
        f'<span class="stat-value">{html.escape(b)}</span>'
        f'<span class="stat-sub">{html.escape(c)}</span></div>'
        for a, b, c in tiles)


def render_inline(summary: dict, key: str) -> str:
    return html.escape(str(summary[key]))


def render_llms(v1: list[dict], v2: list[dict], upd: dict) -> str:
    lines = [f'Latest release: {upd["release"]["tag"]}'
             + (f' ({upd["release"]["date"]})' if upd["release"].get("date") else ""),
             "", f"v1 services ({len(v1)}), by category:", ""]
    for cid, label, _ in CATEGORIES:
        svcs = [s for s in v1 if s["category"] == cid]
        if not svcs:
            continue
        lines.append(f"### {label}")
        lines += [f'- {s["name"]} ({s["tier"]}): {plain(s["purpose"])}' for s in svcs]
        lines.append("")
    lines.append(f"v2 descriptors ({len(v2)}, in development): "
                 + ", ".join(s["name"] for s in v2))
    return "\n".join(lines)


def replace_block(text: str, name: str, body: str) -> str:
    pat = re.compile(r"(<!-- gen:%s -->)(.*?)(<!-- /gen:%s -->)" % (name, name), re.S)
    if not pat.search(text):
        raise SystemExit(f"ERROR: marker gen:{name} not found")
    return pat.sub(lambda m: m.group(1) + "\n" + body + "\n" + m.group(3), text)


def write_if_changed(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        print(f"unchanged {path.relative_to(HERE)}")
        return
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(HERE)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate SKStacks site data")
    ap.add_argument("--repo", help="path to an existing skstacks checkout")
    ap.add_argument("--print", action="store_true", dest="dry",
                    help="print JSON, do not write files")
    args = ap.parse_args()

    tmp = None
    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        tmp = tempfile.mkdtemp(prefix="skstacks-")
        repo = Path(tmp) / "skstacks"
        print(f"cloning {UPSTREAM} (shallow) ...", file=sys.stderr)
        subprocess.run(["git", "clone", "--quiet", "--depth", "20", UPSTREAM, str(repo)],
                       check=True)

    try:
        head = subprocess.run(["git", "log", "-1", "--format=%H%x09%ad", "--date=short"],
                              capture_output=True, text=True, check=True, cwd=repo).stdout.strip()
        head_sha, head_date = head.split("\t")
        v1 = build_v1(repo)
        v2 = build_v2(repo)
        if not v1:
            print("ERROR: no v1 services found; has the upstream layout changed?", file=sys.stderr)
            return 1
        upd = build_updates(repo)
    finally:
        if tmp:
            subprocess.run(["rm", "-rf", tmp], check=False)

    used = [c for c in CATEGORIES if any(s["category"] == c[0] for s in v1)]
    summary = {
        "generated": head_date,
        "upstream_commit": head_sha[:8],
        "release": upd["release"]["tag"],
        "release_date": upd["release"].get("date"),
        "v1_total": len(v1),
        "v1_core": sum(1 for s in v1 if s["tier"] == "core"),
        "v1_optional": sum(1 for s in v1 if s["tier"] == "optional"),
        "categories": len(used),
        "by_category": {c[1]: sum(1 for s in v1 if s["category"] == c[0]) for c in used},
        "v2_total": len(v2),
    }
    catalog = {
        "generated": head_date,
        "source": {"repo": UPSTREAM, "commit": head_sha[:8], "release": upd["release"]["tag"]},
        "categories": [{"id": c[0], "label": c[1], "blurb": c[2]} for c in used],
        "services": v1,
        "v2_descriptors": v2,
    }
    updates = {"generated": head_date, **upd}

    dumps = lambda o: json.dumps(o, indent=2, ensure_ascii=False) + "\n"  # noqa: E731
    if args.dry:
        print(dumps(summary))
        print(dumps(catalog))
        print(dumps(updates))
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_if_changed(DATA_DIR / "services-catalog.json", dumps(catalog))
    write_if_changed(DATA_DIR / "summary.json", dumps(summary))
    write_if_changed(DATA_DIR / "updates.json", dumps(updates))

    index = HERE / "index.html"
    text = index.read_text(encoding="utf-8")
    text = replace_block(text, "stats", render_stats(summary))
    text = replace_block(text, "catalog", render_catalog(v1))
    text = replace_block(text, "v2", render_v2(v2))
    text = replace_block(text, "release", render_release(upd))
    for key in ("release", "v1_total", "v2_total", "generated", "upstream_commit"):
        text = re.sub(r"(<!-- gen:inline:%s -->).*?(<!-- /gen:inline:%s -->)" % (key, key),
                      lambda m, k=key: m.group(1) + render_inline(summary, k) + m.group(2), text)
    write_if_changed(index, text)

    llms = HERE / "llms.txt"
    write_if_changed(llms, replace_block(llms.read_text(encoding="utf-8"), "catalog",
                                         render_llms(v1, v2, upd)))

    print(f"v1 services: {summary['v1_total']} ({summary['v1_core']} core, "
          f"{summary['v1_optional']} optional) in {summary['categories']} categories; "
          f"v2 descriptors: {summary['v2_total']}; release {summary['release']}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
