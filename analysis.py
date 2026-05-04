import re
import json
from datetime import datetime

# ===========================================================
# SENTIMENT ANALYSIS (TextBlob — no API needed)
# ===========================================================

def analyze_sentiment(text: str) -> dict:
    try:
        from textblob import TextBlob
        blob = TextBlob(text)
        score = blob.sentiment.polarity  # -1 to +1
        if score > 0.1:
            label = "Positive"
        elif score < -0.1:
            label = "Negative"
        else:
            label = "Neutral"
        return {
            "sentiment": label,
            "sentiment_score": round(score, 3),
            "confidence": round(abs(score), 3)
        }
    except ImportError:
        # Fallback: keyword-based sentiment
        text_l = text.lower()
        pos = sum(1 for w in ["better", "improving", "recovered", "relief", "resolved"] if w in text_l)
        neg = sum(1 for w in ["worse", "pain", "suffering", "horrible", "failed", "not working"] if w in text_l)
        if pos > neg:
            return {"sentiment": "Positive", "sentiment_score": 0.3, "confidence": 0.5}
        elif neg > pos:
            return {"sentiment": "Negative", "sentiment_score": -0.3, "confidence": 0.5}
        return {"sentiment": "Neutral", "sentiment_score": 0.0, "confidence": 0.4}


# ===========================================================
# ENTITY EXTRACTION (regex + keyword lists)
# ===========================================================

DRUG_TERMS = [
    "ibuprofen", "paracetamol", "acetaminophen", "amoxicillin", "doxycycline",
    "azithromycin", "metformin", "prednisone", "prednisolone", "augmentin",
    "cephalexin", "ciprofloxacin", "metronidazole", "tylenol", "motrin",
    "aspirin", "naproxen", "hydroxychloroquine", "remicade", "humira",
    "antibiotics", "antibiotic", "nsaids", "antihistamine"
]

CONDITION_TERMS = [
    "fever", "fatigue", "covid", "long covid", "fibromyalgia", "lupus",
    "lyme disease", "pots", "mcas", "eds", "cfs", "me/cfs", "chronic fatigue",
    "arthritis", "thyroid", "hypothyroidism", "anemia", "infection",
    "pneumonia", "bronchitis", "sinusitis", "appendicitis", "gastritis",
    "diverticulitis", "endometriosis", "mono", "mononucleosis", "sepsis"
]

SYMPTOM_TERMS = [
    "fever", "fatigue", "chills", "nausea", "vomiting", "headache",
    "body aches", "muscle pain", "joint pain", "weakness", "dizziness",
    "shortness of breath", "chest pain", "rash", "swollen lymph nodes",
    "night sweats", "weight loss", "brain fog", "palpitations"
]

def extract_entities(text: str) -> dict:
    text_l = text.lower()
    entities = {
        "drugs":      [d for d in DRUG_TERMS      if d in text_l],
        "conditions": [c for c in CONDITION_TERMS if c in text_l],
        "symptoms":   [s for s in SYMPTOM_TERMS   if s in text_l],
    }
    # Extract age mentions e.g. "24F", "32M", "24 year old"
    ages = re.findall(r'\b(\d{1,2})[mf]\b|\b(\d{1,3})\s*(?:year[s]?\s*old|yo)\b', text_l)
    entities["ages"] = list(set([a[0] or a[1] for a in ages if any(a)]))
    return entities


# ===========================================================
# PII / PHI DETECTION
# ===========================================================

PII_PATTERNS = {
    "email":         r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "phone":         r'\b(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
    "ssn":           r'\b\d{3}-\d{2}-\d{4}\b',
    "full_name":     r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',
    "age_gender":    r'\b\d{1,3}[MFmf]\b',
    "location":      r'\b(?:in|from|at|near)\s+[A-Z][a-z]+(?:,\s*[A-Z]{2})?\b',
    "dob":           r'\b(?:born|dob|date of birth)[:\s]+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
}

def detect_pii(text: str) -> dict:
    found = {}
    for label, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, text)
        if matches:
            found[label] = matches if isinstance(matches[0], str) else [m for m in matches if m]
    return {
        "pii_flagged": len(found) > 0,
        "pii_details": json.dumps(found) if found else ""
    }


# ===========================================================
# RISK SCORING
# ===========================================================

SYMPTOM_KW   = ["fever", "fatigue", "pain", "chills", "nausea", "weak", "headache"]
WORSENING_KW = ["worse", "getting worse", "not improving", "deteriorating"]
DURATION_KW  = ["days", "weeks", "months", "still", "since"]
FAILURE_KW   = ["not working", "no effect", "not helping", "antibiotics aren't working"]
POSITIVE_KW  = ["better", "improving", "recovered"]

def score_risk(text: str) -> dict:
    text_l = text.lower()
    has_symptom  = any(w in text_l for w in SYMPTOM_KW)
    has_duration = any(w in text_l for w in DURATION_KW)
    has_worsen   = any(w in text_l for w in WORSENING_KW)
    has_failure  = any(w in text_l for w in FAILURE_KW)
    has_positive = any(w in text_l for w in POSITIVE_KW)

    score = 0
    reasons = []
    if has_symptom:  score += 1; reasons.append("Symptoms detected (+1)")
    if has_duration: score += 1; reasons.append("Long duration (+1)")
    if has_worsen:   score += 2; reasons.append("Condition worsening (+2)")
    if has_failure:  score += 2; reasons.append("Treatment not effective (+2)")
    if has_positive: score -= 1; reasons.append("Signs of improvement (-1)")

    level = "Low" if score <= 1 else ("Medium" if score <= 3 else "High")
    meaning = {
        "Low":    "Mild condition, monitor symptoms",
        "Medium": "Moderate concern, consider medical advice",
        "High":   "High risk, seek medical attention"
    }[level]

    # Confidence based on how many signals fired
    signals_fired = sum([has_symptom, has_duration, has_worsen, has_failure])
    confidence = round(min(0.5 + signals_fired * 0.12, 0.95), 2)

    return {
        "risk_score":   score,
        "risk_level":   level,
        "risk_reason":  "; ".join(reasons) if reasons else "No significant indicators",
        "risk_meaning": meaning,
        "confidence":   confidence
    }


# ===========================================================
# SAFETY / ADVERSE EVENT FLAGS
# ===========================================================

SAFETY_KEYWORDS = [
    "adverse", "hospitalized", "hospitalised", "emergency", "er visit",
    "icu", "seizure", "overdose", "anaphylaxis", "allergic reaction",
    "suicidal", "self harm", "attempted suicide", "heart attack",
    "stroke", "organ failure", "sepsis", "coma", "died", "death",
    "serious side effect", "life threatening", "ambulance", "911"
]

def detect_safety(text: str) -> dict:
    text_l = text.lower()
    triggered = [kw for kw in SAFETY_KEYWORDS if kw in text_l]
    return {
        "safety_flag":   len(triggered) > 0,
        "safety_reason": ", ".join(triggered) if triggered else ""
    }


# ===========================================================
# FULL PIPELINE — runs all analysis on a single post
# ===========================================================

def analyze_post(post: dict) -> dict:
    text = post.get("text", "")

    sentiment = analyze_sentiment(text)
    entities  = extract_entities(text)
    pii       = detect_pii(text)
    risk      = score_risk(text)
    safety    = detect_safety(text)

    return {
        **post,
        **sentiment,
        "entities":    json.dumps(entities),
        **pii,
        **risk,
        **safety,
    }


def analyze_batch(posts: list) -> list:
    return [analyze_post(p) for p in posts]


# ===========================================================
# AGGREGATE STATS for a project's signals
# ===========================================================

def aggregate_stats(signals: list) -> dict:
    import pandas as pd

    if not signals:
        return {}

    df = pd.DataFrame(signals)

    stats = {
        "total":          len(df),
        "high_risk":      int((df["risk_level"] == "High").sum()),
        "medium_risk":    int((df["risk_level"] == "Medium").sum()),
        "low_risk":       int((df["risk_level"] == "Low").sum()),
        "safety_flags":   int(df["safety_flag"].sum()) if "safety_flag" in df else 0,
        "pii_flags":      int(df["pii_flagged"].sum()) if "pii_flagged" in df else 0,
        "avg_confidence": round(df["confidence"].mean(), 2) if "confidence" in df else 0,
        "sentiment_dist": df["sentiment"].value_counts().to_dict() if "sentiment" in df else {},
        "source_dist":    df["source"].value_counts().to_dict() if "source" in df else {},
        "risk_dist":      df["risk_level"].value_counts().to_dict() if "risk_level" in df else {},
    }

    # Top entities
    all_conditions = []
    all_drugs      = []
    all_symptoms   = []
    for row in signals:
        try:
            ents = json.loads(row.get("entities", "{}"))
            all_conditions.extend(ents.get("conditions", []))
            all_drugs.extend(ents.get("drugs", []))
            all_symptoms.extend(ents.get("symptoms", []))
        except:
            pass

    from collections import Counter
    stats["top_conditions"] = dict(Counter(all_conditions).most_common(10))
    stats["top_drugs"]      = dict(Counter(all_drugs).most_common(10))
    stats["top_symptoms"]   = dict(Counter(all_symptoms).most_common(10))

    return stats