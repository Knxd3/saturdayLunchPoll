"""
Poll routes.
"""
import uuid
from flask import Blueprint, render_template_string, request, redirect, url_for, make_response, session
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
      --bg: #f7fafc;
      --card: #ffffff;
      --muted: #6b7280;
      --accent: #2563eb;
      --accent-strong: #1d4ed8;
      --text: #111827;
      --chip: #f3f4f6;
      --chip-border: #e5e7eb;
      --border: #e5e7eb;
      --shadow: 0 6px 24px rgba(0,0,0,0.08);
    }
    * { box-sizing: border-box; }
    body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; background: var(--bg); color: var(--text); }
    .wrap { max-width: 920px; margin: 0 auto; padding: 32px 16px 48px; }
    .title { text-align:center; margin-bottom: 8px; font-size: 28px; letter-spacing: 0.2px; }
    .subtitle { text-align:center; margin: 0 auto 24px; max-width: 720px; color: var(--muted); font-size: 14px; }
    .poll { background: var(--card); border:1px solid var(--border); box-shadow: var(--shadow); border-radius: 16px; padding: 16px; }
    form { display:grid; grid-template-columns: 1fr; gap: 12px; }
    @media (min-width: 840px){ form { grid-template-columns: 1fr 1fr; } }
    .option { display:flex; gap:12px; padding:14px; border:1px solid var(--border); background: var(--card); border-radius: 12px; align-items:flex-start; transition: border-color .15s ease, transform .05s ease, box-shadow .15s ease; cursor: pointer; }
    .option:hover { border-color: var(--accent); box-shadow: 0 4px 16px rgba(37,99,235,0.08); }
    .option:active { transform: translateY(1px); }
    .option input { margin-top: 4px; accent-color: var(--accent-strong); }
    .meta { display:flex; flex-wrap: wrap; gap:6px; margin-top:8px; }
    .chip { border:1px solid var(--chip-border); background: var(--chip); color: var(--muted); padding: 2px 8px; border-radius: 999px; font-size: 12px; }
    .name { font-weight: 700; letter-spacing:.2px; }
    .info { color: var(--muted); font-size: 12px; margin-top: 6px; display:flex; flex-wrap:wrap; gap:12px; }
    .toprow { display:flex; align-items:center; gap:10px; }
    .votes { margin-left:auto; background: #eef2ff; border:1px solid #dbeafe; padding:4px 10px; border-radius: 999px; font-size: 12px; color:#1e3a8a; }
    .vote { margin-top: 16px; display:flex; justify-content:center; }
    .vote button { background: var(--accent-strong); color: #fff; border:none; padding: 10px 16px; border-radius: 10px; font-weight: 600; cursor: pointer; }
    a.link { color: var(--accent); text-decoration: none; }
    a.link:hover { text-decoration: underline; }
  </style>
  </head>
  <body>
    <div class="wrap">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
      <h1 style = "flex:1; text-align:center; margin:0;">Where should we go for lunch?</h1>
      {% if session.get('user') %}
        <div>
          <img src="{{ session['user']['picture'] }}" alt="profile" style="width:32px; height:32px; border-radius:50%;">
          <!-- <span style="font-size:0.9rem; margin-right:1rem; margin-left:auto;">{{ session['user']['email'] }}</span> -->
          <a href="{{ url_for('login.logout') }}" style="color:#2563eb; text-decoration:none;">Logout</a>
        </div>
      {% else %}
        <a href="{{ url_for('login.login') }}" style="color:#2563eb; text-decoration:none;">Login</a>
      {% endif %}
      </div>
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
                <div class="toprow">
                  <div class="name">{{ opt['name'] }}</div>
                  <div class="voter-avatars" style="display:flex; gap:4px; align-items:center; margin-left:auto;">
                    {% for v in opt.get('voters', []) %}
                      {% if v.get('picture') %}
                        <img src="{{ v['picture'] }}" alt="{{ v.get('name') or v.get('email') }}" title="{{ v.get('name') or v.get('email') }}" style="width:18px; height:18px; border-radius:50%; border:1px solid #e5e7eb;" />
                      {% endif %}
                    {% endfor %}
                    <span class="votes" title="{{ (opt.get('voters') or []) | map(attribute='name') | join(', ') }}">{{ opt['votes'] }} votes</span>
                  </div>
                </div>
                <div class="info">
                  {% if opt.get('average_price') %}<span>{{ opt['average_price'] }}</span>{% endif %}
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
          <div class="vote" style="width:100%; display:block"><button type="submit" {% if not can_vote %}disabled style="opacity:.6; cursor:not-allowed;"{% endif %}>Submit Votes</button></div>
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
    user = session.get("user")
    email = (user or {}).get("email") if user else None
    voter_id = email or request.cookies.get("voter_id")
    client_ip = request.headers.get("Fly-Client-IP") or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr)
    already = voter_already_voted(voter_id, hash_ip(client_ip)) if voter_id or client_ip else False
    voting_open = is_voting_open()
    can_vote = voting_open and (user is not None) and not already
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
    # require login
    user = session.get("user")
    if not user:
        # stash pending selections and bounce to login
        if option_ids:
            session["pending_option_ids"] = option_ids
        session["post_login_redirect"] = "poll.resume_vote"
        return redirect(url_for("login.login", next="poll.resume_vote"))
    # identify voter via email
    voter_id = user.get("email") or uuid.uuid4().hex
    client_ip = request.headers.get("Fly-Client-IP") or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr)
    ip_h = hash_ip(client_ip)

    resp = make_response(redirect(url_for("poll.show_poll")))
    # persist an opaque cookie for a while (not email)
    cookie_id = request.cookies.get("voter_id") or uuid.uuid4().hex
    resp.set_cookie("voter_id", cookie_id, max_age=60*60*24*120, samesite="Lax")

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
            record_vote(option_int, user)
        # log voter after successful vote(s)
        from .poll_manager import log_voter
        log_voter(voter_id, ip_h, request.headers.get("User-Agent"), email=voter_id)
    return resp


@poll_bp.route("/vote/resume")
def resume_vote():
    """After login, complete any pending selections stored in session."""
    ensure_weekly_selection()
    user = session.get("user")
    if not user:
        session["post_login_redirect"] = "poll.resume_vote"
        return redirect(url_for("login.login", next="poll.resume_vote"))
    # identify voter via email
    voter_id = user.get("email") or uuid.uuid4().hex
    client_ip = request.headers.get("Fly-Client-IP") or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr)
    ip_h = hash_ip(client_ip)

    # enforce window and one-vote-per-week
    resp = make_response(redirect(url_for("poll.show_poll")))
    if not is_voting_open():
        session.pop("pending_option_ids", None)
        return resp
    if voter_already_voted(voter_id, ip_h):
        session.pop("pending_option_ids", None)
        return resp

    option_ids = session.pop("pending_option_ids", []) or []
    for oid in option_ids:
        try:
            option_int = int(oid)
        except Exception:
            continue
        record_vote(option_int, user)
    from .poll_manager import log_voter
    log_voter(voter_id, ip_h, request.headers.get("User-Agent"), email=voter_id)
    return resp
