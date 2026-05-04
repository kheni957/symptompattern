# HealthWatch — Patient Signal Monitor

Real-Time Social Listening for Patient Experience & Safety Signals

---

## Requirements

- Python 3.9 or higher
- pip

---

## Installation

**1. Save these two files in the same folder:**
- `healthwatch.py`
- `requirements.txt`

**2. Install dependencies:**

```bash
pip install -r requirements.txt
```

`requirements.txt` contents:
```
streamlit>=1.32.0
pandas>=2.0.0
matplotlib>=3.7.0
requests>=2.31.0
beautifulsoup4>=4.12.0
python-dotenv>=1.0.0
```

---

## Running the App

```bash
streamlit run healthwatch.py
```

The app will open automatically in your browser at `http://localhost:8501`.

---

## Fresh Start (Recommended on First Run)

If you have a leftover `healthwatch.db` from a previous session, delete it before starting:

**Mac / Linux:**
```bash
rm healthwatch.db
streamlit run healthwatch.py
```

**Windows:**
```bash
del healthwatch.db
streamlit run healthwatch.py
```

The database is recreated automatically on startup.

---

## Data Sources

| Source | Type | Notes |
|--------|------|-------|
| Reddit | Patient forums | No key required |
| OpenFDA | FDA adverse event reports | No key required |
| ClinicalTrials | Completed clinical studies | No key required |
| MedlinePlus | NIH health topics | No key required |

All sources are free and require no API keys or accounts.

---

## Optional: Claude AI Analysis

By default the app runs in **heuristic mode** (free, no key needed).

To enable Claude AI-powered analysis:

1. Get an API key from [console.anthropic.com](https://console.anthropic.com)
2. Paste it into the **Anthropic API Key** field in the sidebar
3. Check **Enable Claude AI Analysis**

The key is session-only and never saved to disk.

---

## Getting Started

1. Go to **📁 Projects** → create a project with keywords (e.g. `ibuprofen, side effects, pain`)
2. Select data sources (Reddit + OpenFDA recommended for starters)
3. Go to **🔍 Run Analysis** → select your project → click **Start Fetch & Analysis**
4. View results in **📊 Signals & Trends**

---

## CSV Upload (Offline Analysis)

Go to **🔍 Run Analysis → Upload CSV tab** to analyse your own data without fetching live sources. The CSV needs at least a title and body column — all other columns are optional.

---

## Troubleshooting

**App won't start** — make sure all packages installed without errors: `pip install -r requirements.txt`

**No signals found** — try broader keywords (single words like `ibuprofen` work better than phrases)

**Reddit returns 0 posts** — Reddit rate-limits aggressively; wait 60 seconds and try again

**Database errors** — delete `healthwatch.db` and restart