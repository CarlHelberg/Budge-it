from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import calendar
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///budget.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    categories = db.relationship('Category', backref='budget', lazy=True)
    # Explicitly specify the foreign key for transactions relationship
    transactions = db.relationship('Transaction',
                                  foreign_keys='Transaction.budget_id',
                                  backref='budget', lazy=True)
    # Separate relationship for transfers
    transfers_to = db.relationship('Transaction',
                                  foreign_keys='Transaction.transfer_to_budget_id',
                                  backref='transfer_to_budget', lazy=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'), nullable=False)
    budgeted_amount = db.Column(db.Float, default=0.0)
    is_future_expense = db.Column(db.Boolean, default=False)
    is_transfer = db.Column(db.Boolean, default=False)
    target_date = db.Column(db.Date, nullable=True)
    target_amount = db.Column(db.Float, nullable=True)

    transactions = db.relationship('Transaction', backref='category', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)
    # Explicitly specify the foreign key name
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    is_income = db.Column(db.Boolean, default=False)
    is_transfer = db.Column(db.Boolean, default=False)
    # Explicitly specify the foreign key name
    transfer_to_budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Helper function for template use
@app.template_filter('money_format')
def money_format(value):
    return "${:.2f}".format(value)

@app.context_processor
def utility_processor():
    def now():
            return datetime.now()

        # Add the min function to be available in templates
    def min_value(a, b):
            return min(a, b)

    return dict(now=now, min=min_value)

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists')
            return redirect(url_for('register'))

        new_user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful!')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid username or password')
            return redirect(url_for('login'))

        login_user(user)
        return redirect(url_for('dashboard'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    budgets = Budget.query.all()
    # Calculate spending information for each budget
    for budget in budgets:
        # Calculate total spent (sum of all expenses)
        expenses = Transaction.query.filter_by(budget_id=budget.id, is_income=False).all()
        budget.total_spent = sum(t.amount for t in expenses)

        # Calculate available amount
        budget.available = budget.balance

        # Calculate percentage spent
        total_income = sum(t.amount for t in Transaction.query.filter_by(budget_id=budget.id, is_income=True).all())
        if total_income > 0:
            budget.spend_percentage = (budget.total_spent / total_income) * 100
        else:
            budget.spend_percentage = 0

    return render_template('dashboard.html', budgets=budgets)

@app.route('/budget/create', methods=['GET', 'POST'])
@login_required
def create_budget():
    if request.method == 'POST':
        name = request.form.get('name')
        initial_balance = float(request.form.get('initial_balance') or 0)

        new_budget = Budget(name=name, balance=initial_balance)
        db.session.add(new_budget)
        db.session.commit()

        return redirect(url_for('dashboard'))

    return render_template('create_budget.html')

@app.route('/budget/<int:budget_id>')
@login_required
def view_budget(budget_id):
    budget = Budget.query.get_or_404(budget_id)
    categories = Category.query.filter_by(budget_id=budget_id).all()

    total_income = sum(t.amount for t in Transaction.query.filter_by(budget_id=budget_id, is_income=True).all())
    total_budgeted = sum(c.budgeted_amount for c in categories)

    # Calculate available amount for each category
    for category in categories:
        # Get all transactions for this category
        category_transactions = Transaction.query.filter_by(category_id=category.id).all()
        # Sum of all expenses for this category
        total_spent = sum(t.amount for t in category_transactions if not t.is_income)
        # Calculate available amount
        category.available = category.budgeted_amount - total_spent

    # Get recent transactions
    recent_transactions = Transaction.query.filter_by(budget_id=budget_id).order_by(Transaction.date.desc()).limit(5).all()

    return render_template('view_budget.html',
                           budget=budget,
                           categories=categories,
                           total_income=total_income,
                           total_budgeted=total_budgeted,
                           transactions=recent_transactions,
                           active_tab='dashboard')

@app.route('/budget/<int:budget_id>/future-expenses')
@login_required
def future_expenses(budget_id):
    budget = Budget.query.get_or_404(budget_id)
    future_categories = Category.query.filter_by(budget_id=budget_id, is_future_expense=True).all()

    for category in future_categories:
        # Calculate how much has been saved
        transactions = Transaction.query.filter_by(category_id=category.id).all()
        saved_amount = sum(t.amount for t in transactions)

        # Calculate remaining amount needed
        category.remaining = category.target_amount - saved_amount

        # Calculate recommended monthly savings
        today = date.today()
        days_remaining = (category.target_date - today).days if category.target_date > today else 1
        months_remaining = max(1, days_remaining // 30)
        category.monthly_recommendation = category.remaining / months_remaining

    return render_template('future_expenses.html', budget=budget, future_categories=future_categories, active_tab='future_expenses')

@app.route('/budget/<int:budget_id>/add-category', methods=['GET', 'POST'])
@login_required
def add_category(budget_id):
    budget = Budget.query.get_or_404(budget_id)

    if request.method == 'POST':
        name = request.form.get('name')
        budgeted_amount = float(request.form.get('budgeted_amount') or 0)
        is_future_expense = 'is_future_expense' in request.form
        is_transfer = 'is_transfer' in request.form

        new_category = Category(
            name=name,
            budget_id=budget_id,
            budgeted_amount=budgeted_amount,
            is_future_expense=is_future_expense,
            is_transfer=is_transfer
        )

        if is_future_expense:
            target_date_str = request.form.get('target_date')
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
            target_amount = float(request.form.get('target_amount') or 0)

            new_category.target_date = target_date
            new_category.target_amount = target_amount

        db.session.add(new_category)
        db.session.commit()

        return redirect(url_for('view_budget', budget_id=budget_id))

    return render_template('add_category.html', budget=budget)

@app.route('/budget/<int:budget_id>/add-transaction', methods=['GET', 'POST'])
@login_required
def add_transaction(budget_id):
    budget = Budget.query.get_or_404(budget_id)
    categories = Category.query.filter_by(budget_id=budget_id).all()
    budgets = Budget.query.all()

    if request.method == 'POST':
        description = request.form.get('description')
        amount = float(request.form.get('amount') or 0)
        date_str = request.form.get('date')
        transaction_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        category_id = request.form.get('category_id')
        is_income = 'is_income' in request.form
        is_transfer = 'is_transfer' in request.form

        new_transaction = Transaction(
            description=description,
            amount=amount,
            date=transaction_date,
            budget_id=budget_id,
            category_id=category_id if category_id and category_id != "" else None,
            is_income=is_income,
            is_transfer=is_transfer
        )

        # Update budget balance
        if is_income:
            budget.balance += amount
        else:
            budget.balance -= amount

        if is_transfer:
            transfer_to_budget_id = request.form.get('transfer_to_budget_id')
            if transfer_to_budget_id:
                new_transaction.transfer_to_budget_id = transfer_to_budget_id

                # Create a corresponding income transaction in the target budget
                target_budget = Budget.query.get(transfer_to_budget_id)
                if target_budget:
                    target_budget.balance += amount

                    transfer_transaction = Transaction(
                        description=f"Transfer from {budget.name}",
                        amount=amount,
                        date=transaction_date,
                        budget_id=int(transfer_to_budget_id),
                        is_income=True
                    )
                    db.session.add(transfer_transaction)

        db.session.add(new_transaction)
        db.session.commit()

        return redirect(url_for('transactions', budget_id=budget_id))

    return render_template('add_transaction.html', budget=budget, categories=categories, budgets=budgets)

@app.route('/budget/<int:budget_id>/calculate-future-expense', methods=['POST'])
@login_required
def calculate_future_expense(budget_id):
    target_amount = float(request.form.get('target_amount') or 0)
    target_date_str = request.form.get('target_date')
    target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()

    # Calculate number of paydays until target date
    # Assuming monthly paydays for simplicity
    today = date.today()
    months_diff = (target_date.year - today.year) * 12 + (target_date.month - today.month)
    paydays = max(1, months_diff)

    # Calculate suggestion
    suggestion = target_amount / paydays

    return jsonify({
        'suggestion': round(suggestion, 2),
        'paydays': paydays
    })

@app.route('/transaction/<int:transaction_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    budget = Budget.query.get_or_404(transaction.budget_id)
    categories = Category.query.filter_by(budget_id=budget.id).all()
    budgets = Budget.query.all()

    if request.method == 'POST':
        # Store old values for balance calculations
        old_amount = transaction.amount
        old_is_income = transaction.is_income
        old_is_transfer = transaction.is_transfer
        old_transfer_to_budget_id = transaction.transfer_to_budget_id

        # Update transaction with new values
        transaction.description = request.form.get('description')
        new_amount = float(request.form.get('amount') or 0)
        transaction.amount = new_amount
        date_str = request.form.get('date')
        transaction.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        transaction.category_id = request.form.get('category_id') if request.form.get('category_id') and request.form.get('category_id') != "" else None
        transaction.is_income = 'is_income' in request.form
        transaction.is_transfer = 'is_transfer' in request.form

        # Update budget balance
        # First, revert the old transaction's effect
        if old_is_income:
            budget.balance -= old_amount
        else:
            budget.balance += old_amount

        # Then, apply the new transaction's effect
        if transaction.is_income:
            budget.balance += new_amount
        else:
            budget.balance -= new_amount

        # Handle transfers
        if old_is_transfer and old_transfer_to_budget_id:
            # Find and delete the old corresponding transaction
            old_target_transaction = Transaction.query.filter_by(
                budget_id=old_transfer_to_budget_id,
                description=f"Transfer from {budget.name}",
                amount=old_amount,
                is_income=True
            ).first()

            if old_target_transaction:
                old_target_budget = Budget.query.get(old_transfer_to_budget_id)
                if old_target_budget:
                    old_target_budget.balance -= old_amount
                db.session.delete(old_target_transaction)

        if transaction.is_transfer:
            transfer_to_budget_id = request.form.get('transfer_to_budget_id')
            transaction.transfer_to_budget_id = transfer_to_budget_id if transfer_to_budget_id else None

            if transfer_to_budget_id:
                target_budget = Budget.query.get(transfer_to_budget_id)
                if target_budget:
                    target_budget.balance += new_amount

                    # Create a new corresponding transaction in the target budget
                    transfer_transaction = Transaction(
                        description=f"Transfer from {budget.name}",
                        amount=new_amount,
                        date=transaction.date,
                        budget_id=int(transfer_to_budget_id),
                        is_income=True
                    )
                    db.session.add(transfer_transaction)
        else:
            transaction.transfer_to_budget_id = None

        db.session.commit()
        flash('Transaction updated successfully!')
        return redirect(url_for('transactions', budget_id=budget.id))

    return render_template('edit_transaction.html', transaction=transaction, budget=budget, categories=categories, budgets=budgets)

@app.route('/transaction/<int:transaction_id>/delete', methods=['POST'])
@login_required
def delete_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    budget_id = transaction.budget_id
    budget = Budget.query.get_or_404(budget_id)

    # Update budget balance
    if transaction.is_income:
        budget.balance -= transaction.amount
    else:
        budget.balance += transaction.amount

    # Handle transfer transaction deletion
    if transaction.is_transfer and transaction.transfer_to_budget_id:
        # Find and delete the corresponding transaction in the target budget
        target_transaction = Transaction.query.filter_by(
            budget_id=transaction.transfer_to_budget_id,
            description=f"Transfer from {budget.name}",
            amount=transaction.amount,
            is_income=True
        ).first()

        if target_transaction:
            target_budget = Budget.query.get(transaction.transfer_to_budget_id)
            if target_budget:
                target_budget.balance -= transaction.amount
            db.session.delete(target_transaction)

    db.session.delete(transaction)
    db.session.commit()
    flash('Transaction deleted successfully!')

    return redirect(url_for('transactions', budget_id=budget_id))

@app.route('/category/<int:category_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    budget = Budget.query.get_or_404(category.budget_id)

    if request.method == 'POST':
        category.name = request.form.get('name')
        category.budgeted_amount = float(request.form.get('budgeted_amount') or 0)
        category.is_future_expense = 'is_future_expense' in request.form
        category.is_transfer = 'is_transfer' in request.form

        if category.is_future_expense:
            target_date_str = request.form.get('target_date')
            if target_date_str:
                category.target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
            category.target_amount = float(request.form.get('target_amount') or 0)
        else:
            category.target_date = None
            category.target_amount = None

        db.session.commit()
        flash('Category updated successfully!')
        return redirect(url_for('view_budget', budget_id=budget.id))

    return render_template('edit_category.html', category=category, budget=budget)

@app.route('/category/<int:category_id>/delete', methods=['POST'])
@login_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    budget_id = category.budget_id

    # Check if there are transactions associated with this category
    transactions = Transaction.query.filter_by(category_id=category_id).all()
    if transactions:
        # Update transactions to have no category
        for transaction in transactions:
            transaction.category_id = None

    db.session.delete(category)
    db.session.commit()
    flash('Category deleted successfully!')

    return redirect(url_for('view_budget', budget_id=budget_id))

@app.route('/budget/<int:budget_id>/categories')
@login_required
def categories(budget_id):
    budget = Budget.query.get_or_404(budget_id)
    categories = Category.query.filter_by(budget_id=budget_id).all()

    # Calculate available amount for each category
    for category in categories:
        # Get all transactions for this category
        category_transactions = Transaction.query.filter_by(category_id=category.id).all()
        # Sum of all expenses for this category
        total_spent = sum(t.amount for t in category_transactions if not t.is_income)
        # Calculate available amount
        category.available = category.budgeted_amount - total_spent

    # Create spending summary with percentage calculations
    spending_summary = []
    for category in categories:
        if not category.is_future_expense:  # Only include regular categories in summary
            spent = category.budgeted_amount - category.available
            remaining = category.available
            # Calculate percentage of budget used
            percentage = (spent / category.budgeted_amount * 100) if category.budgeted_amount > 0 else 0

            spending_summary.append({
                'name': category.name,
                'budgeted_amount': category.budgeted_amount,
                'spent': spent,
                'remaining': remaining,
                'percentage': percentage
            })

    return render_template('categories.html',
                           budget=budget,
                           categories=categories,
                           spending_summary=spending_summary,
                           active_tab='categories')

@app.route('/budget/<int:budget_id>/transactions')
@login_required
def transactions(budget_id):
    budget = Budget.query.get_or_404(budget_id)
    transactions = Transaction.query.filter_by(budget_id=budget_id).order_by(Transaction.date.desc()).all()

    return render_template('transactions.html', budget=budget, transactions=transactions, active_tab='transactions')

# Run the app
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=6969, debug=True)