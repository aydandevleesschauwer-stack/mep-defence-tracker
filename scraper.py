"""
MEP Defence Lobbying Tracker — scraper.py
==========================================
Fetches MEP meeting disclosures from the European Parliament and filters
them against your list of defence firms.

Two data sources are used:
  1. EP Open Data API (JSON-LD format) — for the MEP list
  2. EP website MEP meeting pages — for the actual meeting data
     (more reliable than the API for meetings)

How to run locally:
  pip install requests rapidfuzz beautifulsoup4 lxml
  python scraper.py
"""

import csv
import json
import time
import os
import re
import requests
from rapidfuzz import fuzz
from bs4 import BeautifulSoup

# ─── Configuration ────────────────────────────────────────────────────────────
def slugify(name):
    return name.upper().replace(" ", "_")
FUZZY_THRESHOLD  = 85
REQUEST_DELAY    = 1.0
OUTPUT_FILE      = os.path.join("data", "meetings.json")
EP_API           = "https://data.europarl.europa.eu/api/v2"
MEP_MEETINGS_URL = "https://www.europarl.europa.eu/meps/en/{mep_id}/{slug}/meetings/past"

# ─── Step 1: Load firm list ────────────────────────────────────────────────────

def load_firms(filepath="firms.csv"):
    firms = {}
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name    = row["name"].strip()
            aliases = [a.strip() for a in row.get("aliases", "").split(",") if a.strip()]
            firms[name] = [name] + aliases
    print(f"Loaded {len(firms)} firms from firms.csv")
    return firms

# ─── Step 2: Fetch MEP list ────────────────────────────────────────────────────

def fetch_all_meps():
    """
    Tries the EP Open Data API first (requires application/ld+json).
    Falls back to scraping the EP website MEP list if the API fails.
    """
    print("Fetching MEP list from EP Open Data API...")
    url     = f"{EP_API}/meps"
    headers = {"Accept": "application/ld+json"}
    params  = {"parliamentary-term": "10", "limit": 705, "offset": 0}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        meps = data.get("data", data.get("@graph", []))
        if meps:
            print(f"Found {len(meps)} MEPs via API")
            return meps
        raise ValueError("Empty response from API")
    except Exception as e:
        print(f"API failed ({e}), falling back to EP website MEP list...")
        return fetch_meps_from_website()

def fetch_meps_from_website():
    url  = "https://www.europarl.europa.eu/meps/en/full-list/all"
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    meps = []
    seen = set()
    for a in soup.select("a[href*='/meps/en/']"):
        href = a.get("href", "")
        m    = re.search(r"/meps/en/(\d+)/", href)
        if not m:
            continue
        mep_id = m.group(1)
        if mep_id in seen:
            continue
        seen.add(mep_id)
        name_tag = a.select_one(".erpl_title-h3, .ep_name, strong")
        name = name_tag.get_text(strip=True) if name_tag else a.get_text(strip=True)[:60]
        if name and len(name) > 2:
            meps.append({"identifier": mep_id, "label": [{"value": name}], "country": "", "group": ""})
    print(f"Found {len(meps)} MEPs from EP website")
    return meps

# ─── Step 3: Scrape meetings for one MEP ──────────────────────────────────────

def fetch_mep_meetings_html(mep_id, mep_name):
    slug = slugify(mep_name)
url = MEP_MEETINGS_URL.format(mep_id=mep_id, slug=slug)
try:
        resp = requests.get(url, timeout=30,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; research-scraper)"})
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Warning: could not fetch meetings for {mep_id}: {e}")
        return []

    soup     = BeautifulSoup(resp.text, "lxml")
    meetings = []

    entries = (soup.select("div.erpl_document") or
               soup.select("div[class*='meeting']") or
               soup.select("article") or
               soup.select("div.ep-a_product"))

    for entry in entries:
        date_tag  = entry.select_one("time") or entry.select_one("[class*='date']")
        date      = date_tag.get("datetime", date_tag.get_text(strip=True)) if date_tag else ""
        topic_tag = entry.select_one("h3") or entry.select_one("h4") or entry.select_one("[class*='title']")
        topic     = topic_tag.get_text(strip=True) if topic_tag else ""
        orgs      = []
        for tag in entry.select("[class*='org'], [class*='institution'], li"):
            text = tag.get_text(strip=True)
            if len(text) > 3 and not re.match(r"^\d{1,2}[./]\d", text):
                orgs.append(text)
        if not orgs and topic:
            orgs = [topic]
        meetings.append({"date": date, "topic": topic, "organisations": list(set(orgs))})

    return meetings

# ─── Step 4: Fuzzy-match organisations against firm list ──────────────────────

def match_firms(org_names, firms, threshold=FUZZY_THRESHOLD):
    matched = []
    seen    = set()
    for org in org_names:
        org_clean = org.strip().lower()
        for canonical, search_terms in firms.items():
            if canonical in seen:
                continue
            for term in search_terms:
                if fuzz.token_set_ratio(org_clean, term.lower()) >= threshold:
                    matched.append({"canonical_firm": canonical, "matched_text": org})
                    seen.add(canonical)
                    break
    return matched

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_mep_id(mep):
    return str(mep.get("identifier", mep.get("id", ""))).split("/")[-1]

def get_mep_name(mep):
    labels = mep.get("label", [])
    if isinstance(labels, list) and labels:
        item = labels[0]
        return item.get("value", item) if isinstance(item, dict) else str(item)
    if isinstance(labels, str):
        return labels
    fn = mep.get("familyName", "")
    gn = mep.get("givenName", "")
    return f"{gn} {fn}".strip() or str(mep.get("id", "unknown"))

# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    os.makedirs("data", exist_ok=True)
    firms = load_firms("firms.csv")
    meps  = fetch_all_meps()

    all_matches = []
    total_meetings_checked = 0

    for i, mep in enumerate(meps):
        mep_id   = get_mep_id(mep)
        mep_name = get_mep_name(mep)
        if not mep_id or not mep_id.isdigit():
            continue
        print(f"[{i+1}/{len(meps)}] {mep_name} (ID: {mep_id})")

       meetings = fetch_mep_meetings_html(mep_id, mep_name)
        total_meetings_checked += len(meetings)

        for meeting in meetings:
            matched = match_firms(meeting.get("organisations", []), firms)
            if matched:
                all_matches.append({
                    "mep_id":            mep_id,
                    "mep_name":          mep_name,
                    "mep_country":       mep.get("country", ""),
                    "mep_group":         mep.get("group", ""),
                    "meeting_date":      meeting.get("date", ""),
                    "meeting_topic":     meeting.get("topic", ""),
                    "all_organisations": meeting.get("organisations", []),
                    "matched_firms":     matched,
                    "source_url":        MEP_MEETINGS_URL.format(mep_id=mep_id)
                })
                print(f"  ✓ {[m['canonical_firm'] for m in matched]}")

        time.sleep(REQUEST_DELAY)

    output = {
        "generated_at":           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_meps_checked":     len(meps),
        "total_meetings_checked": total_meetings_checked,
        "total_matches":          len(all_matches),
        "meetings":               all_matches
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Found {len(all_matches)} matching meetings.")
    print(f"Results saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    run()
