"""
HealthWatch — Patient Signal Monitor
Real-Time Social Listening for Patient Experience & Safety Signals
"""

import streamlit as st
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import requests
import sqlite3
import json
import re
import time
import os
import random
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from collections import Counter
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup

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

# International PII patterns with context-aware matching to reduce false positives
PII_PATTERNS = {
    # Universal
    "email":               r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "phone_international": r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{2,5}[\s\-]?\d{2,5}[\s\-]?\d{0,5}",
    "name":                r"\b(?:my name is|call me)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+",
    "dob":                 r"\b(?:born|dob|date of birth|d\.o\.b|birthday)[:\s]+(?:\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2},?\s+\d{4})",
    # United States
    "us_ssn":              r"\b\d{3}-\d{2}-\d{4}\b",
    "us_phone":            r"\b(?:\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]\d{4})\b",
    "us_zip":              r"\b(?:zip|zip code|postal)[:\s]+\d{5}(?:-\d{4})?\b",
    "us_address":          r"\b\d{1,5}\s+[A-Za-z0-9\s]{2,30}\s+(?:St(?:reet)?|Ave(?:nue)?|Rd|Road|Blvd|Boulevard|Dr(?:ive)?|Lane|Ln|Way|Ct|Court|Pl(?:ace)?|Terrace|Ter)\b",
    # United Kingdom
    "uk_nino":             r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b",
    "uk_postcode":         r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}\b",
    "uk_phone":            r"\b(?:(?:\+44|0)[\s\-]?(?:7\d{3}|1\d{3}|2\d{3})[\s\-]?\d{3}[\s\-]?\d{3,4})\b",
    "uk_nhs":              r"\b\d{3}[\s\-]\d{3}[\s\-]\d{4}\b",
    # India
    "in_aadhaar":          r"\b(?:aadhaar|aadhar|uid)[:\s]+\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
    "in_pan":              r"\b[A-Z]{5}\d{4}[A-Z]\b",
    "in_pincode":          r"(?:pin\s*code|pincode|postal\s+code)\b[^0-9]{0,10}[1-9]\d{5}\b",
    "in_phone":            r"\b(?:\+91[\s\-]?)?[6-9]\d{9}\b",
    # Canada
    "ca_sin":              r"\b\d{3}-\d{3}-\d{3}\b",
    "ca_postal":           r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b",
    # Australia
    "au_tfn":              r"\b(?:tfn|tax file number)[:\s]+\d{2,3}[\s\-]?\d{3}[\s\-]?\d{3}\b",
    "au_medicare":         r"\b(?:medicare)[:\s#]+[2-6]\d{9}\b",
    "au_phone":            r"\b(?:\+61[\s\-]?)?0?4\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b",
    # EU
    "eu_national_id":      r"\b(?:national id|id number|passport|personalausweis|dni|nif|bsn)[:\s#]+[A-Z0-9]{6,20}\b",
    "iban":                r"\b[A-Z]{2}\d{2}[\s]?[A-Z0-9]{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{0,4}[\s]?\d{0,4}\b",
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
                post_id           TEXT UNIQUE,
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

def get_signals(pid, limit=10000):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE project_id=? ORDER BY post_date DESC LIMIT ?", (pid, limit)
        ).fetchall()
    return [dict(r) for r in rows]

def save_signals(pid, signals):
    with get_conn() as conn:
        for s in signals:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO signals
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
                    int(s.get("safety_flag", 0)), s.get("safety_reasons", ""),
                    int(s.get("pii_flagged", 0)), s.get("pii_types", ""),
                    s.get("adverse_event", ""),
                    json.dumps(s.get("entities", {})),
                    json.dumps(s.get("topics", [])),
                    s.get("summary", ""),
                    s.get("analyzed_by", "heuristic"),
                ))
            except Exception as e:
                print(f"Error saving signal: {e}")

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
            "AskDocs", "DiagnoseMe", "medical_advice", "Longcovid",
            "covidlonghaulers", "cfs", "Fibromyalgia", "chronicpain",
            "lupus", "autoimmune", "Lyme", "ehlersdanlos", "POTS"
        ]
        self.limit = limit

    def fetch(self, keywords):
        posts = []
        query = " OR ".join(keywords[:4])
        for sub in self.subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub}/search.json"
                resp = requests.get(url, params={"q": query, "sort": "new",
                                                 "limit": self.limit, "restrict_sr": 1},
                                    headers=self.HEADERS, timeout=10)
                if resp.status_code == 429:
                    time.sleep(10)
                    continue
                if resp.status_code != 200:
                    continue
                for child in resp.json().get("data", {}).get("children", []):
                    d = child.get("data", {})
                    title = d.get("title", "")
                    body = d.get("selftext", "")
                    if body in ["[removed]", "[deleted]"]:
                        body = ""
                    full = (title + " " + body).strip()
                    if not self._relevant(full, keywords) or len(full) < 60:
                        continue
                    created = d.get("created_utc", 0)
                    posts.append({
                        "source":    "Reddit",
                        "post_id":   d.get("id", ""),
                        "author":    d.get("author", "[deleted]"),
                        "title":     title,
                        "body":      body,
                        "url":       f"https://reddit.com{d.get('permalink', '')}",
                        "post_date": datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d")
                    })
                time.sleep(1.2)
            except Exception as e:
                print(f"Reddit r/{sub}: {e}")
        return posts


class PubMedEngine(BaseEngine):
    name = "PubMed"
    NON_HUMAN_TERMS = [
        "porcine", "bovine", "equine", "murine", "canine", "feline",
        "swine", "pig ", "mouse", "mice", "rat ", "rats ", "rabbit",
        "veterinary", "livestock", "poultry", "ovine", "prrsv",
        "avian", "broiler", "ruminant", "cattle", "sheep", "goat",
    ]

    def __init__(self, max_results=10):
        self.max_results = max_results

    def _is_non_human(self, text: str) -> bool:
        t = text.lower()
        return any(term in t for term in self.NON_HUMAN_TERMS)

    def fetch(self, keywords):
        posts = []
        for kw in keywords[:3]:
            try:
                sr = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                                  params={"db": "pubmed", "term": kw, "retmax": self.max_results, "retmode": "json"},
                                  timeout=10)
                sr.raise_for_status()
                ids = sr.json().get("esearchresult", {}).get("idlist", [])
                if not ids:
                    continue
                fr = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                                  params={"db": "pubmed", "id": ",".join(ids), "rettype": "abstract", "retmode": "xml"},
                                  timeout=15)
                fr.raise_for_status()
                root = ET.fromstring(fr.content)
                for article in root.findall(".//PubmedArticle"):
                    pmid_el = article.find(".//PMID")
                    pmid = pmid_el.text if pmid_el is not None else str(random.randint(10000, 99999))
                    title_el = article.find(".//ArticleTitle")
                    title = title_el.text if title_el is not None else ""
                    ab_el = article.find(".//AbstractText")
                    body = ab_el.text if ab_el is not None else ""
                    full = ((title or "") + " " + (body or "")).strip()
                    if not self._relevant(full, keywords):
                        continue
                    if self._is_non_human(full):
                        continue
                    posts.append({
                        "source":    "PubMed",
                        "post_id":   f"pubmed_{pmid}",
                        "author":    "PubMed",
                        "title":     (title or "").strip(),
                        "body":      (body or "").strip(),
                        "url":       f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "post_date": datetime.now().strftime("%Y-%m-%d"),
                    })
                time.sleep(0.4)
            except Exception as e:
                print(f"PubMed '{kw}': {e}")
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
                if resp.status_code == 404:
                    continue
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
                    title = f"FDA AE Report: {drug_names[:60]} — {ae_terms[:60]}"
                    body  = (f"Adverse reactions: {ae_terms}. Drugs: {drug_names}. "
                             f"Serious: {'Yes' if serious else 'No'}. "
                             f"Outcomes: {', '.join(str(r.get('reactionoutcome', '')) for r in reactions[:3])}.")
                    uid = event.get("safetyreportid", str(random.randint(100000, 999999)))
                    posts.append({
                        "source":    "OpenFDA",
                        "post_id":   f"fda_{uid}",
                        "author":    "FDA FAERS",
                        "title":     title[:200],
                        "body":      body,
                        "url":       "https://open.fda.gov/apis/drug/event/",
                        "post_date": rd if rd else datetime.now().strftime("%Y-%m-%d"),
                    })
                time.sleep(0.3)
            except Exception as e:
                print(f"OpenFDA '{kw}': {e}")
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
                    if not self._relevant(title + " " + summary, keywords):
                        continue
                    posts.append({
                        "source":    "ClinicalTrials",
                        "post_id":   f"ct_{nctid}",
                        "author":    "ClinicalTrials.gov",
                        "title":     title[:200],
                        "body":      summary[:800] if summary else "",
                        "url":       f"https://clinicaltrials.gov/study/{nctid}",
                        "post_date": datetime.now().strftime("%Y-%m-%d"),
                    })
                time.sleep(0.3)
            except Exception as e:
                print(f"ClinicalTrials '{kw}': {e}")
        return posts


ENGINES = {
    "Reddit":         RedditEngine,
    "PubMed":         PubMedEngine,
    "OpenFDA":        OpenFDAEngine,
    "ClinicalTrials": ClinicalTrialsEngine,
}

def get_engine(name):
    if name in ENGINES:
        return ENGINES[name]()
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
    if idx == -1:
        return False
    context = text[max(0, idx - 30):idx]
    return any(neg in context for neg in NEGATIONS)

def analyze_sentiment(text):
    t = text.lower()
    score = 0
    hits = []
    for phrase, weight in SENTIMENT_LEXICON.items():
        if phrase in t:
            effective = -weight if _is_negated(t, phrase) else weight
            score += effective
            hits.append((phrase, effective))
    norm_score = max(-1.0, min(1.0, score / 15.0))
    label = "Positive" if norm_score >= 0.2 else ("Negative" if norm_score <= -0.2 else "Neutral")
    emotions = [emo for emo, words in SENTIMENT_EMOTIONS.items() if any(w in t for w in words)]
    confidence = round(min(0.4 + len(hits) * 0.07, 0.97), 2)
    top_hits = sorted(hits, key=lambda x: abs(x[1]), reverse=True)[:3]
    detail = ", ".join([f'"{p}" ({w:+d})' for p, w in top_hits]) if top_hits else "no strong signals"
    return {
        "sentiment":        label,
        "sentiment_score":  round(norm_score, 3),
        "sentiment_detail": f"Score {score:+d} | Signals: {detail}" + (f" | Emotions: {', '.join(emotions)}" if emotions else ""),
        "confidence":       confidence,
    }

# ===========================================================
# ENTITY EXTRACTION
# ===========================================================

DRUG_LIST = [
    "ibuprofen", "paracetamol", "acetaminophen", "amoxicillin", "doxycycline",
    "azithromycin", "metformin", "prednisone", "prednisolone", "augmentin",
    "cephalexin", "ciprofloxacin", "metronidazole", "tylenol", "motrin", "aspirin",
    "naproxen", "hydroxychloroquine", "remicade", "humira", "antibiotics",
    "antibiotic", "nsaids", "antihistamine", "sertraline", "gabapentin",
    "lisinopril", "atorvastatin", "omeprazole", "levothyroxine", "concerta",
    "valtrex", "revlimid", "betnovate", "rabipur",
]
CONDITION_LIST = [
    "fever", "fatigue", "covid", "long covid", "fibromyalgia", "lupus",
    "lyme disease", "pots", "mcas", "eds", "cfs", "me/cfs", "chronic fatigue",
    "arthritis", "thyroid", "hypothyroidism", "anemia", "infection",
    "pneumonia", "bronchitis", "sinusitis", "appendicitis", "gastritis",
    "endometriosis", "mononucleosis", "sepsis", "depression", "anxiety",
    "migraine", "diabetes", "hypertension", "asthma", "barth syndrome",
]
SYMPTOM_LIST = [
    "fever", "fatigue", "chills", "nausea", "vomiting", "headache",
    "body aches", "muscle pain", "joint pain", "weakness", "dizziness",
    "shortness of breath", "chest pain", "rash", "swollen lymph nodes",
    "night sweats", "weight loss", "brain fog", "palpitations", "insomnia",
    "dry mouth", "hair loss", "numbness", "tingling", "dry eyes",
]

def extract_entities(text):
    t = text.lower()
    entities = {
        "drugs":      list(set([d for d in DRUG_LIST if d in t])),
        "conditions": list(set([c for c in CONDITION_LIST if c in t])),
        "symptoms":   list(set([s for s in SYMPTOM_LIST if s in t])),
    }
    durations = re.findall(r"\b(\d+)\s*(day|week|month|year)s?\b", t)
    entities["durations"] = [f"{n} {u}s" for n, u in durations[:3]]
    ag = re.findall(r"\b(\d{1,3})\s*(?:year[s]?\s*old|yo|[mf])\b", t)
    entities["age_mentions"] = list(set(ag))[:3]
    return entities

# ===========================================================
# PII DETECTION — international, context-aware, tiered confidence
# ===========================================================

def detect_pii(text):
    found = {}
    for label, pattern in PII_PATTERNS.items():
        try:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                found[label] = matches[:2]
        except re.error:
            pass
    if not found:
        return {"pii_flagged": False, "pii_types": "", "pii_confidence": ""}
    tiered = {"high": [], "medium": [], "low": []}
    for label in found:
        for tier, members in PII_CONFIDENCE.items():
            if label in members:
                tiered[tier].append(label)
                break
        else:
            tiered["medium"].append(label)
    parts = []
    if tiered["high"]:   parts.append("HIGH: "   + ", ".join(tiered["high"][:3]))
    if tiered["medium"]: parts.append("MEDIUM: " + ", ".join(tiered["medium"][:3]))
    if tiered["low"]:    parts.append("LOW: "    + ", ".join(tiered["low"][:3]))
    return {
        "pii_flagged":    True,
        "pii_types":      "; ".join(parts),
        "pii_confidence": "high" if tiered["high"] else ("medium" if tiered["medium"] else "low"),
    }

# ===========================================================
# RISK SCORING — 0-100
# ===========================================================

SYMPTOM_KW   = ["fever", "fatigue", "pain", "chills", "nausea", "weak", "headache", "vomiting", "rash"]
WORSENING_KW = ["worse", "worsening", "getting worse", "not improving", "deteriorating", "declining"]
DURATION_KW  = ["days", "weeks", "months", "still", "since", "persistent", "chronic", "prolonged", "ongoing"]
FAILURE_KW   = ["not working", "no effect", "not helping", "failed", "ineffective", "antibiotics aren't working"]
POSITIVE_KW  = ["better", "improving", "recovered", "resolved", "cured", "remission"]
RISK_WEIGHTS = {
    "safety_keyword": 40, "treatment_failure": 20, "worsening": 15,
    "moderate_ae": 10, "symptom": 5, "duration": 5, "negative_sentiment": 5,
}

def score_risk(text, sentiment_label, safety_flag, source=""):
    t = text.lower()
    raw_score = 0
    reasons = []

    source_discount = 0
    if source in ("PubMed", "ClinicalTrials", "OpenFDA"):
        source_discount = 15

    if safety_flag:
        raw_score += RISK_WEIGHTS["safety_keyword"]; reasons.append("safety keyword")
    if any(w in t for w in FAILURE_KW):
        raw_score += RISK_WEIGHTS["treatment_failure"]; reasons.append("treatment ineffective")
    if any(w in t for w in WORSENING_KW):
        raw_score += RISK_WEIGHTS["worsening"]; reasons.append("condition worsening")
    if any(w in t for w in MODERATE_AE_WORDS):
        raw_score += RISK_WEIGHTS["moderate_ae"]; reasons.append("moderate adverse event")
    if any(w in t for w in SYMPTOM_KW):
        raw_score += RISK_WEIGHTS["symptom"]; reasons.append("symptom present")
    if any(w in t for w in DURATION_KW):
        raw_score += RISK_WEIGHTS["duration"]; reasons.append("prolonged duration")
    if sentiment_label == "Negative":
        raw_score += RISK_WEIGHTS["negative_sentiment"]; reasons.append("negative sentiment")

    if any(w in t for w in POSITIVE_KW) and not safety_flag:
        raw_score = max(0, raw_score - 8)

    raw_score = max(0, raw_score - source_discount)

    risk_score = min(raw_score, 100)
    level = "High" if risk_score >= 60 else ("Medium" if risk_score >= 25 else "Low")
    reason_str = " + ".join(reasons) if reasons else "no significant indicators"
    if source_discount:
        reason_str += f" [−{source_discount} academic source]"
    confidence = round(min(0.45 + len(reasons) * 0.08, 0.96), 2)
    return {
        "risk_level":  level,
        "risk_score":  risk_score,
        "risk_reason": f"⚠️ {level} ({risk_score}/100): {reason_str}",
        "confidence":  confidence,
    }

# ===========================================================
# SAFETY DETECTION — word-boundary matching (no substring false positives)
# ===========================================================

def detect_safety(text):
    t = text.lower()
    triggers = []
    for kw in SAFETY_KEYWORDS:
        matches = list(re.finditer(r"\b" + re.escape(kw) + r"\b", t))
        for m in matches:
            prefix = t[max(0, m.start() - 40):m.start()]
            negated = any(neg in prefix for neg in ["not ", "no ", "non-", "wasn't ", "isn't ",
                                                      "never ", "without ", "ruled out", "deny "])
            if not negated:
                triggers.append(kw)
                break
    return {
        "safety_flag":    len(triggers) > 0,
        "safety_reasons": ", ".join(triggers[:5]) if triggers else "",
    }

TOPIC_MAP = {
    "adverse event":     ["side effect", "adverse", "reaction", "complication"],
    "treatment failure": ["not working", "no effect", "failed", "ineffective"],
    "safety concern":    SAFETY_KEYWORDS,
    "dosage query":      ["dose", "dosage", "how much", "mg", "milligram"],
    "efficacy":          ["works", "effective", "helped", "relief", "better", "resolved"],
    "discontinuation":   ["stopped", "quit", "discontinued", "switched", "stopped taking"],
    "drug interaction":  ["drug interaction", "drug-drug", "combined with medication", "mixing medications", "taking both medications", "contraindicated"],
    "mental health":     ["depressed", "anxiety", "suicidal", "mental", "psychiatric"],
    "long duration":     ["weeks", "months", "chronic", "persistent", "ongoing", "years"],
}

def tag_topics(text):
    t = text.lower()
    return [tag for tag, kws in TOPIC_MAP.items() if any(k in t for k in kws)]

# ===========================================================
# ANALYSIS PIPELINE
# ===========================================================

def heuristic_analyze(post):
    text = f"{post.get('title', '')} {post.get('body', '')}".strip()
    safety   = detect_safety(text)
    pii      = detect_pii(text)
    sent     = analyze_sentiment(text)
    entities = extract_entities(text)
    topics   = tag_topics(text)
    risk     = score_risk(text, sent["sentiment"], safety["safety_flag"], source=post.get("source", ""))
    ae_match = re.search(r"(experienced?|developed?|noticed?|got|having?)\s+([\w\s]{3,40})", text, re.I)
    ae = ae_match.group(2).strip().title() if ae_match else ""
    return {**post, **sent, **safety, **pii, **risk,
            "entities": entities, "topics": topics,
            "adverse_event": ae, "summary": text[:200], "analyzed_by": "heuristic"}

def analyze_batch(posts):
    results = []
    if posts:
        bar = st.progress(0, text="Analysing posts...")
        n = len(posts)
        for i, post in enumerate(posts):
            results.append(heuristic_analyze(post))
            bar.progress((i + 1) / n, text=f"Analysing {i + 1}/{n}...")
        bar.empty()
    return results

# ===========================================================
# TREND ANALYSIS
# ===========================================================

def compute_trends(signals):
    if not signals:
        return []
    df = pd.DataFrame(signals)
    if "post_date" not in df.columns:
        return []
    df["post_date"] = pd.to_datetime(df["post_date"], errors="coerce")
    df = df.dropna(subset=["post_date"])
    if df.empty:
        return []

    insights = []
    now   = df["post_date"].max()
    last7 = df[df["post_date"] >= now - timedelta(days=7)]
    prev7 = df[(df["post_date"] >= now - timedelta(days=14)) & (df["post_date"] < now - timedelta(days=7))]

    if len(last7) > 0 and len(prev7) > 0:
        pct = ((len(last7) - len(prev7)) / max(len(prev7), 1)) * 100
        if pct >= 30:
            insights.append(f"📈 **Volume spike:** {len(last7)} posts last 7d vs {len(prev7)} prior week (+{pct:.0f}%)")
        elif pct <= -30:
            insights.append(f"📉 **Volume drop:** {len(last7)} posts last 7d vs {len(prev7)} prior week ({pct:.0f}%)")

    all_symptoms = []
    for s in signals:
        try:
            ents = json.loads(s.get("entities", "{}")) if isinstance(s.get("entities"), str) else s.get("entities", {})
            all_symptoms.extend(ents.get("symptoms", []) if isinstance(ents, dict) else [])
        except:
            pass
    for sym, cnt in Counter(all_symptoms).most_common(3):
        if cnt >= 3:
            insights.append(f"🤒 **{cnt} posts** mentioning **{sym}**")

    escalation = [s for s in signals
                  if any(w in (s.get("body") or "").lower() for w in ["getting worse", "still not", "weeks later", "months later", "still sick"])
                  and any(w in (s.get("body") or "").lower() for w in ["days", "weeks", "months"])]
    if len(escalation) >= 3:
        insights.append(f"⏱️ **{len(escalation)} posts** show escalation pattern — symptoms worsening over time")

    def get_topics(subset):
        tl = []
        for s in subset.to_dict("records"):
            try:
                t = s.get("topics", "[]")
                tl.extend(json.loads(t) if isinstance(t, str) else t)
            except:
                pass
        return Counter(tl)

    if not last7.empty and not prev7.empty:
        t_last = get_topics(last7)
        t_prev = get_topics(prev7)
        new_topics = [t for t in t_last if t_last[t] >= 2 and t_prev.get(t, 0) == 0]
        if new_topics:
            insights.append(f"🔄 **Topic drift detected:** {', '.join(new_topics[:3])}")

    drug_ae_pairs = []
    for s in signals:
        try:
            ents = json.loads(s.get("entities", "{}")) if isinstance(s.get("entities"), str) else s.get("entities", {})
            if isinstance(ents, dict):
                for d in ents.get("drugs", []):
                    for sy in ents.get("symptoms", []):
                        drug_ae_pairs.append(f"{d}->{sy}")
        except:
            pass
    if drug_ae_pairs:
        top = Counter(drug_ae_pairs).most_common(1)
        if top and top[0][1] >= 3:
            pair, cnt = top[0]
            drug, ae = pair.split("->")
            insights.append(f"💊 **Drug-event signal:** **{drug}** linked to **{ae}** in {cnt} posts")

    if "risk_level" in df.columns and not last7.empty:
        h = len(last7[last7["risk_level"] == "High"])
        if h >= 3:
            insights.append(f"🔴 **{h} high-risk signals** in the last 7 days")

    if "safety_flag" in df.columns and not last7.empty:
        sf7 = int(last7["safety_flag"].sum())
        if sf7 >= 2:
            insights.append(f"🚨 **{sf7} safety flags** in last 7 days — review immediately")

    if "sentiment" in df.columns:
        neg_pct = (df["sentiment"] == "Negative").mean() * 100
        if neg_pct >= 60:
            insights.append(f"😟 **{neg_pct:.0f}% negative sentiment** — elevated patient distress signal")

    topic_list = []
    for s in signals:
        try:
            t = s.get("topics", "[]")
            topic_list.extend(json.loads(t) if isinstance(t, str) else t)
        except:
            pass
    tf_count = topic_list.count("treatment failure")
    if tf_count >= 3:
        insights.append(f"💊 **Treatment failure** in {tf_count} posts — potential safety signal")

    if not insights:
        insights.append("✅ No significant trend anomalies detected.")
    return insights

# ===========================================================
# UI
# ===========================================================

def trend_card(insight: str) -> str:
    """Convert markdown bold to HTML and wrap in trend-card div."""
    import re as _re
    html = _re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', insight)
    return f'<div class="trend-card">{html}</div>'

init_db()
st.set_page_config(page_title="HealthWatch", layout="wide", page_icon="🏥")

st.markdown("""
<style>
    .safety-card { background:#ff000015; border-left:4px solid #E24B4A; padding:10px; border-radius:6px; margin:6px 0; }
    .pii-card    { background:#ff990015; border-left:4px solid #EF9F27; padding:10px; border-radius:6px; margin:6px 0; }
    .trend-card  { background:#1a1a2e;   border-left:4px solid #378ADD; padding:10px; border-radius:6px; margin:6px 0; color:#eee; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.image("https://img.icons8.com/color/96/stethoscope.png", width=60)
    st.title("HealthWatch")
    st.caption("Real-Time Patient Signal Monitor")
    st.markdown("---")
    page = st.radio("Navigate", [
        "🏠 Dashboard", "📁 Projects", "🔍 Run Analysis", "📊 Signals & Trends", "⚙️ Admin"
    ])

# ── DASHBOARD ───────────────────────────────────────────────
if page == "🏠 Dashboard":
    st.title("🏥 HealthWatch Dashboard")
    st.caption("Real-Time Social Listening for Patient Experience & Safety Signals")
    projects = get_projects()
    if not projects:
        st.info("👈 Create your first project in **📁 Projects** to get started.")
    else:
        all_sig = []
        for p in projects:
            all_sig.extend(get_signals(p["id"]))
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("📁 Projects",     len(projects))
        c2.metric("📨 Total Signals", len(all_sig))
        high_risk = sum(1 for s in all_sig if s.get("risk_level") == "High")
        c3.metric("🔴 High Risk",    high_risk, delta="⚠️ Needs Review" if high_risk > 0 else None)
        c4.metric("⚠️ Safety Flags", sum(1 for s in all_sig if s.get("safety_flag") == 1))
        c5.metric("🔒 PII Flagged",  sum(1 for s in all_sig if s.get("pii_flagged") == 1))
        st.markdown("---")
        if all_sig:
            st.subheader("🔎 Trend Insights")
            for insight in compute_trends(all_sig)[:8]:
                st.markdown(trend_card(insight), unsafe_allow_html=True)
        st.markdown("---")
        st.subheader("🔴 Recent High-Risk Signals")
        high_sigs = [s for s in all_sig if s.get("risk_level") == "High"][:10]
        if not high_sigs:
            st.info("No high-risk signals detected.")
        for signal in high_sigs:
            with st.expander(f"⚠️ [{signal.get('risk_score', 0)}/100] {signal.get('title', '')[:100]}"):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"**Risk:** {signal.get('risk_reason', 'N/A')}")
                    st.markdown(f"**Source:** {signal.get('source')} | **Date:** {signal.get('post_date')}")
                    st.markdown(f"**Sentiment:** {signal.get('sentiment')} (confidence: {signal.get('confidence', 0):.0%})")
                    if signal.get("safety_flag"):
                        st.error(f"🚨 Safety Trigger: {signal.get('safety_reasons')}")
                    if signal.get("pii_flagged"):
                        st.warning(f"🔒 PII Detected: {signal.get('pii_types')}")
                    if signal.get("url"):
                        st.markdown(f"[🔗 View Original Post]({signal['url']})")
                with c2:
                    if signal.get("adverse_event"):
                        st.info(f"📋 AE: {signal.get('adverse_event')}")

# ── PROJECTS ────────────────────────────────────────────────
elif page == "📁 Projects":
    st.title("📁 Project Management")
    available = [e["name"] for e in get_source_engines()]
    tab1, tab2 = st.tabs(["➕ Create New Project", "📋 Manage Existing Projects"])

    with tab1:
        with st.form("create_project_form"):
            name    = st.text_input("Project Name *", placeholder="e.g., Ibuprofen Safety Monitoring")
            desc    = st.text_area("Description", placeholder="Describe the purpose of this monitoring project", height=70)
            kw_raw  = st.text_input("Keywords * (comma-separated)", placeholder="ibuprofen, fever, pain, side effects")
            sources = st.multiselect("Data Sources", available, default=["Reddit"])
            latency = st.selectbox("Fetch Frequency", ["realtime", "daily", "weekly"])
            if st.form_submit_button("➕ Create Project", type="primary"):
                if not name.strip() or not kw_raw.strip():
                    st.error("❌ Project name and keywords are required.")
                else:
                    try:
                        keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
                        pid = create_project(name, desc, keywords, sources, latency)
                        st.success(f"✅ Project **{name}** created! (ID: {pid})")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"❌ {e}")

    with tab2:
        projects = get_projects()
        if not projects:
            st.info("No projects yet. Use the Create tab to get started.")
        for p in projects:
            kws  = json.loads(p.get("keywords", "[]"))
            srcs = json.loads(p.get("sources", "[]"))
            sigs = get_signals(p["id"])
            with st.expander(f"📁 **{p['name']}** — {len(sigs)} signals | {p.get('latency', 'daily')} updates"):
                c1, c2 = st.columns([3, 1])
                with c1:
                    nn = st.text_input("Name",        value=p["name"],               key=f"n{p['id']}")
                    nd = st.text_area("Description",  value=p.get("description", ""),key=f"d{p['id']}", height=60)
                    nk = st.text_input("Keywords",    value=", ".join(kws),          key=f"k{p['id']}")
                    ns = st.multiselect("Sources",    available,
                                        default=[s for s in srcs if s in available], key=f"s{p['id']}")
                    nl = st.selectbox("Latency",      ["realtime", "daily", "weekly"],
                                      index=["realtime", "daily", "weekly"].index(p.get("latency", "daily")),
                                      key=f"l{p['id']}")
                with c2:
                    if st.button("💾 Save", key=f"sv{p['id']}"):
                        update_project(p["id"], nn, nd, [k.strip() for k in nk.split(",")], ns, nl)
                        st.success("Saved!"); st.rerun()
                    if st.button("🗑️ Delete", key=f"dl{p['id']}"):
                        delete_project(p["id"]); st.rerun()

# ── RUN ANALYSIS ────────────────────────────────────────────
elif page == "🔍 Run Analysis":
    st.title("🔍 Fetch & Analyse Patient Signals")
    projects = get_projects()
    if not projects:
        st.warning("⚠️ No projects found. Please create a project first.")
        st.stop()

    pm      = {p["name"]: p for p in projects}
    project = pm[st.selectbox("Select Project", list(pm.keys()))]
    keywords = json.loads(project.get("keywords", "[]"))
    sources  = json.loads(project.get("sources", "[]"))
    latency  = project.get("latency", "daily")

    st.markdown(f"""
    **Project Configuration:**
    - **Keywords:** `{', '.join(keywords)}`
    - **Data Sources:** `{', '.join(sources)}`
    - **Update Frequency:** `{latency}`
    """)
    st.info("ℹ️ **Pipeline:** Negation-aware sentiment → Entity extraction → 0-100 risk scoring → International PII detection → Topic classification")

    if st.button("🚀 Start Fetch & Analysis", type="primary"):
        all_posts = []
        with st.status("📡 Fetching data from sources...", expanded=True) as status:
            for source in sources:
                st.write(f"📡 Fetching from **{source}**...")
                try:
                    engine = get_engine(source)
                    fetched = engine.fetch(keywords)
                    st.write(f"   ✅ Retrieved {len(fetched)} relevant posts")
                    all_posts.extend(fetched)
                except Exception as e:
                    st.error(f"   ❌ {source}: {e}")
            status.update(label=f"✅ Fetched {len(all_posts)} total posts.", state="complete")

        if all_posts:
            analyzed = analyze_batch(all_posts)
            save_signals(project["id"], analyzed)
            st.success(f"✅ Saved {len(analyzed)} signals!")
            df = pd.DataFrame(analyzed)
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Total",          len(df))
            c2.metric("🔴 High Risk",   int((df["risk_level"] == "High").sum()))
            c3.metric("Avg Risk Score", f"{df['risk_score'].mean():.0f}/100")
            c4.metric("⚠️ Safety",      int(df["safety_flag"].sum()))
            c5.metric("🔒 PII",         int(df["pii_flagged"].sum()))
            st.balloons()
        else:
            st.warning("⚠️ No posts retrieved. Try adjusting your keywords or sources.")

# ── SIGNALS & TRENDS ────────────────────────────────────────
elif page == "📊 Signals & Trends":
    st.title("📊 Signals & Trend Analysis")
    projects = get_projects()
    if not projects:
        st.stop()

    pm      = {p["name"]: p for p in projects}
    project = pm[st.selectbox("Select Project", list(pm.keys()))]
    signals = get_signals(project["id"])
    if not signals:
        st.info("ℹ️ No signals found. Run analysis first.")
        st.stop()

    df = pd.DataFrame(signals)
    for col in ["topics", "entities"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: json.loads(x) if isinstance(x, str) else (x or {}))

    st.subheader("🔎 Trend Insights")
    for insight in compute_trends(signals):
        st.markdown(trend_card(insight), unsafe_allow_html=True)

    st.markdown("---")
    with st.expander("🔽 Filter Signals", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        rf  = fc1.multiselect("Risk Level",  ["High", "Medium", "Low"],            default=["High", "Medium", "Low"])
        sf  = fc2.multiselect("Sentiment",   ["Positive", "Negative", "Neutral"],  default=["Positive", "Negative", "Neutral"])
        so  = fc3.multiselect("Source",      df["source"].dropna().unique().tolist(),
                               default=df["source"].dropna().unique().tolist())
        fc4, fc5 = st.columns(2)
        safeonly = fc4.checkbox("⚠️ Safety flags only")
        piionly  = fc5.checkbox("🔒 PII flagged only")

    mask = df["risk_level"].isin(rf) & df["sentiment"].isin(sf) & df["source"].isin(so)
    if safeonly: mask &= df["safety_flag"] == 1
    if piionly:  mask &= df["pii_flagged"] == 1
    fdf = df[mask]
    if fdf.empty:
        st.warning("No signals match selected filters.")
        st.stop()

    nh = int((fdf["risk_level"] == "High").sum())
    nm = int((fdf["risk_level"] == "Medium").sum())
    nl = int((fdf["risk_level"] == "Low").sum())
    avg_score = fdf["risk_score"].mean() if "risk_score" in fdf.columns else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div style="text-align:center;padding:10px;background:#ff000010;border-radius:10px"><span style="color:#E24B4A;font-size:20px;font-weight:bold">🔴 HIGH</span><br><span style="font-size:36px;font-weight:bold">{nh}</span></div>', unsafe_allow_html=True)
    c2.markdown(f'<div style="text-align:center;padding:10px;background:#ff990010;border-radius:10px"><span style="color:#EF9F27;font-size:20px;font-weight:bold">🟡 MEDIUM</span><br><span style="font-size:36px;font-weight:bold">{nm}</span></div>', unsafe_allow_html=True)
    c3.markdown(f'<div style="text-align:center;padding:10px;background:#00ff0010;border-radius:10px"><span style="color:#639922;font-size:20px;font-weight:bold">🟢 LOW</span><br><span style="font-size:36px;font-weight:bold">{nl}</span></div>', unsafe_allow_html=True)
    c4.markdown(f'<div style="text-align:center;padding:10px;background:#6666ff10;border-radius:10px"><span style="color:#378ADD;font-size:20px;font-weight:bold">📊 AVG SCORE</span><br><span style="font-size:36px;font-weight:bold">{avg_score:.0f}<span style="font-size:18px">/100</span></span></div>', unsafe_allow_html=True)

    st.markdown("---")

    RISK_C = {"High": "#E24B4A", "Medium": "#EF9F27", "Low": "#639922"}
    SENT_C = {"Positive": "#639922", "Negative": "#E24B4A", "Neutral": "#888780"}

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Risk Distribution")
        rc = fdf["risk_level"].value_counts().reindex(["Low", "Medium", "High"], fill_value=0)
        fig, ax = plt.subplots(figsize=(6, 4), facecolor="white")
        ax.set_facecolor("white")
        bars = ax.bar(rc.index, rc.values, color=[RISK_C.get(r, "#999") for r in rc.index], edgecolor="black", linewidth=0.5)
        ax.set_xlabel("Risk Level", color="black"); ax.set_ylabel("Signals", color="black")
        ax.set_title("Patient Risk Distribution", color="black")
        ax.spines[["top", "right"]].set_visible(False); ax.tick_params(colors="black")
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f'{int(bar.get_height())}', ha="center", va="bottom", color="black")
        st.pyplot(fig); plt.close(fig)

    with col2:
        st.subheader("Sentiment Distribution")
        fig, ax = plt.subplots(figsize=(6, 4), facecolor="white")
        ax.set_facecolor("white")
        sentiments  = ["Positive", "Negative", "Neutral"]
        risk_levels = ["High", "Medium", "Low"]
        risk_colors = {"High": "#E24B4A", "Medium": "#EF9F27", "Low": "#639922"}
        bottoms = [0] * len(sentiments)
        for risk in risk_levels:
            counts = [len(fdf[(fdf["sentiment"] == s) & (fdf["risk_level"] == risk)]) for s in sentiments]
            ax.bar(sentiments, counts, bottom=bottoms, color=risk_colors[risk],
                   edgecolor="black", linewidth=0.5, label=risk, alpha=0.85)
            bottoms = [b + c for b, c in zip(bottoms, counts)]
        for i, total in enumerate(bottoms):
            if total > 0:
                ax.text(i, total, f'{int(total)}', ha="center", va="bottom", color="black")
        ax.set_xlabel("Sentiment", color="black"); ax.set_ylabel("Signals", color="black")
        ax.set_title("Patient Sentiment Distribution", color="black")
        ax.legend(title="Risk Level", loc="upper right")
        ax.spines[["top", "right"]].set_visible(False); ax.tick_params(colors="black")
        st.pyplot(fig); plt.close(fig)

    st.subheader("Risk Score Distribution (0–100)")
    if "risk_score" in fdf.columns:
        fig, ax = plt.subplots(figsize=(10, 4), facecolor="white")
        ax.set_facecolor("white")
        bins = range(0, 106, 5)
        ax.hist(fdf[fdf["risk_score"] <  25]["risk_score"], bins=bins, color="#639922", alpha=0.8, edgecolor="white", label="Low (0–24)")
        ax.hist(fdf[(fdf["risk_score"] >= 25) & (fdf["risk_score"] < 60)]["risk_score"], bins=bins, color="#EF9F27", alpha=0.8, edgecolor="white", label="Medium (25–59)")
        ax.hist(fdf[fdf["risk_score"] >= 60]["risk_score"], bins=bins, color="#E24B4A", alpha=0.8, edgecolor="white", label="High (60+)")
        ax.axvline(60, color="#E24B4A", linestyle="--", linewidth=1.5)
        ax.axvline(25, color="#EF9F27", linestyle="--", linewidth=1.5)
        ax.set_xlabel("Risk Score", color="black"); ax.set_ylabel("Signals", color="black")
        ax.set_title("Distribution of Risk Scores", color="black")
        ax.legend(); ax.spines[["top", "right"]].set_visible(False); ax.tick_params(colors="black")
        st.pyplot(fig); plt.close(fig)

    # Safety flags
    sdf = fdf[fdf["safety_flag"] == 1]
    if not sdf.empty:
        st.markdown("---")
        st.subheader("🚨 Safety & Adverse Event Alerts")
        for _, row in sdf.head(15).iterrows():
            st.markdown(f"""
            <div class="safety-card">
                <strong>{str(row.get('title', ''))[:100]}</strong><br>
                <span style="color:#666">Source: {row.get('source')} | Date: {row.get('post_date')} | Score: {row.get('risk_score', 0)}/100</span><br>
                <span style="color:#E24B4A">⚠️ Triggers: {row.get('safety_reasons', '')}</span>
            </div>""", unsafe_allow_html=True)

    # PII flags
    pdf = fdf[fdf["pii_flagged"] == 1]
    if not pdf.empty:
        st.markdown("---")
        st.subheader("🔒 PII / PHI Detection Alerts")
        for _, row in pdf.head(10).iterrows():
            st.markdown(f"""
            <div class="pii-card">
                <strong>{str(row.get('title', ''))[:100]}</strong><br>
                <span style="color:#666">Source: {row.get('source')} | Date: {row.get('post_date')}</span><br>
                <span style="color:#EF9F27">🔒 {row.get('pii_types', '')}</span>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("📋 All Signals")
    display_cols = [c for c in ["post_date", "source", "title", "sentiment", "risk_level",
                                 "risk_score", "safety_flag", "pii_flagged", "adverse_event"] if c in fdf.columns]
    st.dataframe(fdf[display_cols].head(100), width='stretch', height=400)
    csv = fdf.drop(columns=["id", "project_id"], errors="ignore").to_csv(index=False)
    st.download_button("📥 Download CSV", csv, f"{project['name']}_signals.csv", "text/csv")

# ── ADMIN ───────────────────────────────────────────────────
elif page == "⚙️ Admin":
    st.title("⚙️ System Administration")

    st.subheader("📡 Registered Data Sources")
    for engine in get_source_engines():
        with st.expander(f"🔧 {engine['name']}"):
            try:    st.json(json.loads(engine.get("config", "{}")))
            except: st.code(engine.get("config", "{}"))

    st.markdown("---")
    st.subheader("➕ Register New Data Source")
    with st.form("register_engine"):
        en   = st.text_input("Engine Name",    placeholder="e.g., CustomForum")
        eu   = st.text_input("Base URL",       placeholder="https://api.example.com")
        ek   = st.checkbox("Requires API Key")
        en2  = st.text_area("Configuration Notes")
        if st.form_submit_button("➕ Register Source") and en and eu:
            add_source_engine(en, {"base_url": eu, "requires_api_key": ek, "notes": en2})
            st.success(f"✅ Registered **{en}**!"); st.rerun()

    st.markdown("---")
    st.subheader("📊 Database Statistics")
    with get_conn() as conn:
        np_ = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        ns_ = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        nh_ = conn.execute("SELECT COUNT(*) FROM signals WHERE risk_level='High'").fetchone()[0]
        nf_ = conn.execute("SELECT COUNT(*) FROM signals WHERE safety_flag=1").fetchone()[0]
        np2 = conn.execute("SELECT COUNT(*) FROM signals WHERE pii_flagged=1").fetchone()[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📁 Projects",      np_)
    c2.metric("📊 Total Signals", ns_)
    c3.metric("⚠️ High Risk",     nh_)
    c4.metric("🚨 Safety Flags",  nf_)
    c5.metric("🔒 PII Detected",  np2)

    st.markdown("---")
    st.subheader("⚠️ Danger Zone")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑️ Clear ALL Signal Data"):
            with get_conn() as conn: conn.execute("DELETE FROM signals")
            st.success("All signals cleared."); st.rerun()
    with c2:
        if st.button("🔄 Reset Entire Database"):
            with get_conn() as conn:
                conn.execute("DROP TABLE IF EXISTS signals")
                conn.execute("DROP TABLE IF EXISTS projects")
                conn.execute("DROP TABLE IF EXISTS source_engines")
            init_db()
            st.success("Database reset."); st.rerun()

st.markdown("---")
st.caption("HealthWatch — Patient Safety Monitoring System")