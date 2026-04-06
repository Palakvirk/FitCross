import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error

# ---------------- LOAD DATA ----------------
df = pd.read_csv("fitness_exercises_large.csv")
df.dropna(inplace=True)

# ---------------- ENCODING ----------------
le_muscle = LabelEncoder()
le_diff = LabelEncoder()

df["Muscle_enc"] = le_muscle.fit_transform(df["MuscleGroup"])
df["Difficulty_enc"] = le_diff.fit_transform(df["Difficulty"])

df["Gym_Machine"] = df["Gym_Machine"].map({"Yes":1,"No":0})
df["Home_Compatible"] = df["Home_Compatible"].map({"Yes":1,"No":0})

# ---------------- LABEL ----------------
def generate_label(row):
    score = 0
    if row["Difficulty"] == "Beginner":
        score += 2
    if row["Home_Compatible"] == 1:
        score += 1
    if row["Gym_Machine"] == 1:
        score += 1
    return score

df["suitability"] = df.apply(generate_label, axis=1)

features = ["Muscle_enc","Difficulty_enc","Gym_Machine","Home_Compatible"]
X = df[features]
y = df["suitability"]

# ---------------- TRAIN ----------------
gb_model = GradientBoostingRegressor()
rf_model = RandomForestRegressor()
lr_model = LinearRegression()

gb_model.fit(X, y)
rf_model.fit(X, y)
lr_model.fit(X, y)

scores = {
    "GradientBoosting": mean_squared_error(y, gb_model.predict(X)),
    "RandomForest": mean_squared_error(y, rf_model.predict(X)),
    "LinearRegression": mean_squared_error(y, lr_model.predict(X))
}

best_model_name = min(scores, key=scores.get)

model = gb_model if best_model_name=="GradientBoosting" else rf_model if best_model_name=="RandomForest" else lr_model

# ---------------- BMI ----------------
def calculate_bmi(weight, height):
    if height == 0:
        return 0
    return round(weight / ((height/100)**2), 2)

def fitness_score(bmi, level):

    level = level.capitalize()   # 🔥 fix here

    score = 0

    if 18.5 <= bmi <= 24.9:
        score += 40
    elif 25 <= bmi <= 29.9:
        score += 25
    else:
        score += 10

    score += {
        "Beginner":20,
        "Intermediate":30,
        "Advanced":40
    }[level]

    return score

# ---------------- PROGRESSION ----------------
def generate_progression(level):
    if level == "Beginner":
        return ["Week1: 2x10","Week2: 3x10","Week3: 3x12","Week4: 3x15"]
    elif level == "Intermediate":
        return ["Week1: 3x10","Week2: 4x10","Week3: 4x12","Week4: 4x15"]
    else:
        return ["Week1: 4x8","Week2: 4x10","Week3: 5x10","Week4: 5x12"]

# ---------------- SPLIT ----------------
def weekly_split(days):
    splits = {
        3: {"Day 1":["Chest"],"Day 2":["Back"],"Day 3":["Legs"]},
        4: {"Day 1":["Chest"],"Day 2":["Back"],"Day 3":["Legs"],"Day 4":["Shoulders"]},
        5: {"Day 1":["Chest"],"Day 2":["Back"],"Day 3":["Legs"],"Day 4":["Shoulders"],"Day 5":["Arms"]}
    }
    return splits.get(days, splits[4])

# ---------------- RECOMMENDER ----------------
def recommend_exercises(muscles, location, injuries, level, age):

    subset = df[df["MuscleGroup"].isin(muscles)].copy()

    if location == "Home":
        subset = subset[subset["Home_Compatible"] == 1]
    else:
        subset = subset[subset["Gym_Machine"] == 1]

    if injuries:
        subset = subset[~subset["Avoid_If_Injury"].isin(injuries)]

    subset["ML_score"] = model.predict(subset[features])
    subset = subset.sort_values("ML_score", ascending=False)

    top = subset.head(4)

    return top[["Exercise","Difficulty"]].to_dict("records")