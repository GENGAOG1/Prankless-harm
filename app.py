import os
import json
import uuid
import hmac
import secrets
import datetime
from threading import Lock
from flask import (
    Flask, request, render_template_string,
    redirect, url_for, session, jsonify
)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
LOG_FILE = os.environ.get("LOG_FILE", "/tmp/logs.json")
file_lock = Lock()
# --------------------------------------------------
# STORAGE
# --------------------------------------------------
def load_logs():
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
def save_logs(logs):
    os.makedirs(os.path.dirname(os.path.abspath(LOG_FILE)), exist_ok=True)
    temp_file = LOG_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)
    os.replace(temp_file, LOG_FILE)
# --------------------------------------------------
# AUTOMATIC CATEGORIES
# --------------------------------------------------
def categorize(data):
    if isinstance(data, dict):
        keys = {str(k).lower() for k in data.keys()}
        if "note" in keys or "notiz" in keys:
            return "Notizen"
        if "error" in keys or "exception" in keys:
            return "Fehler"
        if "event" in keys or "level" in keys:
            return "Technische Meldung"
        return "JSON / Strukturierte Daten"
    if isinstance(data, list):
        return "JSON / Strukturierte Daten"
    text = str(data).strip()
    if not text:
        return "Leer"
    if any(word in text.lower() for word in
           ["error:", "exception:", "traceback"]):
        return "Fehler"
    return "Text"
# --------------------------------------------------
# RECEIVE DATA
# --------------------------------------------------
def store_entry(data):
    entry = {
        "id": uuid.uuid4().hex,
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(timespec="seconds"),
        "category": categorize(data),
        "data": (
            json.dumps(data, ensure_ascii=False, indent=2)
            if isinstance(data, (dict, list))
            else str(data)
        )
    }
    with file_lock:
        logs = load_logs()
        logs.append(entry)
        save_logs(logs)
    return entry
@app.route("/")
def index():
    return """
    <h1>Notiz-Service</h1>
    <p>Zum Senden von Daten den POST-Endpunkt /collect verwenden.</p>
    """
@app.route("/collect", methods=["POST"])
def collect():
    if request.is_json:
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "Ungültiges JSON"}), 400
    elif request.form:
        data = request.form.to_dict()
    else:
        data = request.get_data(as_text=True)
    store_entry(data)
    return jsonify({"status": "ok"}), 200
@app.route("/api/log", methods=["POST"])
def api_log():
    raw = request.get_data(as_text=True)
    store_entry(raw)
    return jsonify({"status": "ok"}), 200
# --------------------------------------------------
# ADMIN LOGIN
# --------------------------------------------------
LOGIN_PAGE = """
<h2>Admin Login</h2>
<form method="post">
    <input type="password" name="password"
           placeholder="Passwort" required>
    <button type="submit">Anmelden</button>
</form>
{% if error %}<p>{{ error }}</p>{% endif %}
"""
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if ADMIN_PASSWORD and hmac.compare_digest(
            password, ADMIN_PASSWORD
        ):
            session.clear()
            session["admin"] = True
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin_dashboard"))
        return render_template_string(
            LOGIN_PAGE, error="Login fehlgeschlagen."
        )
    return render_template_string(LOGIN_PAGE, error=None)
@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))
# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------
DASHBOARD = """
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Log Manager</title>
<style>
body {
    background:#111; color:#eee; font-family:monospace;
    padding:20px; max-width:1000px; margin:auto;
}
.card {
    background:#1c1c1c; border:1px solid #444;
    border-radius:8px; padding:15px; margin:12px 0;
}
pre { white-space:pre-wrap; overflow-wrap:anywhere; }
a { color:#6cf; }
button, select {
    padding:8px; margin:4px; cursor:pointer;
}
.delete { background:#8b2222; color:white; border:0; }
.meta { color:#aaa; }
</style>
</head>
<body>
<h1>Log Manager ({{ entries|length }})</h1>
<p><a href="/admin/logout">Abmelden</a></p>
<form method="get">
    <label>Kategorie:
    <select name="category">
        <option value="">Alle</option>
        {% for c in categories %}
        <option value="{{ c }}"
        {% if selected == c %}selected{% endif %}>
        {{ c }}</option>
        {% endfor %}
    </select></label>
    <button type="submit">Filtern</button>
</form>
<form method="post" action="/admin/delete-all"
      onsubmit="return confirm('Wirklich alle Logs löschen?')">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <button class="delete" type="submit">
        Alle Logs löschen
    </button>
</form>
{% for e in entries|reverse %}
<div class="card">
    <h3>{{ e.category }}</h3>
    <div class="meta">{{ e.timestamp }} · ID: {{ e.id }}</div>
    <pre>{{ e.data }}</pre>
    <form method="post"
          action="/admin/delete/{{ e.id }}"
          onsubmit="return confirm('Diesen Eintrag löschen?')">
        <input type="hidden" name="csrf" value="{{ csrf }}">
        <button class="delete" type="submit">Eintrag löschen</button>
    </form>
</div>
{% else %}
<p>Keine Einträge in dieser Kategorie.</p>
{% endfor %}
</body>
</html>
"""
def require_admin():
    return session.get("admin") is True
def valid_csrf():
    supplied = request.form.get("csrf", "")
    expected = session.get("csrf", "")
    return bool(expected) and hmac.compare_digest(
        supplied, expected
    )
@app.route("/admin")
def admin_dashboard():
    if not require_admin():
        return redirect(url_for("admin_login"))
    with file_lock:
        logs = load_logs()
    categories = sorted({
        entry.get("category", "Sonstiges")
        for entry in logs
    })
    selected = request.args.get("category", "")
    entries = logs
    if selected in categories:
        entries = [
            e for e in logs
            if e.get("category") == selected
        ]
    return render_template_string(
        DASHBOARD,
        entries=entries,
        categories=categories,
        selected=selected,
        csrf=session["csrf"]
    )
# --------------------------------------------------
# DELETE LOGS - ADMIN ONLY
# --------------------------------------------------
@app.route("/admin/delete/<entry_id>", methods=["POST"])
def delete_entry(entry_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    if not valid_csrf():
        return "Ungültige Anfrage", 400
    with file_lock:
        logs = load_logs()
        logs = [e for e in logs if e.get("id") != entry_id]
        save_logs(logs)
    return redirect(url_for("admin_dashboard"))
@app.route("/admin/delete-all", methods=["POST"])
def delete_all():
    if not require_admin():
        return redirect(url_for("admin_login"))
    if not valid_csrf():
        return "Ungültige Anfrage", 400
    with file_lock:
        save_logs([])
    return redirect(url_for("admin_dashboard"))
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
