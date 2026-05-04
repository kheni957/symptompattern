import requests
import time
import pandas as pd
from datetime import datetime

# ===========================================================
# BASE ENGINE
# ===========================================================

class BaseEngine:
    name = "base"

    def fetch(self, keywords: list, target: int = 50) -> list:
        raise NotImplementedError

    def _quality_check(self, text, keywords):
        text = text.lower()
        return any(kw.lower() in text for kw in keywords) and len(text) > 60


# ===========================================================
# REDDIT ENGINE
# ===========================================================

class RedditEngine(BaseEngine):
    name = "Reddit"

    SUBREDDITS = [
        "AskDocs", "DiagnoseMe", "medical_advice", "Longcovid",
        "covidlonghaulers", "cfs", "Fibromyalgia", "chronicpain",
        "lupus", "autoimmune", "Lyme", "ehlersdanlos", "POTS"
    ]

    def fetch(self, keywords: list, target: int = 70) -> list:
        query = "+".join(keywords[:3])  # use first 3 keywords for query
        session = requests.Session()
        session.headers.update({"User-Agent": "HealthWatchScraper/1.0"})
        posts = []

        for sub in self.SUBREDDITS:
            if len(posts) >= target:
                break
            try:
                url = f"https://www.reddit.com/r/{sub}/search.json?q={query}&sort=new&limit=25&restrict_sr=1"
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
                    full_text = (title + " " + selftext).strip()
                    if self._quality_check(full_text, keywords):
                        posts.append({
                            "date":   pd.to_datetime(p.get("created_utc", 0), unit='s').strftime("%Y-%m-%d"),
                            "source": self.name,
                            "title":  title,
                            "text":   full_text,
                            "url":    "https://reddit.com" + p.get("permalink", "")
                        })
            except Exception:
                continue

        return posts


# ===========================================================
# OPENFDA ENGINE
# ===========================================================

class OpenFDAEngine(BaseEngine):
    name = "OpenFDA"

    def fetch(self, keywords: list, target: int = 70) -> list:
        medical_terms = keywords + ["pyrexia", "asthenia", "malaise", "myalgia"]
        searches = [f"patient.reaction.reactionmeddrapt:{kw.replace(' ', '+')}"
                    for kw in keywords[:5]]
        posts = []

        for search in searches:
            if len(posts) >= target:
                break
            try:
                url = f"https://api.fda.gov/drug/event.json?search={search}&limit=25"
                r = requests.get(url, timeout=12)
                time.sleep(1)
                if r.status_code != 200:
                    continue
                for result in r.json().get("results", []):
                    if len(posts) >= target:
                        break
                    reactions  = result.get("patient", {}).get("reaction", [])
                    drugs      = result.get("patient", {}).get("drug", [])
                    reaction_text = ", ".join([rx.get("reactionmeddrapt", "").lower() for rx in reactions])
                    drug_text     = ", ".join([d.get("medicinalproduct", "").lower() for d in drugs])
                    serious       = result.get("serious", 0)
                    full_text = (
                        f"patient reported reactions: {reaction_text}. "
                        f"drugs taken: {drug_text}. "
                        f"outcome: {'serious adverse event' if serious == 1 else 'non-serious'}. "
                        f"duration unknown since months of treatment."
                    )
                    receipt_date = result.get("receiptdate", "20240101")
                    try:
                        date_str = datetime.strptime(receipt_date, "%Y%m%d").strftime("%Y-%m-%d")
                    except:
                        date_str = "2024-01-01"
                    has_kw = any(w in full_text.lower() for w in medical_terms)
                    if has_kw and len(full_text) > 60:
                        posts.append({
                            "date":   date_str,
                            "source": self.name,
                            "title":  f"FDA report: {reaction_text[:80]}",
                            "text":   full_text,
                            "url":    "https://open.fda.gov/apis/drug/event/"
                        })
            except Exception:
                continue

        return posts


# ===========================================================
# PUBMED ENGINE
# ===========================================================

class PubMedEngine(BaseEngine):
    name = "PubMed"

    def fetch(self, keywords: list, target: int = 60) -> list:
        base_query = "+".join(keywords[:3])
        queries = [
            base_query,
            base_query + "+chronic",
            base_query + "+treatment",
            base_query + "+weeks",
            base_query + "+syndrome",
        ]
        posts = []

        for query in queries:
            if len(posts) >= target:
                break
            try:
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
                fetch_url = (
                    f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                    f"?db=pubmed&id={','.join(ids)}&rettype=abstract&retmode=text"
                )
                r2 = requests.get(fetch_url, timeout=10)
                time.sleep(0.4)
                if r2.status_code != 200:
                    continue
                for article in r2.text.strip().split("\n\n\n"):
                    if len(posts) >= target:
                        break
                    text  = article.strip()
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    title = lines[0][:120] if lines else "PubMed Abstract"
                    if self._quality_check(text, keywords) and len(text) > 60:
                        posts.append({
                            "date":   datetime.now().strftime("%Y-%m-%d"),
                            "source": self.name,
                            "title":  title,
                            "text":   text,
                            "url":    "https://pubmed.ncbi.nlm.nih.gov/"
                        })
            except Exception:
                continue

        return posts


# ===========================================================
# TWITTER ENGINE (twitterapi.io)
# ===========================================================

class TwitterEngine(BaseEngine):
    name = "Twitter"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def fetch(self, keywords: list, target: int = 50) -> list:
        if not self.api_key:
            return []

        query = " OR ".join([f'"{kw}"' for kw in keywords[:4]])
        posts = []

        try:
            url = "https://api.twitterapi.io/twitter/tweet/advanced_search"
            headers = {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json"
            }
            params = {
                "query": query + " lang:en",
                "queryType": "Latest",
                "count": min(target, 100)
            }
            r = requests.get(url, headers=headers, params=params, timeout=15)

            if r.status_code != 200:
                return []

            tweets = r.json().get("tweets", r.json().get("data", []))

            for tweet in tweets:
                if len(posts) >= target:
                    break
                text = tweet.get("text", tweet.get("full_text", ""))
                if self._quality_check(text, keywords):
                    created = tweet.get("created_at", datetime.now().isoformat())
                    try:
                        date_str = pd.to_datetime(created).strftime("%Y-%m-%d")
                    except:
                        date_str = datetime.now().strftime("%Y-%m-%d")
                    posts.append({
                        "date":   date_str,
                        "source": self.name,
                        "title":  text[:100],
                        "text":   text,
                        "url":    f"https://twitter.com/i/web/status/{tweet.get('id', '')}"
                    })
        except Exception:
            pass

        return posts


# ===========================================================
# ENGINE REGISTRY — add new engines here
# ===========================================================

ENGINES = {
    "Reddit":  RedditEngine,
    "OpenFDA": OpenFDAEngine,
    "PubMed":  PubMedEngine,
    "Twitter": TwitterEngine,
}

def get_engine(name: str, **kwargs):
    cls = ENGINES.get(name)
    if cls:
        return cls(**kwargs)
    raise ValueError(f"Unknown engine: {name}")