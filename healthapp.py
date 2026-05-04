"""
HealthWatch — Patient Signal Monitor
Real-Time Social Listening for Patient Experience & Safety Signals
"""

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import requests
import sqlite3
import json
import re
import time
import os
import random
from datetime import datetime, timedelta
from collections import Counter
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup

# ===========================================================
# CONFIG
# ===========================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "healthwatch.db")

SAFETY_KEYWORDS = [
    "hospitalized", "hospitalised", "went to the er", "called 911",
    "overdose", "suicide", "suicidal", "self-harm", "self harm",
    "died", "death", "fatal", "anaphylaxis", "anaphylactic",
    "seizure", "stroke", "heart attack", "stopped breathing", "unconscious",
    "icu", "intensive care", "life-threatening", "life threatening",
]
MODERATE_AE_WORDS = [
    "chest pain", "allergic reaction", "emergency", "hospitalization",
    "shortness of breath", "severe", "unbearable", "excruciating",
    "vision loss", "hearing loss", "paralysis", "blood clot",
]
PII_PATTERNS = {
    "email":             r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "phone_international": r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{2,5}[\s\-]?\d{2,5}[\s\-]?\d{0,5}",
    "name":              r"\b(?:my name is|call me)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+",
    "dob":               r"\b(?:born|dob|date of birth|d\.o\.b|birthday)[:\s]+(?:\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2},?\s+\d{4})",
    "us_ssn":            r"\b\d{3}-\d{2}-\d{4}\b",
    "us_phone":          r"\b(?:\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]\d{4})\b",
    "us_zip":            r"\b\d{5}(?:-\d{4})?\b",
    "us_address":        r"\b\d{1,5}\s+[A-Za-z0-9\s]{2,30}\s+(?:St(?:reet)?|Ave(?:nue)?|Rd|Road|Blvd|Boulevard|Dr(?:ive)?|Lane|Ln|Way|Ct|Court|Pl(?:ace)?|Terrace|Ter)\b",
    "uk_nino":           r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b",
    "uk_postcode":       r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}\b",
    "uk_phone":          r"\b(?:(?:\+44|0)[\s\-]?(?:7\d{3}|1\d{3}|2\d{3})[\s\-]?\d{3}[\s\-]?\d{3,4})\b",
    "uk_nhs":            r"\b\d{3}[\s\-]\d{3}[\s\-]\d{4}\b",
    "in_aadhaar":        r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
    "in_pan":            r"\b[A-Z]{5}\d{4}[A-Z]\b",
    "in_pincode":        r"\b[1-9]\d{5}\b",
    "in_phone":          r"\b(?:\+91[\s\-]?)?[6-9]\d{9}\b",
    "ca_sin":            r"\b\d{3}-\d{3}-\d{3}\b",
    "ca_postal":         r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b",
    "au_tfn":            r"\b(?:tfn|tax file number)[:\s]+\d{2,3}[\s\-]?\d{3}[\s\-]?\d{3}\b",
    "au_medicare":       r"\b[2-6]\d{9}\b",
    "au_phone":          r"\b(?:\+61[\s\-]?)?0?4\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b",
    "eu_national_id":    r"\b(?:national id|id number|passport|personalausweis|dni|nif|bsn|iban)[:\s#]+[A-Z0-9]{6,20}\b",
    "iban":              r"\b[A-Z]{2}\d{2}[\s]?[A-Z0-9]{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{0,4}[\s]?\d{0,4}\b",
}
PII_CONFIDENCE = {
    "high":   {"email", "us_ssn", "uk_nino", "in_pan", "ca_sin", "au_tfn", "in_aadhaar", "iban", "uk_nhs"},
    "medium": {"phone_international", "us_phone", "uk_phone", "in_phone", "au_phone", "name", "dob", "us_address", "ca_postal", "uk_postcode"},
    "low":    {"us_zip", "in_pincode", "au_medicare", "eu_national_id"},
}

# ===========================================================
# DATABASE
# ===========================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                keywords    TEXT DEFAULT '[]',
                sources     TEXT DEFAULT '[]',
                latency     TEXT DEFAULT 'daily',
                created_at  TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS signals (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id        INTEGER NOT NULL REFERENCES projects(id),
                source            TEXT,
                post_id           TEXT,
                author            TEXT,
                title             TEXT,
                body              TEXT,
                url               TEXT,
                post_date         TEXT,
                fetched_at        TEXT DEFAULT (datetime('now')),
                sentiment         TEXT,
                sentiment_score   REAL,
                sentiment_detail  TEXT,
                risk_level        TEXT,
                risk_score        INTEGER DEFAULT 0,
                risk_reason       TEXT,
                confidence        REAL,
                safety_flag       INTEGER DEFAULT 0,
                safety_reasons    TEXT,
                pii_flagged       INTEGER DEFAULT 0,
                pii_types         TEXT,
                adverse_event     TEXT,
                entities          TEXT,
                topics            TEXT,
                summary           TEXT,
                analyzed_by       TEXT
            );
            CREATE TABLE IF NOT EXISTS source_engines (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                name   TEXT UNIQUE NOT NULL,
                config TEXT DEFAULT '{}'
            );
            INSERT OR IGNORE INTO source_engines (name, config) VALUES
                ('Reddit',         '{"subreddits": ["AskDocs","DiagnoseMe","medical_advice","Longcovid","covidlonghaulers","cfs","Fibromyalgia","chronicpain"], "limit": 25}'),
                ('PubMed',         '{"max_results": 10}'),
                ('OpenFDA',        '{"max_results": 20}'),
                ('ClinicalTrials', '{"max_results": 10}');
        """)

def get_projects():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

def create_project(name, description, keywords, sources, latency="daily"):
    if not name.strip(): raise ValueError("Project name cannot be empty.")
    with get_conn() as conn:
        if conn.execute("SELECT id FROM projects WHERE name=?", (name.strip(),)).fetchone():
            raise ValueError(f"Project '{name.strip()}' already exists.")
        cur = conn.execute(
            "INSERT INTO projects (name, description, keywords, sources, latency) VALUES (?,?,?,?,?)",
            (name.strip(), description, json.dumps(keywords), json.dumps(sources), latency)
        )
        return cur.lastrowid

def update_project(pid, name, description, keywords, sources, latency):
    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET name=?, description=?, keywords=?, sources=?, latency=? WHERE id=?",
            (name, description, json.dumps(keywords), json.dumps(sources), latency, pid)
        )

def delete_project(pid):
    with get_conn() as conn:
        conn.execute("DELETE FROM signals  WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM projects WHERE id=?",         (pid,))

def get_signals(pid, limit=1000):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE project_id=? ORDER BY fetched_at DESC LIMIT ?", (pid, limit)
        ).fetchall()
    return [dict(r) for r in rows]

def save_signals(pid, signals):
    with get_conn() as conn:
        for s in signals:
            try:
                conn.execute("""
                    INSERT INTO signals
                        (project_id, source, post_id, author, title, body, url, post_date,
                         sentiment, sentiment_score, sentiment_detail,
                         risk_level, risk_score, risk_reason, confidence,
                         safety_flag, safety_reasons, pii_flagged, pii_types,
                         adverse_event, entities, topics, summary, analyzed_by)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    pid,
                    s.get("source"), s.get("post_id"), s.get("author"),
                    s.get("title"),  s.get("body"),    s.get("url"), s.get("post_date"),
                    s.get("sentiment"), s.get("sentiment_score"), s.get("sentiment_detail"),
                    s.get("risk_level"), s.get("risk_score", 0), s.get("risk_reason"), s.get("confidence"),
                    int(s.get("safety_flag", 0)), s.get("safety_reasons",""),
                    int(s.get("pii_flagged", 0)), s.get("pii_types",""),
                    s.get("adverse_event",""),
                    json.dumps(s.get("entities", {})),
                    json.dumps(s.get("topics", [])),
                    s.get("summary",""),
                    s.get("analyzed_by","heuristic"),
                ))
            except Exception:
                pass

def get_source_engines():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM source_engines").fetchall()
    return [dict(r) for r in rows]

def add_source_engine(name, config):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO source_engines (name, config) VALUES (?,?)",
                     (name, json.dumps(config)))

# ===========================================================
# ENGINES
# ===========================================================

class BaseEngine(ABC):
    name = "base"
    @abstractmethod
    def fetch(self, keywords: list) -> list: ...
    def _relevant(self, text, keywords):
        t = text.lower()
        return any(k.lower() in t for k in keywords)

class RedditEngine(BaseEngine):
    name = "Reddit"
    HEADERS = {"User-Agent": "HealthWatch/1.0 (patient-signal-monitor)"}
    def __init__(self, subreddits=None, limit=25):
        self.subreddits = subreddits or [
            "AskDocs","DiagnoseMe","medical_advice","Longcovid",
            "covidlonghaulers","cfs","Fibromyalgia","chronicpain",
            "lupus","autoimmune","Lyme","ehlersdanlos","POTS"
        ]
        self.limit = limit
    def fetch(self, keywords):
        posts = []
        query = " OR ".join(keywords[:4])
        for sub in self.subreddits:
            try:
                url  = f"https://www.reddit.com/r/{sub}/search.json"
                resp = requests.get(url, params={"q": query, "sort": "new",
                                                  "limit": self.limit, "restrict_sr": 1},
                                    headers=self.HEADERS, timeout=10)
                if resp.status_code == 429: time.sleep(10); continue
                resp.raise_for_status()
                for child in resp.json().get("data", {}).get("children", []):
                    d     = child.get("data", {})
                    title = d.get("title", "")
                    body  = d.get("selftext", "")
                    if body in ["[removed]", "[deleted]"]: body = ""
                    full  = (title + " " + body).strip()
                    if not self._relevant(full, keywords) or len(full) < 60: continue
                    created = d.get("created_utc", 0)
                    posts.append({
                        "source":    "Reddit",
                        "post_id":   d.get("id",""),
                        "author":    d.get("author","[deleted]"),
                        "title":     title,
                        "body":      body,
                        "url":       f"https://reddit.com{d.get('permalink','')}",
                        "post_date": datetime.utcfromtimestamp(created).strftime("%Y-%m-%d") if created else "",
                    })
                time.sleep(1.2)
            except Exception as e:
                st.warning(f"Reddit r/{sub}: {e}")
        return posts

class PubMedEngine(BaseEngine):
    name = "PubMed"
    def __init__(self, max_results=10):
        self.max_results = max_results
    def fetch(self, keywords):
        posts = []
        for kw in keywords[:3]:
            try:
                sr = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                                   params={"db":"pubmed","term":kw,"retmax":self.max_results,"retmode":"json"},
                                   timeout=10)
                sr.raise_for_status()
                ids = sr.json().get("esearchresult",{}).get("idlist",[])
                if not ids: continue
                fr = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                                   params={"db":"pubmed","id":",".join(ids),"rettype":"abstract","retmode":"xml"},
                                   timeout=15)
                fr.raise_for_status()
                for art in re.findall(r"<PubmedArticle>(.*?)</PubmedArticle>", fr.text, re.DOTALL):
                    pm    = re.search(r"<PMID[^>]*>(\d+)</PMID>", art)
                    ti    = re.search(r"<ArticleTitle>(.*?)</ArticleTitle>", art, re.DOTALL)
                    ab    = re.search(r"<AbstractText[^>]*>(.*?)</AbstractText>", art, re.DOTALL)
                    pmid  = pm.group(1) if pm else str(random.randint(10000,99999))
                    title = re.sub(r"<[^>]+>","", ti.group(1)) if ti else ""
                    body  = re.sub(r"<[^>]+>","", ab.group(1)) if ab else ""
                    full  = (title + " " + body).strip()
                    if not self._relevant(full, keywords): continue
                    posts.append({
                        "source":    "PubMed",
                        "post_id":   f"pubmed_{pmid}",
                        "author":    "PubMed",
                        "title":     title.strip(),
                        "body":      body.strip(),
                        "url":       f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "post_date": datetime.now().strftime("%Y-%m-%d"),
                    })
                time.sleep(0.4)
            except Exception as e:
                st.warning(f"PubMed '{kw}': {e}")
        return posts

class OpenFDAEngine(BaseEngine):
    name = "OpenFDA"
    BASE = "https://api.fda.gov/drug/event.json"
    def __init__(self, max_results=20):
        self.max_results = max_results
    def fetch(self, keywords):
        posts = []
        for kw in keywords[:4]:
            try:
                resp = requests.get(self.BASE, params={
                    "search": f'patient.drug.medicinalproduct:"{kw}"',
                    "limit":  self.max_results,
                }, timeout=15)
                if resp.status_code == 404: continue
                resp.raise_for_status()
                for event in resp.json().get("results", []):
                    patient    = event.get("patient", {})
                    reactions  = patient.get("reaction", [])
                    drugs      = patient.get("drug", [])
                    ae_terms   = ", ".join(r.get("reactionmeddrapt", "") for r in reactions[:5])
                    drug_names = ", ".join(d.get("medicinalproduct", "") for d in drugs[:3])
                    serious    = event.get("serious", 0)
                    rd         = event.get("receiptdate", "")
                    if rd and len(rd) == 8:
                        rd = f"{rd[:4]}-{rd[4:6]}-{rd[6:]}"
                    title = f"FDA AE Report: {drug_names[:60]} - {ae_terms[:60]}"
                    body  = (f"Adverse reactions: {ae_terms}. Drugs: {drug_names}. "
                             f"Serious: {'Yes' if serious else 'No'}. "
                             f"Outcomes: {', '.join(r.get('reactionoutcome','') for r in reactions[:3])}.")
                    uid = event.get("safetyreportid", str(random.randint(100000, 999999)))
                    posts.append({
                        "source":    "OpenFDA",
                        "post_id":   f"fda_{uid}",
                        "author":    "FDA FAERS",
                        "title":     title[:200],
                        "body":      body,
                        "url":       "https://open.fda.gov/apis/drug/event/",
                        "post_date": rd or datetime.now().strftime("%Y-%m-%d"),
                    })
                time.sleep(0.3)
            except Exception as e:
                st.warning(f"OpenFDA '{kw}': {e}")
        return posts

class ClinicalTrialsEngine(BaseEngine):
    name = "ClinicalTrials"
    BASE = "https://clinicaltrials.gov/api/v2/studies"
    def __init__(self, max_results=10):
        self.max_results = max_results
    def fetch(self, keywords):
        posts = []
        for kw in keywords[:3]:
            try:
                resp = requests.get(self.BASE, params={
                    "query.term":           kw,
                    "filter.overallStatus": "COMPLETED",
                    "fields":               "NCTId,BriefTitle,BriefSummary,Condition,InterventionName,StartDate",
                    "pageSize":             self.max_results,
                    "format":               "json",
                }, timeout=15)
                resp.raise_for_status()
                for study in resp.json().get("studies", []):
                    proto   = study.get("protocolSection", {})
                    ident   = proto.get("identificationModule", {})
                    desc    = proto.get("descriptionModule", {})
                    nctid   = ident.get("nctId", "")
                    title   = ident.get("briefTitle", "")
                    summary = desc.get("briefSummary", "")
                    if not self._relevant(title + " " + summary, keywords): continue
                    posts.append({
                        "source":    "ClinicalTrials",
                        "post_id":   f"ct_{nctid}",
                        "author":    "ClinicalTrials.gov",
                        "title":     title[:200],
                        "body":      summary[:800],
                        "url":       f"https://clinicaltrials.gov/study/{nctid}",
                        "post_date": datetime.now().strftime("%Y-%m-%d"),
                    })
                time.sleep(0.3)
            except Exception as e:
                st.warning(f"ClinicalTrials '{kw}': {e}")
        return posts
    

ENGINES = {
    "Reddit":         RedditEngine,
    "PubMed":         PubMedEngine,
    "OpenFDA":        OpenFDAEngine,
    "ClinicalTrials": ClinicalTrialsEngine,
    
}

def get_engine(name):
    if name in ENGINES: return ENGINES[name]()
    raise ValueError(f"Unknown engine: {name}")

# ===========================================================
# SENTIMENT
# ===========================================================

SENTIMENT_LEXICON = {
    "recovered": +3, "cured": +3, "remission": +3, "healed": +3,
    "resolved": +2, "improving": +2, "better": +2, "relief": +2,
    "responding": +2, "effective": +2, "works": +1, "helped": +1,
    "no side effects": +2, "tolerated": +1, "manageable": +1,
    "died": -5, "fatal": -5, "overdose": -5, "suicidal": -5,
    "hospitalized": -4, " icu ": -4, "seizure": -4, "stroke": -4,
    "heart attack": -4, "anaphylaxis": -4,
    "worsening": -3, "deteriorating": -3, "unbearable": -3, "excruciating": -3,
    "not working": -3, "no effect": -3, "failed": -2,
    "worse": -2, "terrible": -2, "horrible": -2, "awful": -2,
    "severe": -2, "dangerous": -2, "adverse": -2,
    "side effect": -1, "nausea": -1, "fatigue": -1, "headache": -1,
    "dizziness": -1, "pain": -1, "discomfort": -1, "worried": -1,
    "scared": -1, "frustrated": -1, "no improvement": -2,
}
NEGATIONS = ["not ", "no ", "never ", "didn't ", "don't ", "doesn't ",
             "wasn't ", "isn't ", "haven't ", "hasn't ", "without "]
SENTIMENT_EMOTIONS = {
    "fear":      ["scared", "terrified", "afraid", "anxious", "worried", "panicked"],
    "despair":   ["hopeless", "desperate", "giving up", "can't take", "no point"],
    "relief":    ["relieved", "finally", "thankfully", "at last", "so glad"],
    "anger":     ["frustrated", "angry", "ridiculous", "unacceptable", "negligent"],
    "hope":      ["hopeful", "optimistic", "fingers crossed", "hopefully", "trying"],
    "confusion": ["confused", "don't understand", "no answers", "mystery", "baffled"],
}

def _is_negated(text, phrase):
    idx = text.find(phrase)
    if idx == -1: return False
    context = text[max(0, idx-30):idx]
    return any(neg in context for neg in NEGATIONS)

def analyze_sentiment(text):
    t = text.lower(); score = 0; hits = []
    for phrase, weight in SENTIMENT_LEXICON.items():
        if phrase in t:
            effective = -weight if _is_negated(t, phrase) else weight
            score += effective; hits.append((phrase, effective))
    norm_score = max(-1.0, min(1.0, score / 10.0))
    label      = "Positive" if norm_score >= 0.2 else ("Negative" if norm_score <= -0.2 else "Neutral")
    emotions   = [emo for emo, words in SENTIMENT_EMOTIONS.items() if any(w in t for w in words)]
    confidence = round(min(0.4 + len(hits) * 0.07, 0.97), 2)
    top_hits   = sorted(hits, key=lambda x: abs(x[1]), reverse=True)[:3]
    detail     = ", ".join([f'"{p}" ({w:+d})' for p, w in top_hits]) if top_hits else "no strong signals"
    return {
        "sentiment":        label,
        "sentiment_score":  round(norm_score, 3),
        "sentiment_detail": f"Score {score:+d} | Signals: {detail}" + (f" | Emotions: {', '.join(emotions)}" if emotions else ""),
        "confidence":       confidence,
    }

# ===========================================================
# ENTITY EXTRACTION
# ===========================================================

DRUG_LIST = ["ibuprofen","paracetamol","acetaminophen","amoxicillin","doxycycline",
             "azithromycin","metformin","prednisone","prednisolone","augmentin",
             "cephalexin","ciprofloxacin","metronidazole","tylenol","motrin","aspirin",
             "naproxen","hydroxychloroquine","remicade","humira","antibiotics",
             "antibiotic","nsaids","antihistamine","sertraline","gabapentin",
             "lisinopril","atorvastatin","omeprazole","levothyroxine"]
CONDITION_LIST = ["fever","fatigue","covid","long covid","fibromyalgia","lupus",
                  "lyme disease","pots","mcas","eds","cfs","me/cfs","chronic fatigue",
                  "arthritis","thyroid","hypothyroidism","anemia","infection",
                  "pneumonia","bronchitis","sinusitis","appendicitis","gastritis",
                  "endometriosis","mononucleosis","sepsis","depression","anxiety",
                  "migraine","diabetes","hypertension","asthma"]
SYMPTOM_LIST = ["fever","fatigue","chills","nausea","vomiting","headache",
                "body aches","muscle pain","joint pain","weakness","dizziness",
                "shortness of breath","chest pain","rash","swollen lymph nodes",
                "night sweats","weight loss","brain fog","palpitations","insomnia",
                "dry mouth","hair loss","numbness","tingling"]

def extract_entities(text):
    t = text.lower()
    entities = {
        "drugs":      [d for d in DRUG_LIST      if d in t],
        "conditions": [c for c in CONDITION_LIST if c in t],
        "symptoms":   [s for s in SYMPTOM_LIST   if s in t],
    }
    durations = re.findall(r"\b(\d+)\s*(day|week|month|year)s?\b", t)
    entities["durations"] = [f"{n} {u}s" for n, u in durations]
    ag = re.findall(r"\b(\d{1,3})\s*(?:year[s]?\s*old|yo|[mf])\b", t)
    entities["age_mentions"] = list(set(ag))
    return entities

# ===========================================================
# PII DETECTION
# ===========================================================

def detect_pii(text):
    found = {}
    for label, pattern in PII_PATTERNS.items():
        try:
            pat = pattern if isinstance(pattern, str) else "".join(pattern)
            matches = re.findall(pat, text, re.IGNORECASE)
            if matches: found[label] = matches
        except re.error:
            pass
    if not found:
        return {"pii_flagged": False, "pii_types": "", "pii_confidence": ""}
    tiered = {"high": [], "medium": [], "low": []}
    for label in found:
        for tier, members in PII_CONFIDENCE.items():
            if label in members: tiered[tier].append(label); break
        else: tiered["medium"].append(label)
    parts = []
    if tiered["high"]:   parts.append("HIGH: "   + ", ".join(tiered["high"]))
    if tiered["medium"]: parts.append("MEDIUM: " + ", ".join(tiered["medium"]))
    if tiered["low"]:    parts.append("LOW: "    + ", ".join(tiered["low"]))
    return {
        "pii_flagged":    True,
        "pii_types":      "; ".join(parts),
        "pii_confidence": "high" if tiered["high"] else ("medium" if tiered["medium"] else "low"),
    }

# ===========================================================
# RISK SCORING
# ===========================================================

SYMPTOM_KW   = ["fever","fatigue","pain","chills","nausea","weak","headache","vomiting","rash"]
WORSENING_KW = ["worse","worsening","getting worse","not improving","deteriorating","declining"]
DURATION_KW  = ["days","weeks","months","still","since","persistent","chronic","prolonged","ongoing"]
FAILURE_KW   = ["not working","no effect","not helping","failed","ineffective","antibiotics aren't working"]
POSITIVE_KW  = ["better","improving","recovered","resolved","cured","remission"]
RISK_WEIGHTS = {
    "safety_keyword": 40, "treatment_failure": 20, "worsening": 15,
    "moderate_ae": 10, "symptom": 5, "duration": 5, "negative_sentiment": 5,
}

def score_risk(text, sentiment_label, safety_flag):
    t = text.lower()
    raw_score = 0; reasons = []
    if safety_flag:                   raw_score += RISK_WEIGHTS["safety_keyword"];    reasons.append("safety keyword")
    if any(w in t for w in FAILURE_KW):  raw_score += RISK_WEIGHTS["treatment_failure"]; reasons.append("treatment ineffective")
    if any(w in t for w in WORSENING_KW): raw_score += RISK_WEIGHTS["worsening"];     reasons.append("condition worsening")
    if any(w in t for w in MODERATE_AE_WORDS): raw_score += RISK_WEIGHTS["moderate_ae"]; reasons.append("moderate adverse event")
    if any(w in t for w in SYMPTOM_KW):  raw_score += RISK_WEIGHTS["symptom"];        reasons.append("symptom present")
    if any(w in t for w in DURATION_KW): raw_score += RISK_WEIGHTS["duration"];       reasons.append("prolonged duration")
    if sentiment_label == "Negative": raw_score += RISK_WEIGHTS["negative_sentiment"]; reasons.append("negative sentiment")
    if any(w in t for w in POSITIVE_KW): raw_score = max(0, raw_score - 15)
    risk_score = min(raw_score, 100)
    level      = "High" if risk_score >= 60 else ("Medium" if risk_score >= 25 else "Low")
    reason_str = " + ".join(reasons) if reasons else "no significant indicators"
    confidence = round(min(0.45 + len(reasons) * 0.08, 0.96), 2)
    return {"risk_level": level, "risk_score": risk_score,
            "risk_reason": f"⚠️ {level} ({risk_score}/100): {reason_str}", "confidence": confidence}

def detect_safety(text):
    import re as _re
    t = text.lower(); triggers = []
    for kw in SAFETY_KEYWORDS:
        if _re.search(r"\b" + _re.escape(kw) + r"\b", t): triggers.append(kw)
    return {"safety_flag": len(triggers) > 0, "safety_reasons": ", ".join(triggers) if triggers else ""}

TOPIC_MAP = {
    "adverse event":     ["side effect","adverse","reaction","complication"],
    "treatment failure": ["not working","no effect","failed","ineffective"],
    "safety concern":    SAFETY_KEYWORDS,
    "dosage query":      ["dose","dosage","how much","mg","milligram"],
    "efficacy":          ["works","effective","helped","relief","better","resolved"],
    "discontinuation":   ["stopped","quit","discontinued","switched","stopped taking"],
    "drug interaction":  ["interaction","combined with","mixing","taking both"],
    "mental health":     ["depressed","anxiety","suicidal","mental","psychiatric"],
    "long duration":     ["weeks","months","chronic","persistent","ongoing","years"],
}

def tag_topics(text):
    t = text.lower()
    return [tag for tag, kws in TOPIC_MAP.items() if any(k in t for k in kws)]

# ===========================================================
# ANALYSIS PIPELINE
# ===========================================================

def heuristic_analyze(post):
    text     = f"{post.get('title','')} {post.get('body','')}".strip()
    safety   = detect_safety(text)
    pii      = detect_pii(text)
    sent     = analyze_sentiment(text)
    entities = extract_entities(text)
    topics   = tag_topics(text)
    risk     = score_risk(text, sent["sentiment"], safety["safety_flag"])
    ae_match = re.search(r"(experienced?|developed?|noticed?|got|having?)\s+([\w\s]{3,40})", text, re.I)
    ae       = ae_match.group(2).strip().title() if ae_match else ""
    return {**post, **sent, **safety, **pii, **risk,
            "entities": entities, "topics": topics,
            "adverse_event": ae, "summary": text[:200], "analyzed_by": "heuristic"}

def analyze_batch(posts):
    results = []
    bar = st.progress(0, text="Analysing posts...")
    n   = max(len(posts), 1)
    for i, post in enumerate(posts):
        results.append(heuristic_analyze(post))
        bar.progress((i+1)/n, text=f"Analysing {i+1}/{n}...")
    bar.empty()
    return results

# ===========================================================
# TREND ANALYSIS
# ===========================================================

def compute_trends(signals):
    if not signals: return []
    df = pd.DataFrame(signals)
    if "post_date" not in df.columns: return []
    df["post_date"] = pd.to_datetime(df["post_date"], errors="coerce")
    df = df.dropna(subset=["post_date"])
    if df.empty: return []
    insights = []
    now   = df["post_date"].max()
    last7 = df[df["post_date"] >= now - timedelta(days=7)]
    prev7 = df[(df["post_date"] >= now - timedelta(days=14)) & (df["post_date"] < now - timedelta(days=7))]
    if len(last7) > 0 and len(prev7) > 0:
        pct = ((len(last7) - len(prev7)) / max(len(prev7),1)) * 100
        if pct >= 30:  insights.append(f"📈 **Volume spike:** {len(last7)} posts last 7d vs {len(prev7)} prior week (+{pct:.0f}%)")
        elif pct <= -30: insights.append(f"📉 **Volume drop:** {len(last7)} posts last 7d vs {len(prev7)} prior week ({pct:.0f}%)")
    all_symptoms = []
    for s in signals:
        try: all_symptoms.extend(json.loads(s.get("entities","{}")).get("symptoms",[]))
        except: pass
    for sym, cnt in Counter(all_symptoms).most_common(3):
        if cnt >= 3: insights.append(f"🤒 **{cnt} people** reporting **{sym}** across posts")
    escalation_posts = [s for s in signals
        if any(w in (s.get("body","") or "").lower() for w in ["getting worse","still not","weeks later","months later","still sick"])
        and any(w in (s.get("body","") or "").lower() for w in ["days","weeks","months"])]
    if len(escalation_posts) >= 3:
        insights.append(f"⏱️ **{len(escalation_posts)} posts** show escalation pattern")
    def get_topics(subset):
        tl = []
        for s in subset.to_dict("records"):
            try:
                t = s.get("topics","[]")
                tl.extend(json.loads(t) if isinstance(t, str) else t)
            except: pass
        return Counter(tl)
    if not last7.empty and not prev7.empty:
        t_last = get_topics(last7); t_prev = get_topics(prev7)
        new_topics = [t for t in t_last if t_last[t] >= 2 and t_prev.get(t, 0) == 0]
        if new_topics: insights.append(f"🔄 **Topic drift detected:** {', '.join(new_topics)}")
    drug_ae_pairs = []
    for s in signals:
        try:
            ents = json.loads(s.get("entities","{}"))
            for d in ents.get("drugs",[]):
                for sy in ents.get("symptoms",[]): drug_ae_pairs.append(f"{d}->{sy}")
        except: pass
    if drug_ae_pairs:
        top = Counter(drug_ae_pairs).most_common(1)
        if top and top[0][1] >= 3:
            pair, cnt = top[0]; drug, ae = pair.split("->")
            insights.append(f"💊 **Drug-event signal:** **{drug}** linked to **{ae}** in {cnt} posts")
    if "risk_level" in df.columns and not last7.empty:
        h = len(last7[last7["risk_level"]=="High"])
        if h >= 3: insights.append(f"🔴 **{h} high-risk signals** in the last 7 days")
    if "safety_flag" in df.columns and not last7.empty:
        sf7 = int(last7["safety_flag"].sum())
        if sf7 >= 2: insights.append(f"🚨 **{sf7} safety flags** in last 7 days — review immediately")
    if "sentiment" in df.columns:
        neg_pct = (df["sentiment"]=="Negative").mean() * 100
        if neg_pct >= 60: insights.append(f"😟 **{neg_pct:.0f}% negative sentiment** — elevated distress signal")
    topic_list = []
    for s in signals:
        try:
            t = s.get("topics","[]")
            topic_list.extend(json.loads(t) if isinstance(t, str) else t)
        except: pass
    tf_count = topic_list.count("treatment failure")
    if tf_count >= 3: insights.append(f"💊 **Treatment failure** in {tf_count} posts — potential safety signal")
    if not insights: insights.append("✅ No significant trend anomalies detected.")
    return insights

# ===========================================================
# UI
# ===========================================================

init_db()
st.set_page_config(page_title="HealthWatch", layout="wide", page_icon="🏥")
st.markdown("""<style>
.safety-card{background:#ff000015;border-left:4px solid #E24B4A;padding:10px;border-radius:6px;margin:6px 0}
.pii-card{background:#ff990015;border-left:4px solid #EF9F27;padding:10px;border-radius:6px;margin:6px 0}
.trend-card{background:#1a1a2e;border-left:4px solid #378ADD;padding:10px;border-radius:6px;margin:6px 0;color:#eee}
</style>""", unsafe_allow_html=True)

st.sidebar.image("https://img.icons8.com/color/96/stethoscope.png", width=60)
st.sidebar.title("HealthWatch")
st.sidebar.caption("Real-Time Patient Signal Monitor")
st.sidebar.markdown("---")

page = st.sidebar.radio("Navigate", [
    "🏠 Dashboard", "📁 Projects", "🔍 Run Analysis", "📊 Signals & Trends", "⚙️ Admin"
])

if page == "🏠 Dashboard":
    st.title("🏥 HealthWatch")
    st.caption("Real-Time Social Listening for Patient Experience & Safety Signals")
    projects = get_projects()
    if not projects:
        st.info("👈 Create your first project in **📁 Projects** to get started.")
    else:
        all_sig = []
        for p in projects: all_sig.extend(get_signals(p["id"]))
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("📁 Projects",     len(projects))
        c2.metric("📨 Signals",      len(all_sig))
        c3.metric("🔴 High Risk",    sum(1 for s in all_sig if s.get("risk_level")=="High"))
        c4.metric("⚠️ Safety Flags", sum(1 for s in all_sig if s.get("safety_flag")==1))
        c5.metric("🔒 PII Flagged",  sum(1 for s in all_sig if s.get("pii_flagged")==1))
        st.markdown("---")
        if all_sig:
            st.subheader("🔎 Trend Insights")
            for insight in compute_trends(all_sig):
                st.markdown(f'<div class="trend-card">{insight}</div>', unsafe_allow_html=True)
        st.markdown("---")
        st.subheader("🔴 Recent High-Risk Signals")
        high = [s for s in all_sig if s.get("risk_level")=="High"][:8]
        if not high: st.info("No high-risk signals yet.")
        for s in high:
            with st.expander(f"🔴 [{s.get('risk_score',0)}/100] {str(s.get('title',''))[:80]}"):
                st.markdown(f"**{s.get('risk_reason','')}**")
                st.caption(f"Source: {s.get('source')} | Sentiment: {s.get('sentiment')} | Confidence: {s.get('confidence',0):.0%}")
                if s.get("safety_flag"): st.error(f"🚨 Safety: {s.get('safety_reasons','')}")
                if s.get("pii_flagged"): st.warning(f"🔒 PII: {s.get('pii_types','')}")
                if s.get("url"): st.markdown(f"[View original]({s['url']})")

elif page == "📁 Projects":
    st.title("📁 Project Management")
    available = [e["name"] for e in get_source_engines()]
    tab1, tab2 = st.tabs(["➕ Create", "📋 Manage"])
    with tab1:
        with st.form("cpf"):
            name    = st.text_input("Project Name *")
            desc    = st.text_area("Description", height=70)
            kw_raw  = st.text_input("Keywords * (comma-separated)", placeholder="fever, ibuprofen, fatigue")
            sources = st.multiselect("Data Sources", available, default=["Reddit"])
            latency = st.selectbox("Fetch Frequency", ["realtime","daily","weekly"])
            if st.form_submit_button("➕ Create Project"):
                if not name.strip() or not kw_raw.strip():
                    st.error("Name and keywords required.")
                else:
                    try:
                        pid = create_project(name, desc, [k.strip() for k in kw_raw.split(",") if k.strip()], sources, latency)
                        st.success(f"✅ Project **{name}** created (ID: {pid})"); st.rerun()
                    except ValueError as e: st.error(str(e))
    with tab2:
        projects = get_projects()
        if not projects: st.info("No projects yet.")
        for p in projects:
            kws  = json.loads(p.get("keywords","[]"))
            srcs = json.loads(p.get("sources","[]"))
            sigs = get_signals(p["id"])
            with st.expander(f"📁 **{p['name']}** — {len(sigs)} signals | latency: {p.get('latency','daily')}"):
                c1, c2 = st.columns([3,1])
                with c1:
                    nn = st.text_input("Name",       value=p["name"],               key=f"n{p['id']}")
                    nd = st.text_area("Description", value=p.get("description",""), key=f"d{p['id']}", height=60)
                    nk = st.text_input("Keywords",   value=", ".join(kws),          key=f"k{p['id']}")
                    ns = st.multiselect("Sources",   available,
                                        default=[s for s in srcs if s in available], key=f"s{p['id']}")
                    nl = st.selectbox("Latency",     ["realtime","daily","weekly"],
                                      index=["realtime","daily","weekly"].index(p.get("latency","daily")),
                                      key=f"l{p['id']}")
                with c2:
                    if st.button("💾 Save",   key=f"sv{p['id']}"):
                        update_project(p["id"], nn, nd, [k.strip() for k in nk.split(",")], ns, nl)
                        st.success("Saved!"); st.rerun()
                    if st.button("🗑️ Delete", key=f"dl{p['id']}"):
                        delete_project(p["id"]); st.rerun()

elif page == "🔍 Run Analysis":
    st.title("🔍 Fetch & Analyse")
    projects = get_projects()
    if not projects: st.warning("Create a project first."); st.stop()
    pm      = {p["name"]: p for p in projects}
    project = pm[st.selectbox("Select Project", list(pm.keys()))]
    kws     = json.loads(project.get("keywords","[]"))
    srcs    = json.loads(project.get("sources","[]"))
    latency = project.get("latency","daily")
    st.markdown(f"**Keywords:** `{', '.join(kws)}`  |  **Sources:** `{', '.join(srcs)}`  |  **Latency:** `{latency}`")
    st.info("ℹ️ Heuristic pipeline: negation-aware sentiment · entity extraction · 0-100 risk scoring · PII detection")
    if st.button("🚀 Fetch & Analyse Now", type="primary"):
        all_posts = []
        with st.status("Fetching data...", expanded=True) as status:
            for src in srcs:
                st.write(f"📡 Fetching from **{src}**...")
                try:
                    eng     = get_engine(src)
                    fetched = eng.fetch(kws)
                    st.write(f"   → {len(fetched)} relevant posts retrieved")
                    all_posts.extend(fetched)
                except Exception as e:
                    st.error(f"{src} error: {e}")
            status.update(label=f"✅ Fetched {len(all_posts)} posts total.", state="complete")
        if all_posts:
            analyzed = analyze_batch(all_posts)
            save_signals(project["id"], analyzed)
            st.success(f"✅ Saved **{len(analyzed)}** signals.")
            df = pd.DataFrame(analyzed)
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Total",          len(df))
            c2.metric("🔴 High Risk",   int((df["risk_level"]=="High").sum()))
            c3.metric("Avg Risk Score", f"{df['risk_score'].mean():.0f}/100")
            c4.metric("⚠️ Safety",      int(df["safety_flag"].sum()))
            c5.metric("🔒 PII",         int(df["pii_flagged"].sum()))
        else:
            st.warning("No posts fetched. Check your keywords and sources.")

elif page == "📊 Signals & Trends":
    st.title("📊 Signals & Trends")
    projects = get_projects()
    if not projects: st.stop()
    pm      = {p["name"]: p for p in projects}
    project = pm[st.selectbox("Project", list(pm.keys()))]
    signals = get_signals(project["id"])
    if not signals: st.info("No signals yet. Run analysis first."); st.stop()
    df = pd.DataFrame(signals)
    for col in ["topics","entities"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: json.loads(x) if isinstance(x, str) else (x or []))
    st.subheader("🔎 Trend Insights")
    for insight in compute_trends(signals):
        st.markdown(f'<div class="trend-card">{insight}</div>', unsafe_allow_html=True)
    st.markdown("---")
    with st.expander("🔽 Filters", expanded=False):
        fc1,fc2,fc3 = st.columns(3)
        rf = fc1.multiselect("Risk Level",  ["High","Medium","Low"],           default=["High","Medium","Low"])
        sf = fc2.multiselect("Sentiment",   ["Positive","Negative","Neutral"], default=["Positive","Negative","Neutral"])
        so = fc3.multiselect("Source",      df["source"].dropna().unique().tolist(),
                              default=df["source"].dropna().unique().tolist())
        safeonly = st.checkbox("⚠️ Safety flags only")
        piionly  = st.checkbox("🔒 PII flagged only")
    mask = df["risk_level"].isin(rf) & df["sentiment"].isin(sf) & df["source"].isin(so)
    if safeonly: mask &= df["safety_flag"]==1
    if piionly:  mask &= df["pii_flagged"]==1
    fdf = df[mask]
    if fdf.empty:
        st.warning("No signals match the selected filters.")
        st.stop()
    nh = int((fdf["risk_level"]=="High").sum())
    nm = int((fdf["risk_level"]=="Medium").sum())
    nl = int((fdf["risk_level"]=="Low").sum())
    avg_score = fdf["risk_score"].mean() if "risk_score" in fdf.columns else 0
    mc1,mc2,mc3,mc4 = st.columns(4)
    mc1.markdown(f'<div style="border:1px solid #F09595;border-radius:8px;padding:1rem;text-align:center"><div style="color:#A32D2D;font-weight:600">🔴 HIGH</div><div style="font-size:2.5rem;font-weight:700;color:#A32D2D">{nh}</div></div>', unsafe_allow_html=True)
    mc2.markdown(f'<div style="border:1px solid #FAC775;border-radius:8px;padding:1rem;text-align:center"><div style="color:#854F0B;font-weight:600">🟡 MEDIUM</div><div style="font-size:2.5rem;font-weight:700;color:#854F0B">{nm}</div></div>', unsafe_allow_html=True)
    mc3.markdown(f'<div style="border:1px solid #C0DD97;border-radius:8px;padding:1rem;text-align:center"><div style="color:#3B6D11;font-weight:600">🟢 LOW</div><div style="font-size:2.5rem;font-weight:700;color:#3B6D11">{nl}</div></div>', unsafe_allow_html=True)
    mc4.markdown(f'<div style="border:1px solid #9999cc;border-radius:8px;padding:1rem;text-align:center"><div style="color:#333399;font-weight:600">📊 AVG SCORE</div><div style="font-size:2.5rem;font-weight:700;color:#333399">{avg_score:.0f}<span style="font-size:1rem">/100</span></div></div>', unsafe_allow_html=True)
    st.markdown("---")
    RISK_C = {"High":"#E24B4A","Medium":"#EF9F27","Low":"#639922"}
    SENT_C = {"Positive":"#639922","Negative":"#E24B4A","Neutral":"#888780"}
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Risk Distribution")
        rc = fdf["risk_level"].value_counts().reindex(["High","Medium","Low"]).fillna(0)
        fig, ax = plt.subplots(figsize=(3.5,3))
        ax.pie(rc, labels=rc.index, autopct="%1.0f%%",
               colors=[RISK_C.get(k,"#999") for k in rc.index],
               wedgeprops={"linewidth":1.5,"edgecolor":"white"}, startangle=90)
        st.pyplot(fig, use_container_width=True); plt.close()
    with col2:
        st.subheader("Sentiment")
        sc = fdf["sentiment"].value_counts()
        fig, ax = plt.subplots(figsize=(3.5,3))
        bars = ax.bar(sc.index, sc.values, color=[SENT_C.get(s,"#999") for s in sc.index],
                      width=0.5, edgecolor="white")
        ax.bar_label(bars, padding=3, fontsize=10)
        ax.spines[["top","right"]].set_visible(False)
        ax.set_ylim(0, sc.max()*1.3 if len(sc) else 1)
        st.pyplot(fig, use_container_width=True); plt.close()
    with col3:
        st.subheader("Risk Score Distribution (0-100)")
        if "risk_score" in fdf.columns:
            fig, ax = plt.subplots(figsize=(3.5,3))
            ax.hist(fdf["risk_score"], bins=10, range=(0,100), color="steelblue", edgecolor="white", linewidth=0.8)
            ax.axvline(60, color="#E24B4A", ls="--", lw=1.5, label="High threshold")
            ax.axvline(25, color="#EF9F27", ls="--", lw=1.5, label="Medium threshold")
            ax.set_xlabel("Risk Score"); ax.set_ylabel("Posts"); ax.legend(fontsize=8)
            ax.spines[["top","right"]].set_visible(False)
            st.pyplot(fig, use_container_width=True); plt.close()
    col4, col5 = st.columns(2)
    with col4:
        st.subheader("Top Topics")
        all_t = [t for row in fdf["topics"] for t in (row if isinstance(row,list) else [])]
        tc    = Counter(all_t).most_common(8)
        if tc:
            fig, ax = plt.subplots(figsize=(5,3))
            tl, tv  = zip(*tc)
            tc_col  = ["#E24B4A" if "safety" in l else "#EF9F27" if "treatment" in l else "#378ADD" for l in tl]
            ax.barh(tl, tv, color=tc_col, edgecolor="white"); ax.invert_yaxis()
            ax.spines[["top","right"]].set_visible(False)
            st.pyplot(fig, use_container_width=True); plt.close()
        else: st.info("No topics yet.")
    with col5:
        st.subheader("Drug-Event Correlation")
        drug_ae = []
        for s in signals:
            try:
                ents = json.loads(s.get("entities","{}"))
                for d in ents.get("drugs",[]):
                    for sy in ents.get("symptoms",[]): drug_ae.append(f"{d} → {sy}")
            except: pass
        if drug_ae:
            top_de = Counter(drug_ae).most_common(8)
            fig, ax = plt.subplots(figsize=(5,3))
            dl, dv  = zip(*top_de)
            ax.barh(dl, dv, color="mediumpurple", edgecolor="white"); ax.invert_yaxis()
            ax.spines[["top","right"]].set_visible(False); ax.set_xlabel("Co-occurrences")
            st.pyplot(fig, use_container_width=True); plt.close()
        else: st.info("Not enough drug+symptom data yet.")
    st.markdown("---")
    st.subheader("📅 Risk Score Timeline (0-100)")
    if "post_date" in fdf.columns and "risk_score" in fdf.columns:
        td = fdf.copy()
        td["post_date"] = pd.to_datetime(td["post_date"], errors="coerce")
        td = td.dropna(subset=["post_date"])
        if not td.empty:
            weekly   = td.set_index("post_date")["risk_score"].resample("W").mean()
            smoothed = weekly.rolling(3, min_periods=1).mean()
            fig, ax  = plt.subplots(figsize=(12,3.5))
            ax.fill_between(weekly.index, 0,  25, alpha=0.07, color="green",  label="Low zone")
            ax.fill_between(weekly.index, 25, 60, alpha=0.07, color="orange", label="Medium zone")
            ax.fill_between(weekly.index, 60, 100,alpha=0.07, color="red",    label="High zone")
            ax.plot(weekly.index,   weekly.values,   "o-", color="steelblue",  lw=1.5, ms=4, label="Weekly avg")
            ax.plot(smoothed.index, smoothed.values, "-",  color="darkorange", lw=2.5,       label="Smoothed")
            ax.axhline(60, color="#E24B4A", ls="--", lw=0.8, alpha=0.6)
            ax.axhline(25, color="#EF9F27", ls="--", lw=0.8, alpha=0.6)
            ax.set_ylabel("Risk Score (0-100)"); ax.set_ylim(0,100)
            ax.set_xlabel("Date"); ax.legend(fontsize=9)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
            plt.xticks(rotation=30)
            st.pyplot(fig, use_container_width=True); plt.close()
    sdf = fdf[fdf["safety_flag"]==1]
    if not sdf.empty:
        st.markdown("---"); st.subheader("🚨 Safety & Adverse Event Flags")
        for _, row in sdf.iterrows():
            st.markdown(
                f'<div class="safety-card"><b>{str(row.get("title",""))[:80]}</b><br>'
                f'Source: {row.get("source","")} | Date: {row.get("post_date","")} | Score: {row.get("risk_score",0)}/100<br>'
                f'Triggers: {row.get("safety_reasons","")}</div>', unsafe_allow_html=True)
    pdf = fdf[fdf["pii_flagged"]==1]
    if not pdf.empty:
        st.markdown("---"); st.subheader("🔒 PII / PHI Detected")
        for _, row in pdf.iterrows():
            st.markdown(
                f'<div class="pii-card"><b>{str(row.get("title",""))[:80]}</b><br>'
                f'Source: {row.get("source","")} | Date: {row.get("post_date","")}<br>'
                f'PII Types: {row.get("pii_types","")}</div>', unsafe_allow_html=True)
    st.markdown("---")
    st.subheader("📋 Signals")
    display_cols = [c for c in ["post_date","source","title","sentiment","sentiment_detail",
                                 "risk_level","risk_score","risk_reason","confidence",
                                 "safety_flag","pii_flagged","adverse_event"] if c in fdf.columns]
    st.dataframe(fdf[display_cols].reset_index(drop=True), use_container_width=True, height=400)
    st.download_button("⬇️ Download CSV",
                       fdf.drop(columns=["id","project_id"], errors="ignore").to_csv(index=False),
                       "signals.csv", "text/csv")

elif page == "⚙️ Admin":
    st.title("⚙️ Admin")
    st.subheader("Registered Source Engines")
    for e in get_source_engines():
        with st.expander(f"🔧 {e['name']}"):
            try:    st.json(json.loads(e.get("config","{}")))
            except: st.code(e.get("config",""))
    st.markdown("---")
    st.subheader("➕ Register New Engine")
    with st.form("add_eng"):
        en  = st.text_input("Engine Name", placeholder="e.g. CustomForum")
        eu  = st.text_input("Base URL",    placeholder="https://example.com")
        ek  = st.checkbox("Requires API Key")
        en2 = st.text_area("Config notes")
        if st.form_submit_button("➕ Register") and en and eu:
            add_source_engine(en, {"base_url": eu, "requires_key": ek, "notes": en2})
            st.success(f"✅ Engine **{en}** registered!"); st.rerun()
    st.markdown("---")
    st.subheader("📊 Database Stats")
    with get_conn() as conn:
        np_ = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        ns_ = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        nh_ = conn.execute("SELECT COUNT(*) FROM signals WHERE risk_level='High'").fetchone()[0]
        nf_ = conn.execute("SELECT COUNT(*) FROM signals WHERE safety_flag=1").fetchone()[0]
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Projects",       np_)
    c2.metric("Total Signals",  ns_)
    c3.metric("High Risk",      nh_)
    c4.metric("Safety Flagged", nf_)
    st.markdown("---")
    st.subheader("⚠️ Danger Zone")
    if st.button("🗑️ Clear ALL signals"):
        with get_conn() as conn: conn.execute("DELETE FROM signals")
        st.success("All signals cleared."); st.rerun()