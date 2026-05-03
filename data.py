import requests
import pandas as pd
import os
from datetime import datetime
import time

# ---------------------------
# Keywords
# ---------------------------

symptoms          = ["fever", "fatigue", "pain", "chills", "nausea", "weak", "headache"]
worsening_words   = ["worse", "not improving", "deteriorating"]
duration_words    = ["days", "weeks", "months", "still", "since"]
treatment_failure = ["not working", "no effect", "not helping"]
positive_words    = ["better", "improving", "recovered"]

def quality_check(text):
    has_symptom = any(w in text for w in symptoms)
    has_context = any(w in text for w in duration_words + worsening_words + treatment_failure)
    long_enough = len(text) > 60
    return has_symptom and has_context and long_enough

# ===========================================================
# 1. REDDIT (70 posts)
# ===========================================================

def fetch_reddit(target=70):
    print("\n📥 Fetching from Reddit...")
    subreddits = [
        "AskDocs", "DiagnoseMe", "medical_advice",
        "Longcovid", "covidlonghaulers", "cfs",
        "Fibromyalgia", "chronicpain"
    ]
    session = requests.Session()
    session.headers.update({"User-Agent": "HealthRiskScraper/1.0"})
    posts = []

    for sub in subreddits:
        if len(posts) >= target:
            break
        try:
            url = f"https://www.reddit.com/r/{sub}/search.json?q=fever+fatigue&sort=new&limit=25&restrict_sr=1"
            r = session.get(url, timeout=10)
            time.sleep(1.5)
            if r.status_code == 429:
                time.sleep(10)
                r = session.get(url, timeout=10)
            if r.status_code != 200:
                continue
            for post in r.json().get("data", {}).get("children", []):
                if len(posts) >= target:
                    break
                p        = post.get("data", {})
                title    = p.get("title", "")
                selftext = p.get("selftext", "")
                if selftext in ["[removed]", "[deleted]", ""]:
                    continue
                full_text = (title + " " + selftext).strip().lower()
                if quality_check(full_text):
                    posts.append({
                        "date":   pd.to_datetime(p.get("created_utc", 0), unit='s').strftime("%Y-%m-%d"),
                        "source": "Reddit",
                        "title":  title,
                        "text":   full_text,
                        "url":    "https://reddit.com" + p.get("permalink", "")
                    })
        except Exception as e:
            print(f"  Error r/{sub}: {e}")

    print(f"  ✅ Reddit: {len(posts)} posts")
    return posts


# ===========================================================
# 2. OpenFDA — adverse event reports (70 posts)
# ===========================================================

def fetch_openfda(target=70):
    print("\n📥 Fetching from OpenFDA...")
    searches = [
        "patient.reaction.reactionmeddrapt:fever",
        "patient.reaction.reactionmeddrapt:fatigue",
        "patient.reaction.reactionmeddrapt:pyrexia",
        "patient.reaction.reactionmeddrapt:chills",
        "patient.reaction.reactionmeddrapt:asthenia",
    ]

    posts = []

    for search in searches:
        if len(posts) >= target:
            break
        try:
            url = f"https://api.fda.gov/drug/event.json?search={search}&limit=25"
            r = requests.get(url, timeout=12)
            time.sleep(1)
            if r.status_code != 200:
                print(f"  OpenFDA failed: {r.status_code}")
                continue

            for result in r.json().get("results", []):
                if len(posts) >= target:
                    break

                # all reactions for this report
                reactions = result.get("patient", {}).get("reaction", [])
                reaction_list = [rx.get("reactionmeddrapt", "").lower() for rx in reactions]
                reaction_text = ", ".join(reaction_list)

                # drugs involved
                drugs = result.get("patient", {}).get("drug", [])
                drug_names = [d.get("medicinalproduct", "").lower() for d in drugs]
                drug_text  = ", ".join(drug_names)

                # outcome
                serious = result.get("serious", 0)
                outcome_text = "serious adverse event" if serious == 1 else "non-serious event"

                full_text = (
                    f"patient reported reactions: {reaction_text}. "
                    f"drugs taken: {drug_text}. "
                    f"outcome: {outcome_text}. "
                    f"duration unknown since months of treatment."
                )

                receipt_date = result.get("receiptdate", "20240101")
                try:
                    date_str = datetime.strptime(receipt_date, "%Y%m%d").strftime("%Y-%m-%d")
                except:
                    date_str = "2024-01-01"

                # relaxed check — FDA data has reactions not full sentences
                has_symptom = any(w in full_text for w in symptoms + ["pyrexia", "asthenia", "malaise", "myalgia"])
                if has_symptom and len(full_text) > 60:
                    posts.append({
                        "date":   date_str,
                        "source": "OpenFDA",
                        "title":  f"FDA report: {reaction_text[:80]}",
                        "text":   full_text,
                        "url":    "https://open.fda.gov/apis/drug/event/"
                    })

        except Exception as e:
            print(f"  Error: {e}")

    print(f"  ✅ OpenFDA: {len(posts)} posts")
    return posts


# ===========================================================
# 3. PubMed — research abstracts (60 posts)
# ===========================================================

def fetch_pubmed(target=60):
    print("\n📥 Fetching from PubMed...")
    queries = [
        "persistent+fever+fatigue",
        "low+grade+fever+chronic+fatigue",
        "post+viral+fatigue+fever",
        "fever+fatigue+treatment",
        "fever+fatigue+weeks",
        "fever+fatigue+pain+weeks",
        "chronic+fever+fatigue+syndrome",
        "unexplained+fever+fatigue",
    ]

    posts = []

    for query in queries:
        if len(posts) >= target:
            break
        try:
            # Step 1: get IDs
            search_url = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
                f"?db=pubmed&term={query}&retmax=15&retmode=json"
            )
            r = requests.get(search_url, timeout=10)
            time.sleep(0.4)
            if r.status_code != 200:
                continue

            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                continue

            # Step 2: fetch abstracts
            fetch_url = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                f"?db=pubmed&id={','.join(ids)}&rettype=abstract&retmode=text"
            )
            r2 = requests.get(fetch_url, timeout=10)
            time.sleep(0.4)
            if r2.status_code != 200:
                continue

            # each article separated by blank lines
            articles = r2.text.strip().split("\n\n\n")

            for article in articles:
                if len(posts) >= target:
                    break
                text  = article.strip().lower()
                lines = [l.strip() for l in article.split("\n") if l.strip()]
                title = lines[0][:120] if lines else "PubMed Abstract"

                # relaxed check for abstracts
                has_symptom = any(w in text for w in symptoms + ["pyrexia", "malaise", "myalgia", "asthenia"])
                long_enough = len(text) > 60
                if has_symptom and long_enough:
                    posts.append({
                        "date":   datetime.now().strftime("%Y-%m-%d"),
                        "source": "PubMed",
                        "title":  title,
                        "text":   text,
                        "url":    "https://pubmed.ncbi.nlm.nih.gov/"
                    })

        except Exception as e:
            print(f"  Error: {e}")

    print(f"  ✅ PubMed: {len(posts)} posts")
    return posts


# ===========================================================
# MAIN
# ===========================================================

reddit_posts = fetch_reddit(target=70)
fda_posts    = fetch_openfda(target=70)
pubmed_posts = fetch_pubmed(target=60)

all_posts = reddit_posts + fda_posts + pubmed_posts
df = pd.DataFrame(all_posts)
df = df.drop_duplicates(subset=['text'])
df = df.reset_index(drop=True)

filename = f"combined_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
df.to_csv(filename, index=False)

print(f"\n{'='*50}")
print(f"✅ Total posts saved : {len(df)}")
print(f"📄 File             : {os.path.abspath(filename)}")
print(f"\nSource breakdown:")
print(df['source'].value_counts().to_string())
print(f"\nSample posts:")
print(df[['date', 'source', 'title']].head(10).to_string())