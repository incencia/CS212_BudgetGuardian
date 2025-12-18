from flask import Flask, render_template, redirect, request, url_for, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from werkzeug.utils import secure_filename
import uuid
from models import db, User, Transaction
from fsm import BudgetFSM

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///budget.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db.init_app(app)

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
    transactions = Transaction.query.filter_by(user_id=user.id).all()
    total_income = sum([t.amount for t in transactions if t.type == 'income'])
    total_expense = sum([t.amount for t in transactions if t.type == 'expense'])
    net = total_income - total_expense
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

@app.route('/get_pet_state')
@login_required
def get_pet_state():
    transactions = Transaction.query.filter_by(user_id=current_user.id).all()
    total_expense = sum([t.amount for t in transactions if t.type == 'expense'])
    fsm = BudgetFSM(current_user.budget, total_expense)
    emotion, pet_image = fsm.get_pet_emotion()
    return jsonify({'emotion': emotion, 'img': url_for('static', filename=f'pet_images/{pet_image}')})

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
