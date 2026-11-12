import hmac
import os
import re
from functools import wraps

import mysql.connector
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("Set FLASK_SECRET_KEY before starting the application.")

CSRFProtect(app)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def db_connection():
    """Open a short-lived connection to the private RDS MySQL endpoint."""
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ.get("DB_NAME", "email_app"),
        connection_timeout=5,
    )


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/subscribe")
def subscribe():
    email = request.form.get("email", "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("index"))

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO subscribers (email) VALUES (%s)",
            (email,),
        )
        conn.commit()
        flash("Thanks! Your email has been saved.", "success")
    except mysql.connector.IntegrityError:
        flash("That email is already subscribed.", "info")
    except mysql.connector.Error:
        app.logger.exception("Database error while saving subscriber")
        flash("We couldn't save your email right now. Please try again later.", "error")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
    return redirect(url_for("index"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        supplied = request.form.get("password", "")
        expected = os.environ.get("ADMIN_PASSWORD", "")
        if expected and hmac.compare_digest(supplied, expected):
            session.clear()
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        flash("Incorrect admin password.", "error")
    return render_template("login.html")


@app.get("/admin")
@admin_required
def admin():
    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, email, created_at FROM subscribers ORDER BY created_at DESC"
        )
        subscribers = cursor.fetchall()
        return render_template("admin.html", subscribers=subscribers)
    except mysql.connector.Error:
        app.logger.exception("Database error while listing subscribers")
        flash("Could not load subscribers. Check the database connection.", "error")
        return render_template("admin.html", subscribers=[])
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@app.post("/admin/delete/<int:subscriber_id>")
@admin_required
def delete_subscriber(subscriber_id):
    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM subscribers WHERE id = %s", (subscriber_id,))
        conn.commit()
        flash("Subscriber deleted.", "success")
    except mysql.connector.Error:
        app.logger.exception("Database error while deleting subscriber")
        flash("Could not delete that subscriber.", "error")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
    return redirect(url_for("admin"))


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    # For production, run with Gunicorn (see README.md), not Flask's dev server.
    app.run(host="127.0.0.1", port=5000, debug=False)
