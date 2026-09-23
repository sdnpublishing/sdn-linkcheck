# sdn-linkcheck

Two halves, deliberately separated:

**GitHub (this repo, free, automatic):** every 3 hours after a random delay, checks a slice of your OWN pages —
author sites, book pages, sitemaps — and raises a GitHub Issue (emails you) when any 404. It never touches Amazon,
so no datacentre traffic ever reaches Amazon from here.

**Your PC (residential address, deliberately low volume):** the same `linkcheck.py` with `SCOPE=amazon` checks bare
product pages — affiliate tag stripped, so a check is never an affiliate click — once a week: 60 links, 90–240 s apart
with occasional 5–15 minute pauses (about three hours, a smaller footprint than an evening's browsing), starting at a
random minute. Every Amazon link is verified roughly once a quarter; discontinued titles are caught sooner by the
monthly KDP archive export → catalogue_sync, which needs no Amazon traffic at all.
Windows Task Scheduler (run as your user, PC must be on):
```
schtasks /create /tn "SDN Amazon links weekly" /tr "cmd /c set SCOPE=amazon&& set SAMPLE=60&& set START_JITTER=5400&& py C:\SDN\linkcheck\linkcheck.py" /sc weekly /d SUN /st 19:00
```
Put `linkcheck.py` in `C:\SDN\linkcheck\`; it keeps its own `linkcheck_state.json` and `linkcheck_report.md` there.
Set `GITHUB_TOKEN` and `GITHUB_REPOSITORY=sdnpublishing/sdn-linkcheck` in the environment if you want the PC runs to
update the same GitHub Issue; otherwise read the local report.

**Better still, when eligible:** Amazon's Product Advertising API is the sanctioned way to verify availability and
list every edition of an ASIN, with no page fetching at all. It needs the Associates account to have made three
qualifying sales in the last 180 days (Associates Central → Tools → Product Advertising API). Say the word and the
checker gets a PA-API mode.

Setup: create a public repo `sdn-linkcheck`, push these files (the deploy script does it), Actions tab → enable
workflows → run "SDN link check" once by hand.
