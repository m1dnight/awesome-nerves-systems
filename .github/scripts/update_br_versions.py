#!/usr/bin/env python3
"""Refresh the `nerves_system_br` column of README.md from each system's repo.

For every table row linking to a GitHub repo, the script reads the
`nerves_system_br` requirement from the repo's mix.exs (root first, then any
other mix.exs in the tree) and the locked version from the sibling mix.lock.

Cell format:
  - exact requirement ("1.35.0")         -> 1.35.0
  - range with lock ("~> 1.33" + 1.34.0) -> ~> 1.33 (locked to 1.34.0)
  - range without lock                   -> ~> 1.33

Rows whose repo cannot be read are left untouched.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

README = sys.argv[1] if len(sys.argv) > 1 else "README.md"
TOKEN = os.environ.get("GITHUB_TOKEN")

ROW_RE = re.compile(
    r"^(\|[^|]*\|\s*\[[^\]]*\]\(https://github\.com/([\w.-]+/[\w.-]+?)/?\)\s*\|\s*)"
    r"([^|]*?)(\s*\|\s*)$"
)
DEP_RE = re.compile(r'\{\s*:nerves_system_br\s*,\s*"([^"]+)"')
LOCK_RE = re.compile(r'"nerves_system_br":\s*\{:hex,\s*:nerves_system_br,\s*"([^"]+)"')
EXACT_RE = re.compile(r"^(?:==\s*)?(\d+\.\d+\.\d+(?:-[\w.]+)?)$")


def fetch(url, api=False):
    headers = {"User-Agent": "awesome-nerves-systems"}
    if api:
        headers["Accept"] = "application/vnd.github+json"
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def raw(repo, path):
    return fetch(f"https://raw.githubusercontent.com/{repo}/HEAD/{path}")


def mix_paths(repo):
    """Candidate mix.exs paths, root first, then shallowest first."""
    yield "mix.exs"
    tree = fetch(f"https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1", api=True)
    if not tree:
        return
    paths = [e["path"] for e in json.loads(tree).get("tree", [])
             if e["path"].endswith("/mix.exs") and "/deps/" not in f"/{e['path']}"]
    yield from sorted(paths, key=lambda p: (p.count("/"), p))


def br_version(repo):
    for path in mix_paths(repo):
        mix = raw(repo, path)
        dep = mix and DEP_RE.search(mix)
        if not dep:
            continue
        req = dep.group(1).strip()
        exact = EXACT_RE.match(req)
        if exact:
            return exact.group(1)
        lock = raw(repo, path[: -len("mix.exs")] + "mix.lock")
        locked = lock and LOCK_RE.search(lock)
        return f"{req} (locked to {locked.group(1)})" if locked else req
    return None


def main():
    with open(README) as f:
        lines = f.read().split("\n")

    changed = []
    for i, line in enumerate(lines):
        m = ROW_RE.match(line)
        if not m:
            continue
        prefix, repo, current, suffix = m.groups()
        try:
            new = br_version(repo)
        except Exception as e:  # network/API errors must not abort the whole run
            print(f"warning: {repo}: {e}", file=sys.stderr)
            continue
        if new is None:
            print(f"warning: {repo}: no nerves_system_br dependency found", file=sys.stderr)
        elif new != current:
            lines[i] = f"{prefix}{new}{suffix}"
            changed.append(f"{repo}: {current} -> {new}")

    if changed:
        with open(README, "w") as f:
            f.write("\n".join(lines))
    print("\n".join(changed) if changed else "No changes.")


if __name__ == "__main__":
    main()
