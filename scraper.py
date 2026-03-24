"""
MEP Defence Lobbying Tracker — scraper.py
==========================================
This script fetches meeting disclosures from the European Parliament's
open data portal, filters them against your list of defence firms,
and saves the results to data/meetings.json.

How to run:
  pip install requests rapidfuzz
  python scraper.py

The script will print progress as it runs. It may take a few minutes
to fetch all MEPs and their meetings.
"""

import csv
import json
import time
import re
import os
import requests
from rapidfuzz import fuzz  # for fuzzy name matching

# ─── Configuration ──────────────────────────────────────────────────────────

# How closely a meeting organisation name must match a firm name (0–100).
# 85 catches variations like "Airbus SE" matching "Airbus". Lower = more
# matches but more false positives. Raise to 90 if you get too many wrong hits.
FUZZY_THRESHOLD = 85

# Seconds to wait between API requests — be polite to the EP servers
REQUEST_DELAY = 0.5

# Output file
OUTPUT_FILE = os.path.join("data", "meetings.json")

# EP Open Data API base URL
EP_API = "https://data.europarl.europa.eu/api/v2"

# ─── Step 1: Load your firm list ────────────────────────────────────────────

def load_firms(filepath="firms.csv"):
    """
    Reads firms.csv and builds a flat list of all firm names + their aliases.
    Returns a dict mapping each canonical firm name to its list of search terms.
    """
    firms = {}
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"].strip()
            # Split aliases on comma, clean them up
            aliases = [a.strip() for a in row.get("aliases", "").split(",") if a.strip()]
            # The canonical name itself is always a search term
            firms[name] = [name] + aliases
    print(f"Loaded {len(firms)} firms from firms.csv")
    return firms

# ─── Step 2: Fetch MEP list ──────────────────────────────────────────────────

def fetch_all_meps():
    """
    Fetches the full list of current MEPs from the EP Open Data API.
    Returns a list of dicts with id, name, country, political group.
    """
    print("Fetching MEP list from EP Open Data API...")
    url = f"{EP_API}/meps"
    params = {
        "format": "application/json",
        "parliamentary-term": "10",  # 10th parliamentary term (2024–2029)
        "limit": 1000,
        "offset": 0
    }
    all_meps = []
    while True:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("data", [])
        if not batch:
            break
        all_meps.extend(batch)
        if len(batch) < params["limit"]:
            break
        params["offset"] += params["limit"]
        time.sleep(REQUEST_DELAY)
    print(f"Found {len(all_meps)} MEPs")
    return all_meps

# ─── Step 3: Fetch meetings for one MEP ──────────────────────────────────────

def fetch_mep_meetings(mep_id):
    """
    Fetches the declared meetings for a single MEP.
    The EP publishes these under the 'lobbyists' activities endpoint.
    Returns a list of meeting dicts, or empty list if none/error.
    """
    url = f"{EP_API}/meps/{mep_id}/activities"
    params = {
        "format": "application/json",
        "activity-type": "MEETING",
        "limit": 200
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            return []  # This MEP has no meetings recorded
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except requests.RequestException as e:
        print(f"  Warning: could not fetch meetings for MEP {mep_id}: {e}")
        return []

# ─── Step 4: Match meetings against firm list ────────────────────────────────

def extract_org_names(meeting):
    """
    Pulls the organisation name(s) out of a meeting record.
    The EP API nests this in different places depending on the record type,
    so we check multiple paths.
    """
    orgs = []
    # Primary path: hadMeetingWith → label
    for participant in meeting.get("hadMeetingWith", []):
        label = participant.get("label", "")
        if label:
            orgs.append(label)
        # Sometimes it's nested further
        for org in participant.get("represents", []):
            name = org.get("label", "")
            if name:
                orgs.append(name)
    return orgs

def match_firms(org_names, firms, threshold=FUZZY_THRESHOLD):
    """
    Given a list of organisation names from a meeting, returns any canonical
    firm names from your list that fuzzy-match above the threshold.
    Uses token_set_ratio which handles word-order differences well.
    """
    matched = []
    for org in org_names:
        org_clean = org.strip().lower()
        for canonical_name, search_terms in firms.items():
            for term in search_terms:
                score = fuzz.token_set_ratio(org_clean, term.lower())
                if score >= threshold:
                    matched.append({
                        "canonical_firm": canonical_name,
                        "matched_text": org,
                        "match_score": score
                    })
                    break  # Don't double-count same firm
    return matched

# ─── Step 5: Parse meeting metadata ─────────────────────────────────────────

def parse_meeting(meeting, mep_info, matched_firms):
    """
    Builds a clean, flat record from a raw meeting dict + matched firms.
    This is what gets saved to meetings.json.
    """
    # Date — the API uses ISO 8601 format
    date = meeting.get("date", meeting.get("startDate", ""))

    # Meeting topic/subject
    topic_list = meeting.get("label", [])
    if isinstance(topic_list, list):
        topic = topic_list[0].get("value", "") if topic_list else ""
    else:
        topic = str(topic_list)

    # All organisations mentioned (not just matched ones)
    all_orgs = extract_org_names(meeting)

    return {
        "mep_id": mep_info.get("identifier", ""),
        "mep_name": _get_label(mep_info),
        "mep_country": _get_country(mep_info),
        "mep_group": _get_group(mep_info),
        "meeting_date": date,
        "meeting_topic": topic,
        "all_organisations": all_orgs,
        "matched_firms": matched_firms,
        "source_url": f"https://www.europarl.europa.eu/meps/en/{mep_info.get('identifier', '')}/meetings/past"
    }

def _get_label(obj):
    labels = obj.get("label", [])
    if isinstance(labels, list) and labels:
        return labels[0].get("value", "")
    return str(labels)

def _get_country(mep):
    for c in mep.get("hasMembership", []):
        country = c.get("memberDuring", {}).get("label", "")
        if country:
            return country
    return mep.get("country", "")

def _get_group(mep):
    for c in mep.get("hasMembership", []):
        group = c.get("label", "")
        if group:
            return group
    return ""

# ─── Main runner ─────────────────────────────────────────────────────────────

def run():
    # Make sure output directory exists
    os.makedirs("data", exist_ok=True)

    # Load firms
    firms = load_firms("firms.csv")

    # Fetch MEPs
    meps = fetch_all_meps()

    all_matches = []
    total_meetings_checked = 0

    for i, mep in enumerate(meps):
        mep_id = mep.get("identifier", "")
        mep_name = _get_label(mep)
        print(f"[{i+1}/{len(meps)}] {mep_name} (ID: {mep_id})")

        meetings = fetch_mep_meetings(mep_id)
        total_meetings_checked += len(meetings)

        for meeting in meetings:
            org_names = extract_org_names(meeting)
            matched = match_firms(org_names, firms)
            if matched:
                record = parse_meeting(meeting, mep, matched)
                all_matches.append(record)
                print(f"  ✓ Match: {[m['canonical_firm'] for m in matched]}")

        time.sleep(REQUEST_DELAY)

    # Save results
    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_meps_checked": len(meps),
        "total_meetings_checked": total_meetings_checked,
        "total_matches": len(all_matches),
        "meetings": all_matches
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Found {len(all_matches)} matching meetings.")
    print(f"Results saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    run()
