"""
Poll routes.
"""
import uuid
from flask import Blueprint, render_template_string, request, redirect, url_for, make_response
from .poll_manager import (
    ensure_weekly_selection,
    get_current_week_selection,
    record_vote,
    is_voting_open,
    get_voting_window,
    voter_already_voted,
    hash_ip,
)

poll_bp = Blueprint("poll", __name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Saturday Lunch Poll</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card: #111827;
      --muted: #9ca3af;
      --accent: #60a5fa;
      --accent-strong: #3b82f6;
      --text: #e5e7eb;
      --chip: #1f2937;
      --chip-border: #374151;
    }
    * { box-sizing: border-box; }
    body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; background: radial-gradient(1200px 600px at 20% -10%, #0f172a 10%, var(--bg) 60%); color: var(--text); }
    .wrap { max-width: 840px; margin: 0 auto; padding: 32px 16px 48px; }
    .title { text-align:center; margin-bottom: 18px; font-size: 28px; letter-spacing: 0.3px; }
    .subtitle { text-align:center; margin: 0 auto 28px; max-width: 700px; color: var(--muted); font-size: 14px; }
    .poll { background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.00)); border:1px solid #111827; box-shadow: 0 8px 32px rgba(0,0,0,0.25); border-radius: 16px; padding: 12px; }
    form { display:grid; grid-template-columns: 1fr; gap: 10px; }
    @media (min-width: 740px){ form { grid-template-columns: 1fr 1fr; } }
    .option { display:flex; gap:12px; padding:12px; border:1px solid var(--chip-border); background: var(--card); border-radius: 12px; align-items:flex-start; transition: border-color .15s ease, transform .05s ease; cursor: pointer; }
    .option:hover { border-color: var(--accent); }
    .option:active { transform: translateY(1px); }
    .option input { margin-top: 4px; accent-color: var(--accent-strong); }
    .meta { display:flex; flex-wrap: wrap; gap:6px; margin-top:6px; }
    .chip { border:1px solid var(--chip-border); background: var(--chip); color: var(--muted); padding: 2px 8px; border-radius: 999px; font-size: 12px; }
    .name { font-weight: 700; letter-spacing:.2px; }
    .info { color: var(--muted); font-size: 12px; margin-top: 6px; display:flex; flex-wrap:wrap; gap:10px; }
    .toprow { display:flex; align-items:center; gap:10px; }
    .votes { margin-left:auto; background: #111827; border:1px solid var(--chip-border); padding:4px 10px; border-radius: 999px; font-size: 12px; color:#f9fafb; }
    .vote { margin-top: 14px; display:flex; justify-content:center; }
    .vote button { background: var(--accent-strong); color: #fff; border:none; padding: 10px 16px; border-radius: 10px; font-weight: 600; cursor: pointer; }
    a.link { color: var(--accent); text-decoration: none; }
    a.link:hover { text-decoration: underline; }
  </style>
  </head>
  <body>
    <div class="wrap">
      <div class="title">Where should we go for lunch?</div>
      <div class="subtitle">Vote for this week's pick. Options refresh every Monday at 10:00. Voting closes Wednesday 23:00.</div>
      {% if already_voted %}
        <div style="padding:10px 12px; color:#fbbf24;">Looks like you already voted this week.</div>
      {% endif %}
      <div class="poll">
        {% if not voting_open %}
          <div style="padding:10px 12px; color:#fca5a5;">Voting is closed for this week.</div>
        {% endif %}
        <form method="POST" action="{{ url_for('poll.vote') }}">
          {% for opt in options %}
            <label class="option">
              <input type="checkbox" name="option_ids" value="{{ opt['id'] }}" {% if not can_vote %}disabled{% endif %}>
              <div>
                <div class="toprow"><div class="name">{{ opt['name'] }}</div><span class="votes">{{ opt['votes'] }} votes</span></div>
                <div class="info">
                  {% if opt.get('average_price') %}<span>Avg: {{ opt['average_price'] }}</span>{% endif %}
                  {% if opt.get('address') %}<span>Loc: {{ opt['address'] }}</span>{% endif %}
                  {% if opt.get('cuisine') %}<span>Cuisine: {{ opt['cuisine'] }}</span>{% endif %}
                </div>
                <div class="meta">
                  {% if opt.get('cuisine') %}<span class="chip">{{ opt['cuisine'] }}</span>{% endif %}
                  {% if opt.get('rating') %}<span class="chip">Rating: {{ opt['rating'] }}</span>{% endif %}
                  {% if opt.get('reviews') %}<span class="chip">{{ opt['reviews'] }}</span>{% endif %}
                  {% if opt.get('average_price') %}<span class="chip">{{ opt['average_price'] }}</span>{% endif %}
                  {% if opt.get('offer') %}<span class="chip">Deal: {{ opt['offer'] }}</span>{% endif %}
                  {% if opt.get('url') %}<span class="chip"><a target="_blank" class="link" href="{{ opt['url'] }}">View</a></span>{% endif %}
                </div>
              </div>
            </label>
          {% endfor %}
          <div class="vote" style="width:100%; display:inline"><button type="submit" {% if not can_vote %}disabled style="opacity:.6; cursor:not-allowed;"{% endif %}>Submit Votes</button></div>
        </form>
      </div>
    </div>
  </body>
  </html>
"""

@poll_bp.route("/")
def show_poll():
    # Ensure current week's selection exists and is up-to-date
    ensure_weekly_selection()
    options = get_current_week_selection()
    # derive identity and vote eligibility
    voter_id = request.cookies.get("voter_id")
    client_ip = request.headers.get("Fly-Client-IP") or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr)
    already = voter_already_voted(voter_id, hash_ip(client_ip)) if voter_id or client_ip else False
    voting_open = is_voting_open()
    can_vote = voting_open and not already
    return render_template_string(
        HTML_TEMPLATE,
        options=options,
        voting_open=voting_open,
        can_vote=can_vote,
        already_voted=already,
        voting_window=get_voting_window(),
    )


@poll_bp.route("/vote", methods=["POST"])
def vote():
    ensure_weekly_selection()
    option_ids = request.form.getlist("option_ids")
    # identify voter
    voter_id = request.cookies.get("voter_id") or uuid.uuid4().hex
    client_ip = request.headers.get("Fly-Client-IP") or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr)
    ip_h = hash_ip(client_ip)

    resp = make_response(redirect(url_for("poll.show_poll")))
    # persist cookie for a while
    resp.set_cookie("voter_id", voter_id, max_age=60*60*24*120, samesite="Lax")

    # enforce window and one-vote-per-week
    if not is_voting_open():
        return resp
    if voter_already_voted(voter_id, ip_h):
        return resp

    if option_ids:
        for oid in option_ids:
            try:
                option_int = int(oid)
            except Exception:
                continue
            record_vote(option_int)
        # log voter after successful vote(s)
        from .poll_manager import log_voter
        log_voter(voter_id, ip_h, request.headers.get("User-Agent"))
    return resp
