#!/usr/bin/env python3
"""
SDN Link Checker — runs on GitHub Actions at randomised times, checks a random slice of
every link on the sites, and raises a GitHub Issue (which emails you) when something breaks.

Each run:  picks the least-recently-checked links (random tie-break) and trickles through them
over the whole run — a random 45–150 s gap between Amazon requests, plus an occasional longer
pause of several minutes, so ~70 links take roughly two hours and never form a burst. Classifies each:
  OK            Amazon product page loaded (title present)
  NOT_FOUND     HTTP 404 — the ASIN no longer exists (dead link)
  UNAVAILABLE   page loads but says the book is currently unavailable (discontinued?)
  BLOCKED       Amazon served a robot check / 503 — cannot judge; retried later, never reported as broken
Affiliate tags are stripped before checking, so a check is never an affiliate click.
SCOPE=internal (GitHub: site pages only, no Amazon traffic from a datacentre) / SCOPE=amazon (your own PC,
residential address, START_JITTER randomises the start time) / SCOPE=all.
Cautionary defaults for Amazon: 60 links per run, 90–240 s apart with 5–15 minute pauses — one weekly run
covers every Amazon link about once a quarter. Raise SAMPLE only if you want faster coverage.
  ERROR         network error
Internal links (author pages, book pages, sitemaps) are HEAD-checked on github.io.
It also reads the "formats" strip on OK pages to discover editions the site doesn't link yet.
State lives in linkcheck_state.json (committed back by the workflow) so coverage rotates
through every link roughly every 3 days at ~70 links per run, 8 runs a day (one every 3 h).
"""
import json, os, random, re, sys, time, urllib.request, urllib.error, datetime

HUB = "https://raw.githubusercontent.com/sdnpublishing/sdn-publishing/main/index.html"
STATE = "linkcheck_state.json"; REPORT = "linkcheck_report.md"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
HDR = {"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9", "Accept": "text/html,application/xhtml+xml"}

def fetch(url, method="GET", timeout=25):
    req = urllib.request.Request(url, method=method, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, (r.read(300000).decode("utf-8", "ignore") if method == "GET" else "")
    except urllib.error.HTTPError as e: return e.code, (e.read(20000).decode("utf-8", "ignore") if e.code != 404 else "")
    except Exception as e: return 0, str(e)

def classify_amazon(status, body):
    if status == 404: return "NOT_FOUND", ""
    if status in (503, 429) or "Robot Check" in body or "api-services-support@amazon.com" in body or "captcha" in body.lower(): return "BLOCKED", ""
    if status != 200: return "ERROR", f"HTTP {status}"
    if re.search(r"Currently unavailable|currently unavailable|This title is not currently available", body): return "UNAVAILABLE", ""
    if "productTitle" in body or re.search(r"<title>[^<]*Amazon", body): return "OK", ""
    return "BLOCKED", "no product markup"

def discovered_editions(body):
    """ASINs of other formats shown on the page's format strip (best-effort)."""
    seg = body[body.find("tmmSwatches"):body.find("tmmSwatches") + 60000] if "tmmSwatches" in body else ""
    return sorted(set(re.findall(r'/dp/([A-Z0-9]{10})', seg)))

def bare(url):
    """Strip affiliate tags and query strings: checking must never register as an affiliate click."""
    u = url.split("?")[0]
    if "/s?" in url or "/s/" in url:      # search-by-ISBN links: check the search page without the tag
        m = re.search(r"[?&]k=([^&]+)", url); return f"https://www.amazon.co.uk/s?k={m.group(1)}&i=stripbooks" if m else u
    return u

def load_links():
    s, hub = fetch(HUB)
    if s != 200: sys.exit("cannot load hub data")
    b0 = hub.find("const BOOKS = "); b1 = hub.find("\nconst AUTHORS"); a0 = hub.find("const AUTHORS = "); a1 = hub.find("\nconst GCOLS")
    books = json.loads(hub[b0+14:b1].rstrip().rstrip(";")); authors = json.loads(hub[a0+16:a1].rstrip().rstrip(";"))
    links = {}
    for b in books:
        for e in b["editions"]:
            links[bare(e["url"])] = {"kind": "amazon", "book": b["short"], "author": b["author"], "format": e["format"], "asin": e["asin"],
                               "known": sorted(x["asin"] for x in b["editions"])}
        links[f'{b["site"]}books/{b["editions"][0]["asin"]}.html'] = {"kind": "internal", "book": b["short"], "author": b["author"]}
    for a in authors:
        links[a["site"]] = {"kind": "internal", "book": "", "author": a["name"]}
        links[a["site"] + "sitemap.xml"] = {"kind": "internal", "book": "", "author": a["name"]}
    links["https://sdnpublishing.github.io/sdn-publishing/"] = {"kind": "internal", "book": "", "author": "hub"}
    return links

def main():
    sample = int(os.environ.get("SAMPLE", "60")); now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    scope = os.environ.get("SCOPE", "all")                     # all | internal | amazon
    jitter = int(os.environ.get("START_JITTER", "0"))          # seconds: local runs sleep a random 0..jitter before starting
    if jitter: time.sleep(random.uniform(0, jitter))
    links = {u: m for u, m in load_links().items() if scope == "all" or m["kind"] == scope}
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"checks": {}, "issues": {}}
    checks = st["checks"]
    # least-recently-checked first, random tie-break; blocked results count as unchecked
    def key(u): c = checks.get(u, {}); return (c.get("last", "") if c.get("status") != "BLOCKED" else "", random.random())
    order = sorted(links, key=key)[:sample]; random.shuffle(order)
    results = {}
    for i, u in enumerate(order, 1):
        meta = links[u]
        if meta["kind"] == "internal":
            s, _ = fetch(u, "HEAD"); status, note = ("OK" if s == 200 else "NOT_FOUND" if s == 404 else "ERROR"), (f"HTTP {s}" if s != 200 else "")
            found = []; time.sleep(random.uniform(2, 8))
        else:
            s, body = fetch(u); status, note = classify_amazon(s, body)
            if "/s?" in u and status in ("NOT_FOUND", "UNAVAILABLE"): status, note = "OK", "search page"
            found = [x for x in discovered_editions(body) if x not in meta["known"]] if status == "OK" else []
            # irregular trickle: 45–150 s between Amazon requests, and roughly every 8–14 links a 3–7 minute pause
            time.sleep(random.uniform(float(os.environ.get("MIN_GAP", 90)), float(os.environ.get("MAX_GAP", 240))))
            if random.random() < 0.12: time.sleep(random.uniform(300, 900))
        prev = checks.get(u, {})
        strikes = (prev.get("strikes", 0) + 1) if status in ("NOT_FOUND", "UNAVAILABLE", "ERROR") else 0
        checks[u] = {"status": status, "note": note, "last": now, "strikes": strikes, "found": found or prev.get("found", []), **{k: meta[k] for k in ("kind", "book", "author")}, **({"format": meta["format"]} if "format" in meta else {})}
        results[u] = checks[u]; print(f"[{i:02d}/{len(order)}] {status:<11} {meta['author'][:18]:<18} {meta['book'][:34]:<34} {meta.get('format','')}")
    # report + issue body: only links broken on 2+ consecutive checks (avoids one-off blips)
    broken = {u: c for u, c in checks.items() if c["strikes"] >= 2}
    disc = {u: c for u, c in checks.items() if c.get("found")}
    lines = [f"# SDN link check — {now}", "", f"Links known: {len(links)} · checked this run: {len(order)} · broken (2+ strikes): {len(broken)} · unreachable this run (Amazon blocked): {sum(1 for c in results.values() if c['status']=='BLOCKED')}", ""]
    if broken:
        lines += ["## Broken links", "| status | author | book | format | url |", "|---|---|---|---|---|"]
        lines += [f"| {c['status']} {c['note']} | {c['author']} | {c['book']} | {c.get('format','')} | {u} |" for u, c in sorted(broken.items(), key=lambda x: x[1]['author'])]
    if disc:
        lines += ["", "## Editions on Amazon not linked on the site (discovered from product pages)", "| author | book | linked ASIN | discovered ASINs |", "|---|---|---|---|"]
        lines += [f"| {c['author']} | {c['book']} | {u.split('/dp/')[1][:10] if '/dp/' in u else ''} | {', '.join(c['found'])} |" for u, c in sorted(disc.items(), key=lambda x: x[1]['author'])]
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines)); json.dump(st, open(STATE, "w"), indent=1)
    # issue via GitHub API (token from the workflow); one open issue updated in place
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if tok and repo and (broken or disc):
        h = {"Authorization": f"token {tok}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json", "User-Agent": "SDN-LinkCheck"}
        title = f"Link check: {len(broken)} broken, {len(disc)} books with unlinked editions"; body = "\n".join(lines)
        num = st["issues"].get("open")
        if num:
            req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues/{num}", data=json.dumps({"title": title, "body": body}).encode(), method="PATCH", headers=h)
        else:
            req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues", data=json.dumps({"title": title, "body": body, "labels": ["linkcheck"]}).encode(), method="POST", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read()); st["issues"]["open"] = j["number"]; json.dump(st, open(STATE, "w"), indent=1); print("issue", j["number"], "updated" if num else "opened")
        except Exception as e: print("issue update failed:", e)
    print(f"done: {len(broken)} broken, {len(disc)} with discovered editions")

if __name__ == "__main__": main()
