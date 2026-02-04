from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "rsvp.db"

app = Flask(__name__, static_folder="public", static_url_path="")


def now() -> str:
    return datetime.utcnow().isoformat()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','admin'))
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'pending_approval',
                paid INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS invitees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invitee_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                responded_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(invitee_id) REFERENCES invitees(id)
            );
            """
        )
        admin = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
        if not admin:
            conn.execute(
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, 'admin')",
                ("Admin", "admin@example.com", "admin123"),
            )
            conn.commit()


def require_auth(role: str | None = None):
    def decorator(func):
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            token = header.replace("Bearer ", "").strip()
            if not token:
                return jsonify(error="Missing token"), 401
            with get_db() as conn:
                session = conn.execute(
                    "SELECT token, user_id, role FROM sessions WHERE token = ?",
                    (token,),
                ).fetchone()
            if not session:
                return jsonify(error="Invalid token"), 401
            if role and session["role"] != role:
                return jsonify(error="Forbidden"), 403
            request.session = session  # type: ignore[attr-defined]
            return func(*args, **kwargs)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator


@app.route("/api/signup", methods=["POST"])
def signup():
    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    email = payload.get("email")
    password = payload.get("password")
    if not name or not email or not password:
        return jsonify(error="Missing fields"), 400
    try:
        with get_db() as conn:
            result = conn.execute(
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, 'user')",
                (name, email, password),
            )
            conn.commit()
        return jsonify(id=result.lastrowid), 201
    except sqlite3.IntegrityError:
        return jsonify(error="Email already in use"), 409


@app.route("/api/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    email = payload.get("email")
    password = payload.get("password")
    role = payload.get("role")
    if not email or not password or not role:
        return jsonify(error="Missing fields"), 400
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, name, role FROM users WHERE email = ? AND password = ?",
            (email, password),
        ).fetchone()
    if not user or user["role"] != role:
        return jsonify(error="Invalid credentials"), 401
    token = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (token, user["id"], user["role"], now()),
        )
        conn.commit()
    return jsonify(token=token, name=user["name"], role=user["role"])


@app.route("/api/events", methods=["POST"])
@require_auth("user")
def create_event():
    payload = request.get_json(silent=True) or {}
    title = payload.get("title")
    event_date = payload.get("eventDate")
    notes = payload.get("notes") or ""
    invitees = payload.get("invitees") or []
    if not title or not event_date or not isinstance(invitees, list) or not invitees:
        return jsonify(error="Missing fields"), 400

    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO events (user_id, title, event_date, notes, created_at) VALUES (?, ?, ?, ?, ?)",
            (request.session["user_id"], title, event_date, notes, now()),  # type: ignore[index]
        )
        event_id = cursor.lastrowid
        for invitee in invitees:
            name = invitee.get("name") if isinstance(invitee, dict) else None
            phone = invitee.get("phone") if isinstance(invitee, dict) else None
            if name and phone:
                conn.execute(
                    "INSERT INTO invitees (event_id, name, phone) VALUES (?, ?, ?)",
                    (event_id, name, phone),
                )
        conn.commit()
    return jsonify(id=event_id), 201


@app.route("/api/events/mine", methods=["GET"])
@require_auth("user")
def list_events():
    with get_db() as conn:
        events = conn.execute(
            "SELECT id, title, event_date as eventDate, notes, status, paid "
            "FROM events WHERE user_id = ? ORDER BY created_at DESC",
            (request.session["user_id"],),  # type: ignore[index]
        ).fetchall()
    return jsonify(events=[dict(event) for event in events])


@app.route("/api/events/<int:event_id>/pay", methods=["POST"])
@require_auth("user")
def mark_paid(event_id: int):
    with get_db() as conn:
        event = conn.execute(
            "SELECT id FROM events WHERE id = ? AND user_id = ?",
            (event_id, request.session["user_id"]),  # type: ignore[index]
        ).fetchone()
        if not event:
            return jsonify(error="Event not found"), 404
        conn.execute("UPDATE events SET paid = 1 WHERE id = ?", (event_id,))
        conn.commit()
    return jsonify(status="paid")


@app.route("/api/admin/events", methods=["GET"])
@require_auth("admin")
def list_pending_events():
    with get_db() as conn:
        events = conn.execute(
            "SELECT events.id, events.title, events.event_date as eventDate, events.notes, "
            "events.status, events.paid, users.name as requester "
            "FROM events JOIN users ON events.user_id = users.id "
            "WHERE events.status = 'pending_approval' ORDER BY events.created_at DESC"
        ).fetchall()
    return jsonify(events=[dict(event) for event in events])


@app.route("/api/admin/events/<int:event_id>/decision", methods=["POST"])
@require_auth("admin")
def decide_event(event_id: int):
    payload = request.get_json(silent=True) or {}
    decision = payload.get("decision")
    if decision not in {"approved", "rejected"}:
        return jsonify(error="Invalid decision"), 400

    with get_db() as conn:
        event = conn.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            return jsonify(error="Event not found"), 404
        conn.execute("UPDATE events SET status = ? WHERE id = ?", (decision, event_id))

        if decision == "approved":
            invitees = conn.execute(
                "SELECT id, name, phone FROM invitees WHERE event_id = ?",
                (event_id,),
            ).fetchall()
            for invitee in invitees:
                conn.execute(
                    "INSERT INTO invites (invitee_id, status, created_at) VALUES (?, 'pending', ?)",
                    (invitee["id"], now()),
                )
                print(
                    f"WhatsApp invite sent to {invitee['name']} ({invitee['phone']}) "
                    f"for event {event_id}."
                )
        conn.commit()
    return jsonify(status=decision)


@app.route("/api/admin/events/<int:event_id>/invites", methods=["GET"])
@require_auth("admin")
def list_invites(event_id: int):
    with get_db() as conn:
        invites = conn.execute(
            "SELECT invites.id, invitees.name, invitees.phone, invites.status, "
            "invites.responded_at as respondedAt "
            "FROM invites JOIN invitees ON invites.invitee_id = invitees.id "
            "WHERE invitees.event_id = ? ORDER BY invites.created_at DESC",
            (event_id,),
        ).fetchall()
    return jsonify(invites=[dict(invite) for invite in invites])


@app.route("/api/invites/<int:invite_id>", methods=["GET"])
def get_invite(invite_id: int):
    with get_db() as conn:
        invite = conn.execute(
            "SELECT invites.id, invites.status, invitees.name, invitees.phone, "
            "events.title, events.event_date as eventDate "
            "FROM invites JOIN invitees ON invites.invitee_id = invitees.id "
            "JOIN events ON invitees.event_id = events.id WHERE invites.id = ?",
            (invite_id,),
        ).fetchone()
    if not invite:
        return jsonify(error="Invite not found"), 404
    return jsonify(invite=dict(invite))


@app.route("/api/invites/<int:invite_id>/respond", methods=["POST"])
def respond_invite(invite_id: int):
    payload = request.get_json(silent=True) or {}
    response = payload.get("response")
    if response not in {"approved", "rejected", "maybe"}:
        return jsonify(error="Invalid response"), 400

    with get_db() as conn:
        invite = conn.execute(
            "SELECT id FROM invites WHERE id = ?",
            (invite_id,),
        ).fetchone()
        if not invite:
            return jsonify(error="Invite not found"), 404
        conn.execute(
            "UPDATE invites SET status = ?, responded_at = ? WHERE id = ?",
            (response, now(), invite_id),
        )
        conn.commit()
    return jsonify(status=response)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "user-login.html")


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=3000, debug=True)
