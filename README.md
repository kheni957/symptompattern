from google.colab import files
uploaded = files.upload()  # select your data.csv when prompted

import pandas as pd
import re

# Load data
df = pd.read_csv("data.csv")

# ---------------------------
# Keyword dictionaries
# ---------------------------

symptoms = ["fever", "fatigue", "pain", "chills", "nausea", "weak", "headache"]

worsening_words = ["worse", "getting worse", "not improving", "deteriorating"]

duration_words = ["days", "weeks", "months", "still", "since"]

treatment_failure = ["not working", "no effect", "antibiotics aren't working", "not helping"]

positive_words = ["better", "improving", "recovered"]

# ---------------------------
# Feature extraction functions
# ---------------------------

def detect_symptoms(text):
    return any(word in text for word in symptoms)

def detect_worsening(text):
    return any(word in text for word in worsening_words)

def detect_duration(text):
    return any(word in text for word in duration_words)

def detect_treatment_failure(text):
    return any(word in text for word in treatment_failure)

def detect_positive(text):
    return any(word in text for word in positive_words)

# ---------------------------
# Risk scoring logic
# ---------------------------

def calculate_risk(row):
    score = 0

    if row['symptom']:
        score += 1
    if row['duration']:
        score += 1
    if row['worsening']:
        score += 2
    if row['treatment_failure']:
        score += 2
    if row['positive']:
        score -= 1  # improvement lowers risk

    return score

def classify_risk(score):
    if score <= 1:
        return "Low"
    elif score <= 3:
        return "Medium"
    else:
        return "High"

# ---------------------------
# Apply processing
# ---------------------------

df['text'] = df['text'].str.lower()

df['symptom'] = df['text'].apply(detect_symptoms)
df['duration'] = df['text'].apply(detect_duration)
df['worsening'] = df['text'].apply(detect_worsening)
df['treatment_failure'] = df['text'].apply(detect_treatment_failure)
df['positive'] = df['text'].apply(detect_positive)

df['risk_score'] = df.apply(calculate_risk, axis=1)
df['risk_level'] = df['risk_score'].apply(classify_risk)

# ---------------------------
# Save output
# ---------------------------

df.to_csv("output.csv", index=False)


# ---------------------------
# 🧠 Explanation generator
# ---------------------------

def generate_explanation(row):
    reasons = []

    if row['symptom']:
        reasons.append("Symptoms detected (+1)")
    if row['duration']:
        reasons.append("Long duration mentioned (+1)")
    if row['worsening']:
        reasons.append("Condition worsening (+2)")
    if row['treatment_failure']:
        reasons.append("Treatment not effective (+2)")
    if row['positive']:
        reasons.append("Signs of improvement (-1)")

    return "; ".join(reasons) if reasons else "No significant indicators"


# ---------------------------
# Risk meaning
# ---------------------------

def risk_meaning(level):
    if level == "Low":
        return "Mild condition, monitor symptoms"
    elif level == "Medium":
        return "Moderate concern, consider medical advice"
    else:
        return "High risk, seek medical attention"


# ---------------------------
# Apply processing
# ---------------------------

df['text'] = df['text'].str.lower()

df['symptom'] = df['text'].apply(detect_symptoms)
df['duration'] = df['text'].apply(detect_duration)
df['worsening'] = df['text'].apply(detect_worsening)
df['treatment_failure'] = df['text'].apply(detect_treatment_failure)
df['positive'] = df['text'].apply(detect_positive)

df['risk_score'] = df.apply(calculate_risk, axis=1)
df['risk_level'] = df['risk_score'].apply(classify_risk)

# Add explanation + meaning
df['risk_reason'] = df.apply(generate_explanation, axis=1)
df['risk_meaning'] = df['risk_level'].apply(risk_meaning)

# ---------------------------
# Save output
# ---------------------------

df.to_csv("output.csv", index=False)

print("Done. Output saved as output.csv")





