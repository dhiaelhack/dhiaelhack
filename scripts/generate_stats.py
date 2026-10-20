#!/usr/bin/env python3
"""Generate a self-contained GitHub profile statistics SVG."""

import argparse
import datetime as dt
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "stats.svg"
API = "https://api.github.com"
USER = "dhiaelhack"
LANG_COLORS = ["#00C2A8", "#12AAB8", "#238FC8", "#3B82F6", "#637CF0"]


def request(url, token):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "dhiaelhack-profile-stats",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def fetch_stats(token):
    profile = request(f"{API}/users/{USER}", token)
    repos = []
    page = 1
    while True:
        batch = request(f"{API}/users/{USER}/repos?type=owner&per_page=100&page={page}", token)
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    owned = [repo for repo in repos if not repo.get("fork") and not repo.get("private")]
    languages = {}
    for repo in owned:
        for name, count in request(repo["languages_url"], token).items():
            languages[name] = languages.get(name, 0) + count

    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365)).isoformat(timespec="seconds").replace("+00:00", "Z")
    query = """query($login: String!, $from: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from) {
          totalCommitContributions
          totalPullRequestContributions
        }
      }
    }"""
    payload = json.dumps({"query": query, "variables": {"login": USER, "from": since}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=payload, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "dhiaelhack-profile-stats",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError("GitHub GraphQL: " + "; ".join(error["message"] for error in result["errors"]))
    contribution = result["data"]["user"]["contributionsCollection"]
    return {
        "repos": profile["public_repos"],
        "stars": sum(repo.get("stargazers_count", 0) for repo in owned),
        "followers": profile["followers"],
        "commits": contribution["totalCommitContributions"],
        "prs": contribution["totalPullRequestContributions"],
        "languages": sorted(languages.items(), key=lambda item: item[1], reverse=True)[:5],
    }


def render(data):
    esc = lambda value: html.escape(str(value), quote=True)
    labels = [
        ("PUBLIC REPOS", data["repos"]), ("STARS", data["stars"]),
        ("FOLLOWERS", data["followers"]), ("COMMITS / 12 MO", data["commits"]),
        ("PULL REQUESTS / 12 MO", data["prs"]),
    ]
    aria = ", ".join(f"{name.lower()}: {value}" for name, value in labels)
    aria += "; top languages: " + (", ".join(name for name, _ in data["languages"]) or "—")
    out = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="220" viewBox="0 0 1000 220" role="img" aria-label="{esc(aria)}">
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#0B1220"/><stop offset="1" stop-color="#0E2B36"/></linearGradient><linearGradient id="bar" x1="0" x2="1"><stop stop-color="#00C2A8"/><stop offset="1" stop-color="#3B82F6"/></linearGradient></defs>
<rect width="1000" height="220" rx="16" fill="url(#bg)" stroke="#00C2A8" stroke-opacity=".35"/>
<text x="32" y="38" fill="#00C2A8" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace" font-size="14" font-weight="700">GITHUB ACTIVITY · LAST 12 MONTHS</text>''']
    for i, (name, value) in enumerate(labels):
        x = 32 + (i % 3) * 225
        y = 82 + (i // 3) * 65
        out.append(f'<text x="{x}" y="{y}" fill="#8B9BB0" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace" font-size="11">{esc(name)}</text>')
        out.append(f'<text x="{x}" y="{y + 28}" fill="#E6EDF3" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace" font-size="22" font-weight="700">{esc(value)}</text>')
    out.append('<text x="707" y="38" fill="#00C2A8" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace" font-size="14" font-weight="700">TOP LANGUAGES</text>')
    langs = data["languages"]
    total = sum(value for _, value in langs)
    if langs and total:
        y = 64
        for index, (name, count) in enumerate(langs):
            width = max(3, round(240 * count / total))
            out.append(f'<text x="707" y="{y + 11}" fill="#E6EDF3" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace" font-size="11">{esc(name)}</text>')
            out.append(f'<rect x="810" y="{y}" width="150" height="10" rx="5" fill="#8B9BB0" fill-opacity=".16"/><rect x="810" y="{y}" width="{round(width * 150 / 240)}" height="10" rx="5" fill="{LANG_COLORS[index]}"/>')
            y += 29
    else:
        out.append('<text x="707" y="82" fill="#8B9BB0" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace" font-size="18">—</text>')
    out.append('</svg>\n')
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="render neutral placeholders without network access")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="SVG output path")
    args = parser.parse_args()
    if args.dry_run or not os.environ.get("GITHUB_TOKEN"):
        data = {"repos": "—", "stars": "—", "followers": "—", "commits": "—", "prs": "—", "languages": []}
    else:
        try:
            data = fetch_stats(os.environ["GITHUB_TOKEN"])
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, RuntimeError, ValueError) as error:
            print(f"Could not fetch GitHub stats: {error}", file=sys.stderr)
            return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(data), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
