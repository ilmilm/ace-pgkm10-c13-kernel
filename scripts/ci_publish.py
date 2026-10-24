#!/usr/bin/env python3
"""Publish files from the CI runner back into this repository via the API.

The local machine cannot reach Actions log/artifact blob storage, so the runner
pushes what we need (build log, Image, Image.gz, Module.symvers) into a branch
instead.  Everything goes through api.github.com, which the runner can reach.

usage (in the workflow):
    python3 scripts/ci_publish.py <branch> <commit message> <file> [file ...]
env:
    GITHUB_TOKEN, GITHUB_REPOSITORY
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]


def api(path, method="GET", payload=None, attempts=4):
    url = "https://api.github.com/" + path
    data = json.dumps(payload).encode() if payload is not None else None
    last = None
    for i in range(attempts):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ace-c13-ci-publish",
        })
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:400]
            if e.code in (500, 502, 503, 504) and i + 1 < attempts:
                print(f"  retry {i+1} after HTTP {e.code}", file=sys.stderr)
                time.sleep(5 * (i + 1))
                last = e
                continue
            print("HTTP", e.code, detail, file=sys.stderr)
            raise
        except Exception as e:            # timeouts, resets
            last = e
            if i + 1 < attempts:
                print(f"  retry {i+1} after {type(e).__name__}", file=sys.stderr)
                time.sleep(5 * (i + 1))
                continue
            raise
    raise last


def main():
    branch, msg = sys.argv[1], sys.argv[2]
    files = sys.argv[3:]
    entries = []
    for p in files:
        if not os.path.exists(p):
            print("skip (missing):", p)
            continue
        raw = open(p, "rb").read()
        blob = api(f"repos/{REPO}/git/blobs", "POST",
                   {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        entries.append({"path": os.path.basename(p), "mode": "100644",
                        "type": "blob", "sha": blob["sha"]})
        print(f"  blob {blob['sha'][:10]} {os.path.basename(p)} ({len(raw)} bytes)")
    if not entries:
        print("nothing to publish")
        return

    try:
        ref = api(f"repos/{REPO}/git/ref/heads/{branch}")
        parents = [ref["object"]["sha"]]
        base_tree = api(f"repos/{REPO}/git/commits/{parents[0]}")["tree"]["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        parents, base_tree = [], None

    tree_body = {"tree": entries}
    if base_tree:
        tree_body["base_tree"] = base_tree
    tree = api(f"repos/{REPO}/git/trees", "POST", tree_body)

    commit_body = {"message": msg, "tree": tree["sha"]}
    if parents:
        commit_body["parents"] = parents
    commit = api(f"repos/{REPO}/git/commits", "POST", commit_body)

    if parents:
        api(f"repos/{REPO}/git/refs/heads/{branch}", "PATCH",
            {"sha": commit["sha"], "force": True})
    else:
        api(f"repos/{REPO}/git/refs", "POST",
            {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
    print("published ->", branch, commit["sha"][:10])


if __name__ == "__main__":
    main()
