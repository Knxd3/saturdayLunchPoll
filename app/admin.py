"""
Admin routes: gated by email in admins table. Allows toggling restaurants.is_excluded
and reflects immediately in voting (UI disables via join; server blocks votes).
"""
from __future__ import annotations

import sqlite3
from flask import Blueprint, render_template_string, request, jsonify, session, abort, redirect, url_for
import os

DB_PATH = os.environ.get("DB_PATH", "database.db")


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def is_admin(email: str | None) -> bool:
    if not email:
        return False
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS admins (email TEXT PRIMARY KEY)")
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT 1 FROM admins WHERE email = ? LIMIT 1", (email,)).fetchone()
            return row is not None
    except Exception:
        return False


def ensure_restaurants_excluded_column(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(restaurants)")
    cols = [r[1] for r in cur.fetchall()]
    if "is_excluded" not in cols:
        # Add column; existing rows will be NULL, so queries must use COALESCE
        conn.execute("ALTER TABLE restaurants ADD COLUMN is_excluded INTEGER DEFAULT 0")
        conn.commit()


@admin_bp.route("/")
def admin_home():
    user = session.get("user") or {}
    email = user.get("email")
    if not is_admin(email):
        # If not logged in, push to login; else 403
        if not email:
            # set redirect back to admin
            session["post_login_redirect"] = "admin.admin_home"
            return redirect(url_for("login.login", next="admin.admin_home"))
        abort(403)
    # List restaurants with exclusion status
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                (
                    "SELECT name, cuisine, rating, reviews, COALESCE(is_excluded, 0) AS is_excluded "
                    "FROM restaurants ORDER BY name COLLATE NOCASE"
                )
            ).fetchall()
        except Exception:
            rows = []

    html = """
    <!doctype html>
    <html>
    <head>
      <meta charset=\"utf-8\" />
      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
      <title>Admin · Restaurants</title>
      <style>
        body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin:20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border-bottom: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; }
        th { background: #f9fafb; font-weight: 600; }
        .chip { padding:2px 8px; border:1px solid #e5e7eb; border-radius:999px; font-size:12px; color:#6b7280; background:#f3f4f6; }
        button.toggle { padding:6px 10px; border-radius:8px; border:1px solid #d1d5db; background:#fff; cursor:pointer; }
        button.toggle[data-on=\"1\"] { background:#fee2e2; border-color:#fecaca; color:#991b1b; }
        button.toggle[data-on=\"0\"] { background:#dcfce7; border-color:#bbf7d0; color:#065f46; }
      </style>
    </head>
    <body>
      <div style=\"display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;\">
        <h2 style=\"margin:0;\">Admin · Restaurants</h2>
        <div>
          <a href=\"{{ url_for('poll.show_poll') }}\">Back to poll</a>
          <span style=\"margin:0 8px; color:#9ca3af;\">|</span>
          <a href=\"{{ url_for('login.logout') }}\">Logout</a>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Cuisine</th>
            <th>Rating</th>
            <th>Reviews</th>
            <th>Excluded?</th>
            <th>Toggle</th>
          </tr>
        </thead>
        <tbody>
        {% for r in rows %}
          <tr data-name=\"{{ r['name'] }}\">
            <td>{{ r['name'] }}</td>
            <td>{{ r['cuisine'] or '' }}</td>
            <td>{{ r['rating'] or '' }}</td>
            <td><span class=\"chip\">{{ r['reviews'] or 0 }}</span></td>
            <td class=\"excluded\">{{ 1 if r['is_excluded'] else 0 }}</td>
            <td>
              <button class=\"toggle\" data-on=\"{{ 1 if r['is_excluded'] else 0 }}\">{{ 'Enable' if r['is_excluded'] else 'Disable' }}</button>
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      <script>
      async function toggle(name, btn, td) {
        btn.disabled = true;
        try {
          const resp = await fetch("{{ url_for('admin.toggle_restaurant') }}", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ name })
          });
          const data = await resp.json();
          if (data && data.ok) {
            btn.dataset.on = String(data.is_excluded);
            btn.textContent = data.is_excluded ? "Enable" : "Disable";
            td.textContent = data.is_excluded ? "1" : "0";
          } else {
            alert("Toggle failed");
          }
        } catch (e) {
          alert("Error toggling: " + e);
        } finally {
          btn.disabled = false;
        }
      }
      document.querySelectorAll('button.toggle').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const tr = btn.closest('tr');
          const name = tr.getAttribute('data-name');
          const td = tr.querySelector('td.excluded');
          toggle(name, btn, td);
        });
      });
      </script>
    </body>
    </html>
    """
    return render_template_string(html, rows=rows)


@admin_bp.route("/toggle", methods=["POST"])
def toggle_restaurant():
    user = session.get("user") or {}
    email = user.get("email")
    if not is_admin(email):
        abort(403)
    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    if not name:
        return jsonify({"ok": False, "error": "missing name"}), 400
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        ensure_restaurants_excluded_column(conn)
        cur = conn.cursor()
        row = cur.execute("SELECT COALESCE(is_excluded,0) AS ex FROM restaurants WHERE name = ?", (name,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "not found"}), 404
        new_val = 0 if int(row["ex"] or 0) else 1
        cur.execute("UPDATE restaurants SET is_excluded = ? WHERE name = ?", (new_val, name))
        conn.commit()
    return jsonify({"ok": True, "is_excluded": int(new_val)})

