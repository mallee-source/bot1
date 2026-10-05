"""
AI Brain + Customer Dashboard Server — this is YOUR server.

- Your real OpenRouter API key lives only here.
- Customers never get any Python file — they only get a LINK to log into.
- From the dashboard, a customer can: see their credits, add/remove their
  own OpenRouter key, and enter their own MT5 account details.
- Actual trading still runs on a Windows VPS (see vps_runner.py in the
  Hedge-Bot folder) — that VPS pulls each customer's MT5 credentials from
  here via the protected /admin/customers endpoint and trades on their
  behalf. The customer's PC/browser is never involved in execution.
"""

import hashlib
import secrets
import sqlite3

import requests
from flask import Flask, jsonify, redirect, request, session, render_template_string, url_for

# ── YOUR SECRETS — never share these, never put them in anything a customer gets
OPENROUTER_API_KEY = "your_openrouter_api_key"
ADMIN_SECRET = "change_this_to_a_long_random_admin_secret"  # used by vps_runner.py only

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openrouter/free"

SYSTEM_PROMPT = (
    "You are a Senior Portfolio Manager trading using the Smart Money Concept "
    "(SMC) methodology. You will receive 4H and 15M candle data plus SMC "
    "analysis (market structure, order blocks, fair value gaps, and "
    "liquidity levels) for both timeframes.\n\n"
    "Apply this strategy:\n"
    "1. Use the 4H market structure to determine the higher-timeframe bias "
    "(only trade in that direction).\n"
    "2. Use the 15M timeframe to find the entry: look for price reacting "
    "to an order block or filling a fair value gap in the direction of "
    "the 4H bias.\n"
    "3. Be cautious of liquidity levels — price often sweeps a recent "
    "swing high/low before reversing; do not chase a move straight into "
    "unswept liquidity.\n"
    "4. If the 4H and 15M do not align, or structure is unclear/ranging, "
    "prefer HOLD over a low-quality trade.\n\n"
    "You must reply with EXACTLY one word: BUY, SELL, or HOLD. No other text."
)

DB_PATH = "users.db"
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # sessions reset on every restart — fine for now


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            credits INTEGER NOT NULL DEFAULT 0,
            own_api_key TEXT,
            mt5_login TEXT,
            mt5_password TEXT,
            mt5_server TEXT,
            symbol TEXT DEFAULT 'XAUUSD',
            active INTEGER NOT NULL DEFAULT 1
        )"""
    )
    # Safe migration for databases created before these columns existed
    for col, decl in [
        ("own_api_key", "TEXT"),
        ("mt5_login", "TEXT"),
        ("mt5_password", "TEXT"),
        ("mt5_server", "TEXT"),
        ("symbol", "TEXT DEFAULT 'XAUUSD'"),
        ("active", "INTEGER NOT NULL DEFAULT 1"),
    ]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def check_auth(username, password):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row is None or row["password_hash"] != hash_password(password):
        return None
    return row


def deduct_credit(username):
    conn = get_db()
    conn.execute("UPDATE users SET credits = credits - 1 WHERE username = ?", (username,))
    conn.commit()
    conn.close()


def get_user(username):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row


# ───────────────────────── WEB DASHBOARD (for customers) ─────────────────────────

LOGIN_PAGE = """
<!doctype html><html><head><title>Login</title>
<style>body{font-family:sans-serif;max-width:400px;margin:80px auto;padding:0 20px}
input{width:100%;padding:10px;margin:6px 0;box-sizing:border-box}
button{width:100%;padding:10px;background:#16a34a;color:#fff;border:none;border-radius:6px;cursor:pointer}
.error{color:#dc2626}</style></head><body>
<h2>🤖 AI Hedge Fund — Login</h2>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post">
<input name="username" placeholder="Username" required>
<input name="password" type="password" placeholder="Password" required>
<button type="submit">Login</button>
</form></body></html>
"""

DASHBOARD_PAGE = """
<!doctype html><html><head><title>Dashboard</title>
<style>body{font-family:sans-serif;max-width:600px;margin:40px auto;padding:0 20px}
fieldset{margin:20px 0;padding:15px;border-radius:8px}
input{width:100%;padding:8px;margin:5px 0;box-sizing:border-box}
button{padding:10px 16px;background:#16a34a;color:#fff;border:none;border-radius:6px;cursor:pointer}
.msg{background:#dcfce7;padding:10px;border-radius:6px}
.logout{float:right}</style></head><body>
<a class="logout" href="/logout">Logout</a>
<h2>🤖 Welcome, {{ user.username }}</h2>
{% if msg %}<p class="msg">{{ msg }}</p>{% endif %}

<fieldset>
<legend><b>Credits</b></legend>
{% if user.own_api_key %}
  <p>✅ Using your own OpenRouter API key — unlimited, shared credits not used.</p>
{% else %}
  <p>Shared credits remaining: <b>{{ user.credits }}</b></p>
{% endif %}
</fieldset>

<fieldset>
<legend><b>AI Mode</b></legend>
<form method="post" action="/dashboard/api_key">
<label>Your own OpenRouter API key (leave blank to use shared credits):</label>
<input name="api_key" placeholder="sk-or-v1-..." value="{{ user.own_api_key or '' }}">
<button type="submit">Save</button>
</form>
</fieldset>

<fieldset>
<legend><b>MT5 Account</b></legend>
<form method="post" action="/dashboard/mt5">
<label>MT5 Login</label>
<input name="mt5_login" value="{{ user.mt5_login or '' }}" required>
<label>MT5 Password</label>
<input name="mt5_password" type="password" placeholder="(unchanged if left blank)">
<label>MT5 Server</label>
<input name="mt5_server" value="{{ user.mt5_server or '' }}" required>
<label>Symbol to trade</label>
<input name="symbol" value="{{ user.symbol or 'XAUUSD' }}" required>
<button type="submit">Save MT5 Details</button>
</form>
</fieldset>

</body></html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = check_auth(request.form["username"], request.form["password"])
        if user is None:
            return render_template_string(LOGIN_PAGE, error="Invalid username or password.")
        session["username"] = user["username"]
        return redirect(url_for("dashboard"))
    return render_template_string(LOGIN_PAGE, error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def require_login():
    if "username" not in session:
        return None
    return get_user(session["username"])


@app.route("/dashboard")
def dashboard():
    user = require_login()
    if user is None:
        return redirect(url_for("login"))
    return render_template_string(DASHBOARD_PAGE, user=user, msg=request.args.get("msg"))


@app.route("/dashboard/api_key", methods=["POST"])
def dashboard_api_key():
    user = require_login()
    if user is None:
        return redirect(url_for("login"))
    api_key = request.form.get("api_key", "").strip()
    conn = get_db()
    conn.execute("UPDATE users SET own_api_key = ? WHERE username = ?", (api_key or None, user["username"]))
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard", msg="Saved."))


@app.route("/dashboard/mt5", methods=["POST"])
def dashboard_mt5():
    user = require_login()
    if user is None:
        return redirect(url_for("login"))
    mt5_login = request.form.get("mt5_login", "").strip()
    mt5_password = request.form.get("mt5_password", "").strip()
    mt5_server = request.form.get("mt5_server", "").strip()
    symbol = request.form.get("symbol", "XAUUSD").strip()

    conn = get_db()
    if mt5_password:
        conn.execute(
            "UPDATE users SET mt5_login=?, mt5_password=?, mt5_server=?, symbol=? WHERE username=?",
            (mt5_login, mt5_password, mt5_server, symbol, user["username"]),
        )
    else:
        conn.execute(
            "UPDATE users SET mt5_login=?, mt5_server=?, symbol=? WHERE username=?",
            (mt5_login, mt5_server, symbol, user["username"]),
        )
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard", msg="MT5 details saved."))


@app.route("/")
def home():
    return redirect(url_for("dashboard") if "username" in session else url_for("login"))


# ───────────────────────── AI DECISION API (called by your VPS runner) ─────────────────────────

@app.route("/decision", methods=["POST"])
def decision():
    auth = request.authorization
    if not auth:
        return jsonify({"error": "unauthorized"}), 401

    user = check_auth(auth.username, auth.password)
    if user is None:
        return jsonify({"error": "invalid credentials"}), 401

    using_own_key = bool(user["own_api_key"])

    if not using_own_key and user["credits"] <= 0:
        return jsonify({"error": "no_credits", "message": "Credits exhausted. Please top up, or add your own API key."}), 402

    market_data = request.json.get("market_data", "")
    if not market_data:
        return jsonify({"error": "market_data is required"}), 400

    key_to_use = user["own_api_key"] if using_own_key else OPENROUTER_API_KEY

    headers = {"Authorization": f"Bearer {key_to_use}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": market_data},
        ],
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        ai_text = response.json()["choices"][0]["message"]["content"].strip().upper()
        if ai_text not in ("BUY", "SELL", "HOLD"):
            ai_text = "HOLD"
    except Exception as e:
        return jsonify({"error": f"AI call failed: {e}"}), 502

    if using_own_key:
        return jsonify({"decision": ai_text, "credits_left": "unlimited (using your own API key)"})

    deduct_credit(user["username"])
    return jsonify({"decision": ai_text, "credits_left": user["credits"] - 1})


@app.route("/set_api_key", methods=["POST"])
def set_api_key():
    auth = request.authorization
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user = check_auth(auth.username, auth.password)
    if user is None:
        return jsonify({"error": "invalid credentials"}), 401

    api_key = (request.json or {}).get("api_key", "").strip()
    conn = get_db()
    conn.execute("UPDATE users SET own_api_key = ? WHERE username = ?", (api_key or None, user["username"]))
    conn.commit()
    conn.close()

    if api_key:
        return jsonify({"message": "Your own API key is now active."})
    return jsonify({"message": "Your own API key was removed."})


@app.route("/credits", methods=["GET"])
def credits():
    auth = request.authorization
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user = check_auth(auth.username, auth.password)
    if user is None:
        return jsonify({"error": "invalid credentials"}), 401
    return jsonify({"username": user["username"], "credits": user["credits"]})


# ───────────────────────── ADMIN API (called only by vps_runner.py, on YOUR VPS) ─────────────────────────

@app.route("/admin/decision", methods=["POST"])
def admin_decision():
    """Same as /decision, but authenticated with ADMIN_SECRET + a target
    username instead of that customer's password — used by vps_runner.py,
    which never has access to customers' plaintext passwords (only hashes
    are stored, by design)."""
    if request.headers.get("X-Admin-Secret") != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    body = request.json or {}
    username = body.get("username")
    market_data = body.get("market_data", "")

    user = get_user(username)
    if user is None:
        return jsonify({"error": "unknown username"}), 404
    if not market_data:
        return jsonify({"error": "market_data is required"}), 400

    using_own_key = bool(user["own_api_key"])

    if not using_own_key and user["credits"] <= 0:
        return jsonify({"error": "no_credits", "message": "Credits exhausted."}), 402

    key_to_use = user["own_api_key"] if using_own_key else OPENROUTER_API_KEY
    headers = {"Authorization": f"Bearer {key_to_use}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": market_data},
        ],
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        ai_text = response.json()["choices"][0]["message"]["content"].strip().upper()
        if ai_text not in ("BUY", "SELL", "HOLD"):
            ai_text = "HOLD"
    except Exception as e:
        return jsonify({"error": f"AI call failed: {e}"}), 502

    if using_own_key:
        return jsonify({"decision": ai_text, "credits_left": "unlimited (own API key)"})

    deduct_credit(user["username"])
    return jsonify({"decision": ai_text, "credits_left": user["credits"] - 1})


@app.route("/admin/customers", methods=["GET"])
def admin_customers():
    """Returns every active customer's trading credentials so your VPS runner
    can log into their MT5 account and trade on their behalf. Protected by
    ADMIN_SECRET — never expose this header/value to customers."""
    if request.headers.get("X-Admin-Secret") != ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    rows = conn.execute(
        "SELECT username, mt5_login, mt5_password, mt5_server, symbol, own_api_key "
        "FROM users WHERE active = 1 AND mt5_login IS NOT NULL"
    ).fetchall()
    conn.close()

    customers = [dict(row) for row in rows]
    return jsonify({"customers": customers})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
