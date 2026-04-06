import os
from datetime import datetime, timezone

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from forms import RegistrationForm, LoginForm
from models import db, User, WeightLog, DailyProgress
from workout_model import (
    weekly_split,
    recommend_exercises,
    calculate_bmi,
    fitness_score,
    generate_progression
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fallback-dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'

# Init extensions
db.init_app(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------- HELPERS ----------------

def generate_ai_plan(user):
    """
    Generate an AI fitness plan for the user.
    The result is cached in user.ai_plan to avoid repeated API calls.
    """
    if getattr(user, 'ai_plan', None):
        return user.ai_plan

    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        prompt = f"""
        Create a personalized fitness plan.

        Age: {user.age}
        Goal: {user.goal}
        Fitness Level: {user.fitness_level}
        Diet: {user.diet_preference}
        Medical issues: {user.disease}
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        plan = response.choices[0].message.content

    except Exception as e:
        print("AI Error:", e)
        plan = "Start slow, stay consistent, hydrate well."

    # Cache the plan on the user record
    user.ai_plan = plan
    db.session.commit()

    return plan


def bmi_category(bmi):
    if bmi < 18.5:
        return "Underweight", "Focus on strength and nutrition"
    elif bmi < 25:
        return "Fit", "Maintain consistency"
    elif bmi < 30:
        return "Overweight", "Include cardio"
    else:
        return "Obese", "Start slow and build gradually"


def fitness_score_category(score):
    if score >= 70:
        return "Excellent", "High fitness level"
    elif score >= 50:
        return "Moderate", "Average fitness level"
    else:
        return "Beginner", "Start gradually"


def owned_or_403(user_id):
    """Abort with 403 if the logged-in user is not the owner of the resource."""
    if current_user.id != user_id:
        abort(403)


# ---------------- ROUTES ----------------

@app.route('/')
def home():
    return render_template("index.html", user=current_user)


@app.route('/signup', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()

    if form.validate_on_submit():
        hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')

        user = User(
            username=form.username.data,
            email=form.email.data,
            password=hashed_pw,
            age=form.age.data,
            gender=form.gender.data,
            height=form.height.data,
            weight=form.weight.data,
            goal=form.goal.data,
            diet_preference=form.diet_preference.data,
            fitness_level=form.fitness_level.data,
            disease=form.disease.data
        )

        db.session.add(user)
        db.session.commit()

        flash('Account created successfully!', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('dashboard', user_id=user.id))

        flash('Invalid credentials', 'danger')

    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/dashboard/<int:user_id>')
@login_required
def dashboard(user_id):
    owned_or_403(user_id)

    user = User.query.get_or_404(user_id)

    logs = WeightLog.query.filter_by(user_id=user_id).order_by(WeightLog.date).all()
    dates = [log.date.strftime("%d %b") for log in logs]
    weights = [log.weight for log in logs]

    ai_plan = generate_ai_plan(user)

    return render_template(
        'dashboard.html',
        user=user,
        dates=dates,
        weights=weights,
        workout_plan=ai_plan
        cal_recom="Get your personalized calorie & macro breakdown."
    )


@app.route('/log_weight/<int:user_id>', methods=['POST'])
@login_required
def log_weight(user_id):
    owned_or_403(user_id)

    weight = request.form['weight']
    entry = WeightLog(user_id=user_id, weight=weight)
    db.session.add(entry)
    db.session.commit()
    return redirect(url_for('dashboard', user_id=user_id))


@app.route('/save_progress', methods=['POST'])
@login_required
def save_progress():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        user_id = data['user_id']
        owned_or_403(user_id)

        meals = data['meals']
        workouts = data['workouts']
        water = data['water']
        cheat = data['cheat']

    except (KeyError, TypeError) as e:
        return jsonify({"error": f"Missing field: {e}"}), 400

    today = datetime.now(timezone.utc).date()

    entry = DailyProgress.query.filter_by(user_id=user_id, date=today).first()

    if not entry:
        entry = DailyProgress(user_id=user_id, date=today)

    entry.meals_done = meals
    entry.workouts_done = workouts
    entry.water_glasses = water
    entry.cheat_percent = cheat

    db.session.add(entry)
    db.session.commit()

    return jsonify({"status": "saved"})


@app.route("/generate_workout/<int:user_id>", methods=["GET", "POST"])
@login_required
def generate_workout(user_id):
    owned_or_403(user_id)

    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        age = int(request.form["age"])
        weight = float(request.form["weight"])
        height = float(request.form["height"])
        level = request.form["level"]
        location = request.form["location"]
        days = int(request.form["days"])
        injuries = request.form.getlist("injuries")

        bmi = calculate_bmi(weight, height)
        score = fitness_score(bmi, level)

        bmi_cat, bmi_advice = bmi_category(bmi)
        fit_cat, fit_advice = fitness_score_category(score)

        progression = generate_progression(level)

        split = weekly_split(days)
        plan = {
            day: recommend_exercises(muscles, location, injuries, level, age)
            for day, muscles in split.items()
        }

        return render_template(
            "workout.html",
            plan=plan,
            bmi=round(bmi, 2),
            score=score,
            bmi_cat=bmi_cat,
            bmi_advice=bmi_advice,
            fit_cat=fit_cat,
            fit_advice=fit_advice,
            progression=progression,
            user=user
        )

    return render_template(
        "workout.html",
        plan=None,
        bmi=None,
        score=None,
        bmi_cat=None,
        bmi_advice=None,
        fit_cat=None,
        fit_advice=None,
        progression=None,
        user=user
    )


@app.route('/calorie')
def calorie():
    return render_template("cal_cal.html")


@app.route('/strength')
def strength():
    return render_template("strength.html")


@app.route('/nutrition')
def nutrition():
    return render_template("nutrition.html")


@app.route('/mobility')
def mobility():
    return render_template("mobility.html")


@app.route('/fatloss')
def fatloss():
    return render_template("fatloss.html")


@app.route('/bmr')
def bmr():
    return render_template("bmr_cal.html")


@app.route('/bmi')
def bmi():
    return render_template("bmi_cal.html")


@app.route('/workout_tips')
def workout_tips():
    return render_template("workout_tips.html")

@app.route('/cal_recom')
def cal_recom():
    return render_template("calorie_recommender.html")


# ---------------- RUN ----------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)