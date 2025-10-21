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

    # Ensure a CSRF token exists for admin actions
    import secrets as _secrets
    csrf_token = session.get("csrf_token")
    if not csrf_token:
        csrf_token = _secrets.token_urlsafe(32)
        session["csrf_token"] = csrf_token

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
        .chart-section { display:grid; grid-template-columns: 1fr 280px; gap:16px; align-items:start; margin-top:8px; }
        .chart-container { height:420px; }
        .chart-controls { display:flex; flex-direction:column; }
        .chart-controls select { min-width:260px; padding:6px; border:1px solid #d1d5db; border-radius:8px; background:#fff; }
        .band-toggle { font-size:13px; color:#374151; display:flex; align-items:center; gap:6px; margin-top:8px; }
        @media (max-width: 768px) {
          body { margin:16px; }
          .chart-section { grid-template-columns: 1fr; }
          .chart-container { order:1; height:320px; }
          .chart-controls { order:2; width:100%; }
          .chart-controls select { min-width:0; width:100%; height:auto; }
          .band-toggle { align-items:flex-start; }
        }
      </style>
      <script src=\"https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js\"></script>
      <script src=\"https://cdn.jsdelivr.net/npm/date-fns@2.30.0/dist/date-fns.min.js\"></script>
      <script src=\"https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3\"></script>
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
      <div style=\"border:1px solid #e5e7eb; border-radius:12px; padding:12px 16px; margin: 16px 0; background:#fff;\">
        <div>
          <h3 style=\"margin:6px 0 6px;\">Posterior Evolution (weekly)</h3>
          <div style=\"color:#6b7280; font-size: 13px;\">Solid line: posterior mean. Shaded band: 5%–95% credible interval.</div>
        </div>
        <div class=\"chart-section\">
          <div class=\"chart-container\">
            <canvas id=\"mabChart\"></canvas>
          </div>
          <div class=\"chart-controls\">
            <label for=\"restaurantSelect\" style=\"font-size:12px; color:#6b7280; margin-bottom:4px;\">Restaurants (total votes)</label>
            <select id=\"restaurantSelect\" multiple size=\"10\" style=\"height:100%;\"></select>
            <div style=\"margin-top:6px; font-size:12px; color:#6b7280;\">Tip: select up to 12 restaurants.</div>
            <label class=\"band-toggle\">
              <input id=\"toggleBands\" type=\"checkbox\" checked />
              <span>Show credible bands</span>
            </label>
          </div>
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
      (async function renderMabChart() {
        try {
          const resp = await fetch("{{ url_for('admin.mab_history_json') }}");
          const payload = await resp.json();
          const series = payload.series || [];
          const names = (payload.names || []).slice(); // all names available
          const defaultNames = (payload.default || names.slice(0,10)).slice();
          if (!series.length || !names.length) return;

          const labels = series.map(p => p.week);

          const colors = [
            '#2563eb', '#059669', '#f59e0b', '#ef4444', '#8b5cf6', '#10b981', '#f97316', '#22c55e', '#e11d48', '#14b8a6',
            '#6366f1', '#84cc16', '#dc2626', '#a855f7', '#0ea5e9', '#d97706', '#16a34a'
          ];
          const rgba = (hex, alpha=0.10) => {
            const m = hex.replace('#','');
            const r = parseInt(m.substring(0,2),16), g=parseInt(m.substring(2,4),16), b=parseInt(m.substring(4,6),16);
            return `rgba(${r}, ${g}, ${b}, ${alpha})`;
          };

          // Populate restaurant select with totals (all names, sorted by total desc)
          const select = document.getElementById('restaurantSelect');
          const totals = payload.totals || {};
          const sortedNames = [...names].sort((a,b) => (totals[b]||0) - (totals[a]||0));
          if (select) {
            sortedNames.forEach(nm => {
              const opt = document.createElement('option');
              opt.value = nm;
              opt.textContent = `${nm} (${totals[nm] ?? 0})`;
              opt.selected = defaultNames.includes(nm);
              select.appendChild(opt);
            });
          }

          const hashColorIdx = (s) => {
            let h = 0; for (let i=0;i<s.length;i++) { h = (h*31 + s.charCodeAt(i))|0; }
            return Math.abs(h) % colors.length;
          };

          const buildDatasets = (selNames) => {
            const ds = [];
            selNames.forEach((nm) => {
              const color = colors[hashColorIdx(nm)];
              const mean = series.map(p => (p[`${nm}_mean`] ?? null));
              const lo = series.map(p => (p[`${nm}_lo`] ?? null));
              const hi = series.map(p => {
                const l = p[`${nm}_lo`];
                const b = p[`${nm}_band`];
                if (l == null || b == null) return null;
                return l + b;
              });
              ds.push({
                label: `${nm} 5%`,
                data: lo,
                borderColor: 'rgba(0,0,0,0)',
                backgroundColor: 'rgba(0,0,0,0)',
                pointRadius: 0,
                borderWidth: 0,
                spanGaps: true,
                yAxisID: 'y',
                isBand: true,
              });
              ds.push({
                label: `${nm} 95%`,
                data: hi,
                borderColor: 'rgba(0,0,0,0)',
                backgroundColor: rgba(color, 0.10),
                fill: '-1',
                pointRadius: 0,
                borderWidth: 0,
                spanGaps: true,
                yAxisID: 'y',
                isBand: true,
              });
              ds.push({
                label: `${nm} mean`,
                data: mean,
                borderColor: color,
                backgroundColor: color,
                fill: false,
                pointRadius: 0,
                borderWidth: 2,
                spanGaps: true,
                yAxisID: 'y',
              });
            });
            return ds;
          };

          const ctx = document.getElementById('mabChart').getContext('2d');
          let selectedNames = defaultNames;
          const chart = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets: buildDatasets(selectedNames) },
            options: {
              responsive: true,
              interaction: { mode: 'index', intersect: false },
              stacked: false,
              plugins: {
                legend: { display: false },
                tooltip: { enabled: true }
              },
              scales: {
                x: {
                  type: 'time',
                  time: { unit: 'week', tooltipFormat: 'PP' },
                  ticks: { maxRotation: 0 },
                },
                y: {
                  beginAtZero: true,
                  suggestedMax: 1,
                  min: 0,
                  max: 1,
                  title: { display: true, text: 'p' }
                }
              }
            }
          });

          // Wire up toggle for credible bands
          const bandToggle = document.getElementById('toggleBands');
          const applyBandVisibility = () => {
            const show = bandToggle ? bandToggle.checked : true;
            chart.data.datasets.forEach(ds => {
              if (ds.isBand) ds.hidden = !show;
            });
            chart.update('none');
          };
          if (bandToggle) {
            bandToggle.addEventListener('change', applyBandVisibility);
            applyBandVisibility();
          }

          // Selection handling
          const cap = 12;
          let prevSelected = new Set(selectedNames);
          const getSelectedNames = () => {
            if (!select) return sortedNames;
            return Array.from(select.selectedOptions).map(o => o.value);
          };
          if (select) {
            select.addEventListener('change', () => {
              const current = getSelectedNames();
              if (current.length > cap) {
                // determine which option was added; revert it
                const added = current.find(v => !prevSelected.has(v));
                // if we can't find the added one, just trim extras
                const toDeselect = added || current[current.length - 1];
                Array.from(select.options).forEach(opt => {
                  if (opt.value === toDeselect) opt.selected = false;
                });
                return; // wait for next change event
              }
              selectedNames = current;
              prevSelected = new Set(selectedNames);
              chart.data.datasets = buildDatasets(selectedNames);
              applyBandVisibility();
            });
          }

          // Attach CSRF header to admin POSTs in this page
          const csrfToken = "{{ csrf_token }}";
          window.__adminFetch = (url, opts = {}) => {
            const headers = Object.assign({ 'X-CSRF-Token': csrfToken }, opts.headers || {});
            return fetch(url, Object.assign({}, opts, { headers }));
          };
        } catch (e) {
          console.error('Failed to render MAB chart', e);
        }
      })();

      async function toggle(name, btn, td) {
        btn.disabled = true;
        try {
          const resp = await window.__adminFetch("{{ url_for('admin.toggle_restaurant') }}", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ name })
          });
          const contentType = resp.headers.get("content-type") || "";
          let data = null;
          if (contentType.includes("application/json")) {
            data = await resp.json();
          } else {
            const text = (await resp.text()).trim();
            throw new Error(text || `Unexpected response (HTTP ${resp.status})`);
          }
          if (!resp.ok || !data?.ok) {
            const message = data?.error || `Toggle failed (HTTP ${resp.status})`;
            throw new Error(message);
          }
          btn.dataset.on = String(data.is_excluded);
          btn.textContent = data.is_excluded ? "Enable" : "Disable";
          td.textContent = data.is_excluded ? "1" : "0";
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
    return render_template_string(html, rows=rows, csrf_token=csrf_token)


@admin_bp.route("/toggle", methods=["POST"])
def toggle_restaurant():
    user = session.get("user") or {}
    email = user.get("email")
    if not is_admin(email):
        return jsonify({"ok": False, "error": "forbidden"}), 403
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


@admin_bp.route("/mab_history.json")
def mab_history_json():
    user = session.get("user") or {}
    email = user.get("email")
    if not is_admin(email):
        abort(403)
    try:
        from .mab_history import build_weekly_posteriors, build_chart_series
        import random
        rows = build_weekly_posteriors()

        # Build totals for ALL restaurants and compute default (top-10) list
        totals_map: dict[str, int] = {}
        all_names_sorted: list[str] = []
        default_top: list[str] = []
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                totals_rows = conn.execute(
                    "SELECT name, SUM(COALESCE(votes,0)) AS tot FROM weekly_results GROUP BY name"
                ).fetchall()
                totals_map = {r["name"]: int(r["tot"] or 0) for r in totals_rows}
                # All names sorted by totals desc, then name
                all_names_sorted = [r["name"] for r in sorted(totals_rows, key=lambda r: (-(int(r["tot"] or 0)), r["name"]))]
                # Default top-10 with random tie-breaking
                shuffled = list(totals_rows)
                random.shuffle(shuffled)
                shuffled.sort(key=lambda r: int(r["tot"] or 0), reverse=True)
                default_top = [r["name"] for r in shuffled[:10]]
        except Exception:
            # Fallback from computed rows if DB totals query fails
            all_names_sorted = sorted({r.name for r in rows})
            random.shuffle(all_names_sorted)
            default_top = all_names_sorted[:10]
            totals_map = {nm: 0 for nm in all_names_sorted}

        # Build series for ALL rows; client selects subset
        series = build_chart_series(rows)
        return jsonify({
            "series": series,
            "names": all_names_sorted,
            "default": default_top,
            "totals": totals_map,
        })
    except Exception as e:
        return jsonify({"series": [], "names": [], "error": str(e)}), 500
