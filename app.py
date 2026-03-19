from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
import openai
import os
import uuid
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
import logging
from functools import wraps
import re
from werkzeug.exceptions import BadRequest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limiting (simple in-memory for demo)
request_counts = {}

def rate_limit(max_requests=100, window_seconds=3600):
    """Simple rate limiting decorator"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            client_ip = request.remote_addr
            current_time = datetime.now().timestamp()

            if client_ip not in request_counts:
                request_counts[client_ip] = []

            # Clean old requests
            request_counts[client_ip] = [
                req_time for req_time in request_counts[client_ip]
                if current_time - req_time < window_seconds
            ]

            if len(request_counts[client_ip]) >= max_requests:
                return jsonify(error="Rate limit exceeded"), 429

            request_counts[client_ip].append(current_time)
            return f(*args, **kwargs)
        return wrapper
    return decorator

def validate_input(data, required_fields):
    """Validate required fields in request data"""
    for field in required_fields:
        if field not in data or not str(data[field]).strip():
            raise BadRequest(f"Missing required field: {field}")
    return True

def sanitize_string(text, max_length=500):
    """Sanitize and validate string input"""
    if not isinstance(text, str):
        raise BadRequest("Invalid input type")
    text = text.strip()
    if len(text) > max_length:
        raise BadRequest(f"Input too long (max {max_length} characters)")
    # Basic XSS prevention
    text = re.sub(r'<[^>]*>', '', text)
    return text
import logging
from functools import wraps

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
CORS(app, resources={
    r"/": {
        "origins": ["http://localhost:3000", "http://127.0.0.1:3000", "https://ai-finance-frontend.onrender.com", "*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})
bcrypt = Bcrypt(app)

# Initialize OpenAI client
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY not set in environment variables")
openai.api_key = openai_api_key

# Database setup
DB_FILE = "finance_assistant.db"

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                FOREIGN KEY(username) REFERENCES users(username)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(username) REFERENCES users(username)
            )
        """)
        conn.commit()

# Initialize database on startup
init_db()

# In-memory session cache for quick lookups
sessions = {}

def get_user_from_header():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.replace("Bearer ", "")
    
    # Check in-memory cache first
    if token in sessions:
        return sessions[token]
    
    # Check database
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username FROM sessions WHERE token = ? AND expires_at > ?",
            (token, datetime.now().isoformat())
        )
        row = cursor.fetchone()
        if row:
            username = row["username"]
            sessions[token] = username  # Cache it
            return username
    
    return None

@app.route("/")
def home():
    return "App is running"

@app.route("/health")
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Check database connection
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        logger.error(f"Database health check failed: {e}")

    return jsonify({
        "status": "healthy" if db_status == "healthy" else "unhealthy",
        "database": db_status,
        "timestamp": datetime.now().isoformat(),
        "uptime": "running"
    }), 200 if db_status == "healthy" else 503

@app.route("/signup", methods=["POST"])
@rate_limit(max_requests=5, window_seconds=3600)  # 5 signups per hour per IP
def signup():
    try:
        data = request.get_json()
        if not data:
            return jsonify(error="Invalid JSON"), 400

        username = data.get("username", "").strip()
        password = data.get("password", "").strip()

        # Validate input
        validate_input({"username": username, "password": password}, ["username", "password"])

        if len(username) < 3 or len(username) > 50:
            return jsonify(error="Username must be 3-50 characters"), 400

        if len(password) < 6:
            return jsonify(error="Password must be at least 6 characters"), 400

        # Check for valid characters
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return jsonify(error="Username can only contain letters, numbers, and underscores"), 400

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                return jsonify(error="User already exists"), 400

            # Hash password
            password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

            try:
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash)
                )
                conn.commit()
                logger.info(f"New user registered: {username}")
            except sqlite3.IntegrityError:
                return jsonify(error="User already exists"), 400

        # Create session token
        token = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(days=7)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)",
                (token, username, expires_at.isoformat())
            )
            conn.commit()

        sessions[token] = username  # Cache it
        return jsonify(message="Signup successful", token=token), 201

    except BadRequest as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        return jsonify(error="Internal server error"), 500

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify(error="Username and password are required"), 400

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        
        if not row or not bcrypt.check_password_hash(row["password_hash"], password):
            return jsonify(error="Invalid credentials"), 401

    # Create session token
    token = str(uuid.uuid4())
    expires_at = datetime.now() + timedelta(days=7)
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)",
            (token, username, expires_at.isoformat())
        )
        conn.commit()
    
    sessions[token] = username  # Cache it
    return jsonify(message="Login successful", token=token), 200

@app.route("/transactions", methods=["GET"])
def get_transactions():
    user = get_user_from_header()
    if not user:
        return jsonify(error="Unauthorized"), 401

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT date, amount, description FROM transactions WHERE username = ? ORDER BY date DESC",
            (user,)
        )
        rows = cursor.fetchall()
        transactions = [
            {"date": row["date"], "amount": row["amount"], "description": row["description"]}
            for row in rows
        ]
    
    return jsonify(transactions), 200

@app.route("/transactions", methods=["POST"])
def add_transaction():
    user = get_user_from_header()
    if not user:
        return jsonify(error="Unauthorized"), 401

    data = request.get_json()
    amount = data.get("amount")
    date = data.get("date")
    description = data.get("description", "")

    if not amount or not date:
        return jsonify(error="Amount and date are required"), 400

    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify(error="Invalid amount"), 400

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO transactions (username, amount, date, description) VALUES (?, ?, ?, ?)",
            (user, amount, date, description)
        )
        conn.commit()

    return jsonify(message="Transaction added successfully"), 201

@app.route("/insights", methods=["GET"])
def get_insights():
    user = get_user_from_header()
    if not user:
        return jsonify(error="Unauthorized"), 401

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT SUM(amount) as total FROM transactions WHERE username = ?",
            (user,)
        )
        result = cursor.fetchone()
        total_spending = result["total"] or 0
    
    # Generate insights based on spending
    insights = []
    if total_spending > 10000:
        insights.append("Your spending is quite high. Consider setting a budget.")
    elif total_spending > 5000:
        insights.append("Monitor your spending to stay on track.")
    else:
        insights.append("Great job keeping your spending under control!")
    
    return jsonify({
        "total_spending": total_spending,
        "prediction": insights[0]
    }), 200

@app.route("/logout", methods=["POST"])
def logout():
    user = get_user_from_header()
    if not user:
        return jsonify(error="Unauthorized"), 401

    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "")
    
    # Remove from cache
    if token in sessions:
        del sessions[token]
    
    # Keep in database for audit trail (don't delete, just rely on expiration)
    return jsonify(message="Logged out successfully"), 200

@app.route("/chat", methods=["POST"])
@rate_limit(max_requests=50, window_seconds=3600)  # 50 messages per hour per IP
def chat():
    user = get_user_from_header()
    if not user:
        return jsonify(error="Unauthorized"), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify(error="Invalid JSON"), 400

        message = data.get("message", "").strip()

        if not message:
            return jsonify(reply="Please enter a valid message"), 400

        # Sanitize input
        message = sanitize_string(message, max_length=1000)

        logger.info(f"Chat request from user: {user}")
        ai_reply = generate_response(message, user)
        return jsonify(reply=ai_reply), 200

    except BadRequest as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logger.error(f"Chat error for user {user}: {str(e)}")
        return jsonify(error="Error generating response", details=str(e)), 500

def generate_response(message, username):
    """Generate response using OpenAI API with financial context"""
    try:
        # Get user's recent transactions for context
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT amount, description FROM transactions WHERE username = ? ORDER BY date DESC LIMIT 5",
                (username,)
            )
            transactions = cursor.fetchall()
        
        transaction_context = ""
        if transactions:
            transaction_context = "\nRecent transactions:\n"
            for t in transactions:
                transaction_context += f"- ₦{t['amount']} ({t['description']})\n"
        
        system_prompt = f"""You are a friendly and helpful AI Finance Assistant. 
You help users manage their finances, budgets, and spending.
You provide practical advice on money management, budgeting, and financial planning.
Keep responses concise and actionable.
{transaction_context}"""
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            max_tokens=500,
            temperature=0.7
        )
        
        return response.choices[0].message.content
    except Exception as e:
        raise e

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)