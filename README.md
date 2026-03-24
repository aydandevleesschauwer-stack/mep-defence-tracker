# MEP Defence Industry Meetings Tracker

Tracks meetings between MEPs and European defence industry firms, based on
official disclosures from the European Parliament.

Firms tracked are those registered in the EU Transparency Register with
declared interest in: EDIP, EDF, EDIS, EDIDP, ASAP, EDIRPA, ReArm Europe,
and related European defence industrial policy.

---

## What this does

1. **Fetches** meeting disclosures from the EP's open data API
2. **Filters** them to only show meetings involving your 172 defence firms
3. **Publishes** a searchable dashboard at your GitHub Pages URL
4. **Refreshes automatically** every week via GitHub Actions

---

## Setup guide (step by step, no experience needed)

### Step 1 — Create a GitHub account
Go to https://github.com and create a free account if you don't have one.

### Step 2 — Create a new repository
1. Click the **+** icon (top right) → **New repository**
2. Name it: `mep-defence-tracker`
3. Set it to **Public** (required for free GitHub Pages)
4. Click **Create repository**

### Step 3 — Upload these files
The easiest way for beginners:
1. On your new repo page, click **uploading an existing file**
2. Drag all these files into the upload area:
   - `firms.csv`
   - `scraper.py`
   - `index.html`
   - `README.md`
3. Also upload `.github/workflows/refresh.yml`
   (you may need to create the folder structure manually on GitHub)
4. Click **Commit changes**

### Step 4 — Enable GitHub Pages
1. Go to your repo → **Settings** → **Pages**
2. Under "Source", select **Deploy from a branch**
3. Choose branch: **main**, folder: **/ (root)**
4. Click **Save**
5. Your dashboard will be live at: `https://YOUR-USERNAME.github.io/mep-defence-tracker/`

### Step 5 — Run the scraper for the first time

**Option A: Run it on your own computer (recommended for first run)**

1. Install Python from https://python.org (version 3.9 or newer)
2. Open a terminal / command prompt
3. Navigate to the folder with these files:
   ```
   cd path/to/mep-defence-tracker
   ```
4. Install required packages:
   ```
   pip install requests rapidfuzz
   ```
5. Run the scraper:
   ```
   python scraper.py
   ```
6. It will create `data/meetings.json` — upload this file to your GitHub repo

**Option B: Run it via GitHub Actions (after uploading all files)**

1. Go to your repo → **Actions** tab
2. Click **Refresh MEP meeting data**
3. Click **Run workflow** → **Run workflow**
4. Wait ~5 minutes for it to complete

### Step 6 — Set up automatic weekly refresh
The `.github/workflows/refresh.yml` file handles this automatically once
uploaded. It runs every Monday at 6am UTC and commits updated data.

---

## Updating your firm list

Edit `firms.csv` directly on GitHub (click the file → pencil icon).
Each row has:
- `name` — the canonical firm name (shown in the dashboard)
- `aliases` — comma-separated alternative spellings to also match

---

## File reference

| File | Purpose |
|------|---------|
| `firms.csv` | Your list of 172 firms + aliases |
| `scraper.py` | Fetches EP data, matches firms, outputs JSON |
| `data/meetings.json` | Auto-generated; never edit by hand |
| `index.html` | The dashboard website |
| `.github/workflows/refresh.yml` | Automatic weekly update |

---

## Troubleshooting

**"No meetings found" on the dashboard**
→ The scraper hasn't run yet, or `data/meetings.json` hasn't been uploaded.

**Scraper runs but finds 0 matches**
→ Try lowering `FUZZY_THRESHOLD` in `scraper.py` from 85 to 75.

**A firm is being missed**
→ Add its exact name as it appears in EP records to the `aliases` column in `firms.csv`.

**GitHub Actions fails**
→ Go to Actions tab → click the failed run → read the error log. Most common
  cause is a network timeout — just re-run it.

---

## Data source

European Parliament Open Data Portal: https://data.europarl.europa.eu
Meeting disclosures are published by MEPs under Rule 11 of the EP Rules of Procedure.
