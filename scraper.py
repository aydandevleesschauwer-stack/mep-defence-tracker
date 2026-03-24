import csv
import json
import time
import os
import re
import requests
from rapidfuzz import fuzz
from bs4 import BeautifulSoup

# ─── CONFIG ─────────────────────────────────────────

FUZZY_THRESHOLD = 85
REQUEST_DELAY = 1.0
OUTPUT_FILE = os.path.join("data", "meetings.json")

# ─── HELPERS ───────────────────────────────────────

def slugify(name):
    return (
        name.upper()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("'", "")
    )

def get_mep_id(mep):
    return str(mep.get("identifier", "")).split("/")[-1]

def get_mep_name(mep):
    labels = mep.get("label", [])
    if isinstance(labels, list) and labels:
        item = labels[0]
        return item.get("value", "") if isinstance(item, dict) else str(item)
    return "UNKNOWN"

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

# ─── FETCH MEPS ────────────────────────────────────

def fetch_all_meps():
    url = "https://data.europarl.europa.eu/api/v2/meps"
    params = {"parliamentary-term": "10", "limit": 705}

    try:
        resp = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        meps = data.get("data", [])
        print(f"Found {len(meps)} MEPs")
        return meps
    except Exception as e:
        print("Failed to fetch MEPs:", e)
        return []

# ─── FETCH MEETINGS ────────────────────────────────

def fetch_mep_meetings(mep_id, mep_name):
    slug = slugify(mep_name)
    url = f"https://www.europarl.europa.eu/meps/en/{mep_id}/{slug}/meetings/past"

    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            print(f"  Skipping {mep_id} ({resp.status_code})")
            return []
    except requests.RequestException as e:
        print(f"  Error for {mep_id}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    meetings = []

    entries = soup.select("div.erpl_document")

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
    meps = fetch_all_meps()

    all_matches = []

    for i, mep in enumerate(meps):
        mep_id = get_mep_id(mep)
        mep_name = get_mep_name(mep)

        if not mep_id.isdigit():
            continue

        print(f"[{i+1}/{len(meps)}] {mep_name} ({mep_id})")

        meetings = fetch_mep_meetings(mep_id, mep_name)

        for meeting in meetings:
            matched = match_firms(meeting["organisations"], firms)
            if matched:
                all_matches.append({
                    "mep_id": mep_id,
                    "mep_name": mep_name,
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

    print("Done!")

# ─── RUN ───────────────────────────────────────────

if __name__ == "__main__":
    run()
