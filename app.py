from flask import Flask, render_template, redirect, request, url_for, jsonify, abort, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
import uuid
from models import db, User, Transaction
from fsm import BudgetFSM
from sqlalchemy import func

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///budget.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Avoid aggressive static caching while developing (helps CSS changes show up).
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db.init_app(app)
app.jinja_env.auto_reload = True

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Flask 3.x removed before_first_request; create tables at startup.
with app.app_context():
    db.create_all()

# Allowed file extensions for uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/how-it-works')
def how_it_works():
    # Public “How it Works” page with a demo FSM + flowchart.
    return render_template(
        'how_it_works.html',
        pet_map={
            "S0": "neutral-car.gif",
            "S1": "slight_overspend.gif",
            "S2": "major_overspend.gif",
            "S3": "happy-happy-happy-cat.gif",
        },
    )


# ---- PWA helpers ----
# Service workers need to be served from the site root to control the whole app.
@app.route('/sw.js')
def service_worker():
    resp = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
    # Avoid stale SW during development.
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/manifest.webmanifest')
def manifest():
    return send_from_directory(app.static_folder, 'manifest.webmanifest', mimetype='application/manifest+json')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_exists = User.query.filter_by(username=username).first()
        if user_exists:
            error = f"Username '{username}' is already taken. Please choose a different username."
            return render_template('login.html', register=True, error=error)
        password_hash = generate_password_hash(password)
        user = User(username=username, password_hash=password_hash, budget=1000)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('login.html', register=True)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password.")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user
    # Dashboard is DAILY-only and naturally "resets" at midnight by filtering to today.
    now = datetime.now()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_today = start_today + timedelta(days=1)

    transactions = (
        Transaction.query.filter(
            Transaction.user_id == user.id,
            Transaction.date >= start_today,
            Transaction.date < end_today,
        )
        .order_by(Transaction.date.desc())
        .all()
    )

    total_income = sum(t.amount for t in transactions if t.type == 'income')
    total_expense = sum(t.amount for t in transactions if t.type == 'expense')
    net = total_income - total_expense

    # Treat user.budget as a DAILY budget for the dashboard.
    fsm = BudgetFSM(user.budget, total_expense)
    emotion, pet_image = fsm.get_pet_emotion()
    resp_amount = request.args.get('extracted_amount')
    return render_template('dashboard.html',
                           transactions=transactions, budget=user.budget,
                           total_expense=total_expense, net=net,
                           emotion=emotion, pet_image=pet_image,
                           extracted_amount=resp_amount)

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    amount = float(request.form['amount'])
    category = request.form['category']
    tx_type = request.form['type']  # 'income' or 'expense'
    transaction = Transaction(user_id=current_user.id, amount=amount, category=category, type=tx_type, date=datetime.now())
    db.session.add(transaction)
    db.session.commit()
    return redirect(url_for('dashboard'))


@app.route('/set_budget', methods=['POST'])
@login_required
def set_budget():
    """
    User enters a spending limit in daily/weekly/monthly terms.
    Internally we store it as a DAILY budget (User.budget) so:
    - Dashboard compares today's spending vs daily budget
    - Insights derives weekly/monthly/yearly budgets from daily
    """
    raw_amount = request.form.get('budget_amount', '').strip()
    period = request.form.get('budget_period', 'daily').strip().lower()

    try:
        amount = float(raw_amount)
    except ValueError:
        return redirect(url_for('dashboard'))

    if amount < 0:
        return redirect(url_for('dashboard'))

    if period == 'daily':
        daily_budget = amount
    elif period == 'weekly':
        daily_budget = amount / 7.0
    elif period == 'monthly':
        # Approx month length; used consistently across Insights too.
        daily_budget = amount / 30.0
    elif period == 'yearly':
        daily_budget = amount / 365.0
    else:
        daily_budget = amount

    current_user.budget = float(daily_budget)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/get_pet_state')
@login_required
def get_pet_state():
    # Keep API consistent with the dashboard: return DAILY pet state.
    now = datetime.now()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_today = start_today + timedelta(days=1)
    transactions = (
        Transaction.query.filter(
            Transaction.user_id == current_user.id,
            Transaction.date >= start_today,
            Transaction.date < end_today,
        ).all()
    )
    total_expense = sum(t.amount for t in transactions if t.type == 'expense')
    fsm = BudgetFSM(current_user.budget, total_expense)
    emotion, pet_image = fsm.get_pet_emotion()
    return jsonify({'emotion': emotion, 'img': url_for('static', filename=f'pet_images/{pet_image}')})


def _month_add(year: int, month: int, delta_months: int) -> tuple[int, int]:
    """Add delta months to a (year, month) pair."""
    idx = year * 12 + (month - 1) + delta_months
    return idx // 12, (idx % 12) + 1


def _period_budget(daily_budget: float, period: str) -> float:
    """
    Convert a DAILY budget into a period budget.

    Assumption: user.budget represents DAILY budget.
    - weekly: daily * 7
    - monthly: daily * 30 (approx)
    - yearly: daily * 365 (approx)
    """
    if period == "daily":
        return daily_budget
    if period == "weekly":
        return daily_budget * 7
    if period == "monthly":
        return daily_budget * 30
    if period == "yearly":
        return daily_budget * 365
    raise ValueError(f"Unknown period: {period}")


def _bar_data(values: list[tuple[str, float]]) -> list[dict]:
    max_v = max([v for _, v in values] + [0.0])
    denom = max_v if max_v > 0 else 1.0
    return [{"label": k, "value": float(v), "pct": (float(v) / denom) * 100.0} for k, v in values]


@app.route('/insights')
@login_required
def insights():
    """
    Spending insights by period (daily/weekly/monthly/yearly) with bar graphs
    and an FSM result per timeframe, plus 6-month spending history.
    """
    user = current_user
    now = datetime.now()

    # ---- DAILY series (last 7 days) ----
    daily_days = 7
    start_daily = (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=daily_days - 1))
    daily_rows = (
        db.session.query(func.strftime('%Y-%m-%d', Transaction.date), func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(
            Transaction.user_id == user.id,
            Transaction.type == 'expense',
            Transaction.date >= start_daily,
        )
        .group_by(func.strftime('%Y-%m-%d', Transaction.date))
        .all()
    )
    daily_map = {k: float(v) for k, v in daily_rows}
    daily_values = []
    for i in range(daily_days - 1, -1, -1):
        d = (now - timedelta(days=i)).date()
        key = d.strftime('%Y-%m-%d')
        label = d.strftime('%b %d')
        daily_values.append((label, daily_map.get(key, 0.0)))
    today_key = now.strftime('%Y-%m-%d')
    daily_total = daily_map.get(today_key, 0.0)
    daily_budget = _period_budget(user.budget, "daily")
    daily_emotion, daily_pet = BudgetFSM(daily_budget, daily_total).get_pet_emotion()

    # ---- WEEKLY series (last 8 weeks) ----
    weekly_weeks = 8
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    this_week_start = start_today - timedelta(days=start_today.weekday())  # Monday
    start_weekly = this_week_start - timedelta(weeks=weekly_weeks - 1)
    weekly_rows = (
        db.session.query(func.strftime('%Y-%W', Transaction.date), func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(
            Transaction.user_id == user.id,
            Transaction.type == 'expense',
            Transaction.date >= start_weekly,
        )
        .group_by(func.strftime('%Y-%W', Transaction.date))
        .all()
    )
    weekly_map = {k: float(v) for k, v in weekly_rows}
    weekly_values = []
    for i in range(weekly_weeks - 1, -1, -1):
        ws = this_week_start - timedelta(weeks=i)
        key = ws.strftime('%Y-%W')
        label = ws.strftime('Wk %b %d')
        weekly_values.append((label, weekly_map.get(key, 0.0)))
    weekly_total = weekly_map.get(this_week_start.strftime('%Y-%W'), 0.0)
    weekly_budget = _period_budget(user.budget, "weekly")
    weekly_emotion, weekly_pet = BudgetFSM(weekly_budget, weekly_total).get_pet_emotion()

    # ---- MONTHLY series (last 6 months) ----
    monthly_months = 6
    y, m = now.year, now.month
    start_y, start_m = _month_add(y, m, -(monthly_months - 1))
    start_monthly = now.replace(year=start_y, month=start_m, day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_rows = (
        db.session.query(func.strftime('%Y-%m', Transaction.date), func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(
            Transaction.user_id == user.id,
            Transaction.type == 'expense',
            Transaction.date >= start_monthly,
        )
        .group_by(func.strftime('%Y-%m', Transaction.date))
        .all()
    )
    monthly_map = {k: float(v) for k, v in monthly_rows}
    monthly_values = []
    for i in range(monthly_months - 1, -1, -1):
        yy, mm = _month_add(y, m, -i)
        key = f"{yy:04d}-{mm:02d}"
        label = datetime(yy, mm, 1).strftime('%b %Y')
        monthly_values.append((label, monthly_map.get(key, 0.0)))
    this_month_key = f"{y:04d}-{m:02d}"
    monthly_total = monthly_map.get(this_month_key, 0.0)
    monthly_budget = _period_budget(user.budget, "monthly")
    monthly_emotion, monthly_pet = BudgetFSM(monthly_budget, monthly_total).get_pet_emotion()

    # ---- YEARLY series (last 5 years) ----
    yearly_years = 5
    start_yearly = now.replace(year=now.year - (yearly_years - 1), month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    yearly_rows = (
        db.session.query(func.strftime('%Y', Transaction.date), func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(
            Transaction.user_id == user.id,
            Transaction.type == 'expense',
            Transaction.date >= start_yearly,
        )
        .group_by(func.strftime('%Y', Transaction.date))
        .all()
    )
    yearly_map = {k: float(v) for k, v in yearly_rows}
    yearly_values = []
    for i in range(yearly_years - 1, -1, -1):
        yy = now.year - i
        key = f"{yy:04d}"
        yearly_values.append((key, yearly_map.get(key, 0.0)))
    yearly_total = yearly_map.get(f"{now.year:04d}", 0.0)
    yearly_budget = _period_budget(user.budget, "yearly")
    yearly_emotion, yearly_pet = BudgetFSM(yearly_budget, yearly_total).get_pet_emotion()

    # ---- Spending history (last ~6 months) ----
    history_start = now - timedelta(days=183)
    history = (
        Transaction.query.filter(
            Transaction.user_id == user.id,
            Transaction.type == 'expense',
            Transaction.date >= history_start,
        )
        .order_by(Transaction.date.desc())
        .all()
    )

    return render_template(
        'insights.html',
        daily=_bar_data(daily_values),
        weekly=_bar_data(weekly_values),
        monthly=_bar_data(monthly_values),
        yearly=_bar_data(yearly_values),
        daily_total=daily_total,
        weekly_total=weekly_total,
        monthly_total=monthly_total,
        yearly_total=yearly_total,
        daily_budget=daily_budget,
        weekly_budget=weekly_budget,
        monthly_budget=monthly_budget,
        yearly_budget=yearly_budget,
        daily_emotion=daily_emotion,
        weekly_emotion=weekly_emotion,
        monthly_emotion=monthly_emotion,
        yearly_emotion=yearly_emotion,
        daily_pet=daily_pet,
        weekly_pet=weekly_pet,
        monthly_pet=monthly_pet,
        yearly_pet=yearly_pet,
        history=history,
    )

@app.route('/upload_receipt', methods=['POST'])
@login_required
def upload_receipt():
    if 'receipt' not in request.files:
        return "No file", 400
    file = request.files['receipt']
    if file.filename == '':
        return "No selected file", 400
    if not allowed_file(file.filename):
        abort(400, description="Unsupported file extension.")
    # Sanitize filename
    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1]
    unique_filename = f"user{current_user.id}_" + str(uuid.uuid4()) + ext
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(file_path)

    # Lazy import so the app can start even if OCR deps are missing.
    import easyocr
    reader = easyocr.Reader(['en'])
    results = reader.readtext(file_path, detail=0)
    import re
    amount = ''
    for line in results:
        match = re.search(r'\d+\.\d{2}', line)
        if match:
            amount = match.group()
            break
    return redirect(url_for('dashboard', extracted_amount=amount))

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')
    app.run(debug=debug_mode)
