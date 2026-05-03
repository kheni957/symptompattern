import requests
import pandas as pd

def fetch_reddit_posts(query="fever", limit=50):
    url = f"https://www.reddit.com/search.json?q={query}&limit={limit}"
    
    headers = {"User-Agent": "health-risk-app"}

    response = requests.get(url, headers=headers)
    data = response.json()

    posts = []
    for post in data["data"]["children"]:
        p = post["data"]
        posts.append({
            "date": pd.to_datetime(p["created_utc"], unit='s'),
            "text": p["title"] + " " + (p.get("selftext") or "")
        })

    return pd.DataFrame(posts)