HealthWatch — Setup & Run
1. Install dependencies
    pip install -r requirements.txt

2. Delete old database (fresh start)
    # Windows
    del healthwatch.db
    # Mac / Linux
    rm healthwatch.db
Skip this step if you want to keep your existing projects and signals.

3. Run the app
    streamlit run healthwatch.py
The app opens automatically at http://localhost:8501


First time setup

Go to 📁 Projects → Create New Project
Enter a name, keywords (e.g. ibuprofen, fever, side effects), and pick your data sources
Go to 🔍 Run Analysis → select your project → click Start Fetch & Analysis
Go to 📊 Signals & Trends to view results

Claude AI (optional)
If you have an Anthropic API key, paste it into the sidebar key field before running analysis. Leave it blank to use free heuristic mode — no account needed.
To enable Claude AI, also install:
bashpip install anthropic

Requirements

Python 3.9+
Internet connection (fetches live data from Reddit, PubMed, OpenFDA, ClinicalTrials)
No paid accounts required for standard use