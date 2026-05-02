from google.colab import files
uploaded = files.upload()  # select your data.csv when prompted

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ---------------------------
# Load data
# ---------------------------

df = pd.read_csv("data.csv")

# ---------------------------
# Keyword dictionaries
# ---------------------------

symptoms          = ["fever", "fatigue", "pain", "chills", "nausea", "weak", "headache"]
worsening_words   = ["worse", "getting worse", "not improving", "deteriorating"]
duration_words    = ["days", "weeks", "months", "still", "since"]
treatment_failure = ["not working", "no effect", "antibiotics aren't working", "not helping"]
positive_words    = ["better", "improving", "recovered"]

# ---------------------------
# Feature extraction functions
# ---------------------------

def detect_symptoms(text):          return any(word in text for word in symptoms)
def detect_worsening(text):         return any(word in text for word in worsening_words)
def detect_duration(text):          return any(word in text for word in duration_words)
def detect_treatment_failure(text): return any(word in text for word in treatment_failure)
def detect_positive(text):          return any(word in text for word in positive_words)

# ---------------------------
# Risk scoring logic
# ---------------------------

def calculate_risk(row):
    score = 0
    if row['symptom']:           score += 1
    if row['duration']:          score += 1
    if row['worsening']:         score += 2
    if row['treatment_failure']: score += 2
    if row['positive']:          score -= 1
    return score

def classify_risk(score):
    if score <= 1:   return "Low"
    elif score <= 3: return "Medium"
    else:            return "High"

def generate_explanation(row):
    reasons = []
    if row['symptom']:           reasons.append("Symptoms detected (+1)")
    if row['duration']:          reasons.append("Long duration mentioned (+1)")
    if row['worsening']:         reasons.append("Condition worsening (+2)")
    if row['treatment_failure']: reasons.append("Treatment not effective (+2)")
    if row['positive']:          reasons.append("Signs of improvement (-1)")
    return "; ".join(reasons) if reasons else "No significant indicators"

def risk_meaning(level):
    if level == "Low":      return "Mild condition, monitor symptoms"
    elif level == "Medium": return "Moderate concern, consider medical advice"
    else:                   return "High risk, seek medical attention"

# ---------------------------
# Apply processing
# ---------------------------

df['text'] = df['text'].str.lower()

df['symptom']           = df['text'].apply(detect_symptoms)
df['duration']          = df['text'].apply(detect_duration)
df['worsening']         = df['text'].apply(detect_worsening)
df['treatment_failure'] = df['text'].apply(detect_treatment_failure)
df['positive']          = df['text'].apply(detect_positive)

df['risk_score']   = df.apply(calculate_risk, axis=1)
df['risk_level']   = df['risk_score'].apply(classify_risk)
df['risk_reason']  = df.apply(generate_explanation, axis=1)
df['risk_meaning'] = df['risk_level'].apply(risk_meaning)

# ---------------------------
# Save CSV output
# ---------------------------

df.to_csv("output.csv", index=False)
print("Done. Output saved as output.csv")
print(df[['date', 'risk_score', 'risk_level', 'risk_reason', 'risk_meaning']].to_string())

# ---------------------------
# Matplotlib Graphs
# ---------------------------

fig = plt.figure(figsize=(18, 14))
fig.suptitle("Health Risk Analysis Dashboard", fontsize=16, fontweight='bold', y=0.98)
gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.35)

# Chart 1: Risk Trend Over Time
ax1 = fig.add_subplot(gs[0, :])

if 'date' in df.columns:
    df['date'] = pd.to_datetime(df['date'])
    df_sorted = df.sort_values('date').copy()
    df_sorted.set_index('date', inplace=True)

    weekly   = df_sorted['risk_score'].resample('W').mean()
    smoothed = weekly.rolling(window=3, min_periods=1).mean()

    ax1.fill_between(weekly.index, 0, 1, alpha=0.08, color='green', label='Low zone')
    ax1.fill_between(weekly.index, 1, 3, alpha=0.08, color='orange', label='Medium zone')
    ax1.fill_between(weekly.index, 3, 6, alpha=0.08, color='red', label='High zone')
    ax1.plot(weekly.index, weekly.values, 'o-', color='steelblue', linewidth=1.5, markersize=4, label='Weekly avg (raw)')
    ax1.plot(smoothed.index, smoothed.values, '-', color='darkorange', linewidth=2.5, label='Smoothed trend')
    ax1.axhline(y=1, color='green', linestyle='--', linewidth=0.8, alpha=0.5)
    ax1.axhline(y=3, color='red', linestyle='--', linewidth=0.8, alpha=0.5)
    ax1.set_xlabel("Date", fontsize=11)
    ax1.set_ylabel("Avg Risk Score", fontsize=11)
    ax1.set_title("Risk Trend Over Time (Weekly Aggregated)", fontsize=12, fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.set_ylim(0, 6)
else:
    ax1.text(0.5, 0.5, "No 'date' column found", ha='center', va='center', fontsize=13)
    ax1.set_title("Risk Trend Over Time")

# Chart 2: Risk Level Distribution (Pie)
ax2 = fig.add_subplot(gs[1, 0])

counts     = df['risk_level'].value_counts()
colors_map = {'Low': '#4CAF50', 'Medium': '#FF9800', 'High': '#F44336'}
pie_colors = [colors_map.get(l, 'grey') for l in counts.index]

ax2.pie(
    counts.values, labels=counts.index, autopct='%1.1f%%',
    colors=pie_colors, startangle=140, textprops={'fontsize': 11}
)
ax2.set_title("Risk Level Distribution", fontsize=12, fontweight='bold')

# Chart 3: Risk Score Histogram
ax3 = fig.add_subplot(gs[1, 1])

ax3.hist(df['risk_score'],
         bins=range(int(df['risk_score'].min()), int(df['risk_score'].max()) + 2),
         color='steelblue', edgecolor='white', linewidth=0.8, rwidth=0.8)

ax3.axvspan(df['risk_score'].min() - 0.5, 1.5, alpha=0.08, color='green')
ax3.axvspan(1.5, 3.5, alpha=0.08, color='orange')
ax3.axvspan(3.5, df['risk_score'].max() + 0.5, alpha=0.08, color='red')

ax3.set_xlabel("Risk Score", fontsize=11)
ax3.set_ylabel("Number of Posts", fontsize=11)
ax3.set_title("Risk Score Distribution", fontsize=12, fontweight='bold')

for rect in ax3.patches:
    height = rect.get_height()
    if height > 0:
        ax3.text(rect.get_x() + rect.get_width() / 2., height + 0.3,
                 f'{int(height)}', ha='center', va='bottom', fontsize=9, fontweight='bold')

plt.savefig("risk_dashboard.png", dpi=150, bbox_inches='tight')
plt.show()
print("Dashboard saved as risk_dashboard.png")

# ---------------------------
# Download outputs
# ---------------------------

files.download("output.csv")
files.download("risk_dashboard.png")
