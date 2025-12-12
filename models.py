from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password_hash = db.Column(db.String(120))
    budget = db.Column(db.Float, default=0.0)
    # Add extra fields as needed

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(10))  # 'expense' or 'income'
    category = db.Column(db.String(50))
    date = db.Column(db.DateTime, nullable=False)
