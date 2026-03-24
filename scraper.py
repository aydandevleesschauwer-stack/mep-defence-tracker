import csv
import json
import os
import time
import requests
from rapidfuzz import fuzz
from bs4 import BeautifulSoup

# ─── CONFIG ─────────────────────────────────────────
FUZZY_THRESHOLD = 85
REQUEST_DELAY = 1.0
OUTPUT_FILE = os.path.join("data", "meetings.json")
MEP_LIST_URL = "https://www.europarl.europa.eu/meps/en/full-list/all"

# ─── HELPERS ───────────────────────────────────────
def slugify(name):
    return (
        name.upper()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("'", "")
    )

# ─── LOAD FIRMS ────────────────────────────────────
def load_firms(filepath="firms.csv"):
    firms = {}
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"].strip()
            aliases = [a.strip() for a in row.get("aliases", "").split(",") if a.strip()]
            firms[name] = [name] + aliases
    print(f"Loaded {len(firms)} firms")
    return firms

# ─── FETCH MEP LIST ───────────────────────────────
def fetch_meps():
    try:
        resp = requests.get(MEP_LIST_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print("Failed to fetch MEP list:", e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    meps = []

    # Elke MEP staat in een <a> binnen div.erpl_mep
    for a in soup.select("div.erpl_mep a"):
        href = a.get("href")
        if not href or "/meetings/past" in href:
            continue
        parts = href.strip("/").split("/")
        if len(parts) >= 4:
            mep_id = parts[-2]
            mep_slug = parts[-1]
            mep_name = a.get_text(strip=True)
            meps.append({"id": mep_id, "slug": mep_slug, "name": mep_name})
    print(f"Found {len(meps)} MEPs")
    return meps

# ─── FETCH MEETINGS ───────────────────────────────
def fetch_mep_meetings(mep):
    url = f"https://www.europarl.europa.eu/meps/en/{mep['id']}/{mep['slug']}/meetings/past"
    print(f"Fetching meetings for {mep['name']} ({mep['id']}) -> {url}")
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            print(f"  Skipping {mep['id']} ({resp.status_code})")
            return []
    except requests.RequestException as e:
        print(f"  Error for {mep['id']}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    meetings = []

    entries = soup.select("div.erpl_document")
    if not entries:
        print(f"  No meetings found for {mep['name']} ({mep['id']})")

    for entry in entries:
        date_tag = entry.select_one("time")
        topic_tag = entry.select_one("h3")
        date = date_tag.get_text(strip=True) if date_tag else ""
        topic = topic_tag.get_text(strip=True) if topic_tag else ""

        orgs = []
        for tag in entry.select("li"):
            text = tag.get_text(strip=True)
            if len(text) > 3:
                orgs.append(text)
        if not orgs and topic:
            orgs = [topic]

        meetings.append({
            "date": date,
            "topic": topic,
            "organisations": list(set(orgs))
        })

    print(f"  Found {len(meetings)} meetings for {mep['name']}")
    return meetings

# ─── MATCH FIRMS ───────────────────────────────────
def match_firms(org_names, firms):
    matched = []
    seen = set()
    for org in org_names:
        org_clean = org.lower()
        for canonical, terms in firms.items():
            if canonical in seen:
                continue
            for term in terms:
                if fuzz.token_set_ratio(org_clean, term.lower()) >= FUZZY_THRESHOLD:
                    matched.append({
                        "canonical_firm": canonical,
                        "matched_text": org
                    })
                    seen.add(canonical)
                    break
    return matched

# ─── MAIN ──────────────────────────────────────────
def run():
    os.makedirs("data", exist_ok=True)
    firms = load_firms()
    meps = fetch_meps()
    all_matches = []

    for i, mep in enumerate(meps):
        print(f"[{i+1}/{len(meps)}] {mep['name']} ({mep['id']})")
        meetings = fetch_mep_meetings(mep)
        for meeting in meetings:
            matched = match_firms(meeting["organisations"], firms)
            if matched:
                all_matches.append({
                    "mep_id": mep["id"],
                    "mep_name": mep["name"],
                    "meeting_date": meeting["date"],
                    "meeting_topic": meeting["topic"],
                    "matched_firms": matched
                })
                print("  ✓ match")
        time.sleep(REQUEST_DELAY)

    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_matches": len(all_matches),
        "meetings": all_matches
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print("Done! JSON written to", OUTPUT_FILE)

if __name__ == "__main__":
    run()
