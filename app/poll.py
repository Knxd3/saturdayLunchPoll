"""
Poll routes.
"""
import uuid
from flask import Blueprint, render_template_string, request, redirect, url_for, make_response, session
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .timeutil import now_london, week_monday_london, to_london
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
      --chip-accent-bg: #eef2ff;
      --chip-accent-border: #bfdbfe;
      --chip-accent-text: #1e3a8a;
      --border: #e5e7eb;
      --shadow: 0 6px 24px rgba(0,0,0,0.08);
    }
    * { box-sizing: border-box; }
    body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; background: var(--bg); color: var(--text); }
    .wrap { max-width: 920px; margin: 0 auto; padding: 32px 16px 48px; }
    .subtitle { text-align:center; margin: 0 auto 24px; max-width: 720px; color: var(--muted); font-size: 14px; }
    .poll { background: var(--card); border:1px solid var(--border); box-shadow: var(--shadow); border-radius: 16px; padding: 16px; }
    form { display:grid; grid-template-columns: 1fr; gap: 12px; }
    .option { position:relative; display:flex; gap:12px; padding:14px 14px 10px; border:1px solid var(--border); background: var(--card); border-radius: 12px; align-items:flex-start; transition: border-color .15s ease, transform .05s ease, box-shadow .15s ease; cursor: pointer; width:100%; }
    .option:hover { border-color: var(--accent); box-shadow: 0 4px 16px rgba(37,99,235,0.08); }
    .option:active { transform: translateY(1px); }
    .option input { align-self:center; accent-color: var(--accent-strong); flex: 0 0 auto; }
    .option > div { flex: 1 1 auto; min-width: 0; align-self:center; }
    .meta { display:flex; flex-wrap: wrap; gap:6px; margin-top:8px; }
    .chip { border:1px solid var(--chip-border); background: var(--chip); color: var(--muted); padding: 2px 8px; border-radius: 999px; font-size: 12px; }
    .chip-cuisine { padding: 1px 7px; line-height: 1.2; }
    .chip-accent { background: rgba(238,242,255,0.75); border-color: rgba(191,219,254,0.7); color: rgba(30,58,138,0.8); }
    .chip-value  { background: rgba(236,253,245,0.75); border-color: rgba(167,243,208,0.65); color: rgba(6,95,70,0.8); }
    .name { font-weight: 700; letter-spacing:.2px; }
    .info { color: var(--muted); font-size: 12px; margin-top: 6px; display:flex; flex-wrap:wrap; gap:12px; }
    .toprow { display:flex; align-items:center; gap:10px; }
    .rank { width: 34px; height: 15px; border-radius: 6px; background: var(--chip); border:1px solid var(--chip-border); color: var(--muted); display:flex; align-items:center; justify-content:center; font-weight:600; font-size:11px; }
    .votes { margin-left:auto; background: #eef2ff; border:1px solid #dbeafe; padding:4px 10px; border-radius: 999px; font-size: 12px; color:#1e3a8a; cursor:pointer; }
    .votes:focus { outline: 2px solid var(--accent); outline-offset: 2px; }
    /* Cookie-only mode alt (kept for quick toggling):
    .vote-count { margin-left:auto; background:#eef2ff; border:1px solid #dbeafe; padding:4px 10px; border-radius:999px; font-size:12px; color:#1e3a8a; }
    */
    .voter-popup { position:absolute; top:36px; right:14px; z-index:20; background: var(--card); border:1px solid var(--border); box-shadow: var(--shadow); border-radius: 10px; padding:10px 12px; width:220px; display:none; }
    .voter-popup.open { display:block; }
    .voter-popup h4 { margin:0 0 8px; font-size:13px; font-weight:600; color:var(--text); }
    .voter-popup-list { list-style:none; margin:0; padding:0; max-height:180px; overflow-y:auto; }
    .voter-popup-list li { display:flex; align-items:center; gap:8px; padding:4px 0; font-size:12px; color:var(--text); }
    .voter-popup-list img { width:28px; height:28px; border-radius:50%; border:1px solid var(--border); object-fit:cover; }
    .avatar-fallback { width:28px; height:28px; border-radius:50%; background: var(--chip); border:1px solid var(--chip-border); display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:600; color:var(--muted); }
    .voter-popup-empty { font-size:12px; color:var(--muted); }
    .voter-popup-close { position:absolute; top:6px; right:8px; background:none; border:none; color:var(--muted); cursor:pointer; font-size:14px; }
    .voter-popup-close:hover { color:var(--accent); }
    .vote { margin-top: 16px; display:flex; justify-content:center; }
    .vote button { background: var(--accent-strong); color: #fff; border:none; padding: 10px 16px; border-radius: 10px; font-weight: 600; cursor: pointer; }
    a.link { color: var(--accent); text-decoration: none; }
    a.link:hover { text-decoration: underline; }
    /* Title link should look like plain text; only indicate on hover */
    @media (max-width: 640px) {
      .poll { padding: 12px; border-radius: 14px; }
      form { gap: 10px; }
      .option { padding: 12px; gap: 10px; }
      .option input { align-self:center; }
      .meta { gap:4px; }
      .chip { font-size: 11px; padding: 1px 7px; }
      .chip-cuisine { padding: 0 6px; }
      .chip-accent { border-color: rgba(191,219,254,0.6); color: rgba(30,58,138,0.75); }
      .chip-value { border-color: rgba(167,243,208,0.55); color: rgba(6,95,70,0.75); }
      .name { font-size: 15px; line-height: 1.25; }
      .info { font-size: 11px; gap: 8px; }
      .votes { font-size: 11px; padding: 3px 8px; }
      .voter-popup { right:10px; }
      .voter-popup h4 { font-size:12px; }
      .voter-popup-list li { font-size:11px; }
    }
    .name a, .name a.link { color: inherit; text-decoration: none; }
    .name a:hover, .name a.link:hover { color: inherit; text-decoration: underline; }
  </style>
  </head>
  <body>
    <div class="wrap">
      <!-- Top-right login/logout -->
      <div style="display:flex; justify-content:flex-end; margin-bottom:1rem;">
        {% if session.get('user') %}
          <div>
            <img src="{{ session['user']['picture'] }}" alt="profile" style="width:32px; height:32px; border-radius:50%; vertical-align:middle;">
            <a href="{{ url_for('login.logout') }}" style="color:#2563eb; text-decoration:none; margin-left:0.5rem;">Logout</a>
          </div>
        {% else %}
          <a href="{{ url_for('login.login') }}" style="color:#2563eb; text-decoration:none;">Login</a>
        {% endif %}
      </div>
      <!-- Cookie-only header (kept for quick toggling):
      <div style="display:flex; justify-content:flex-end; margin-bottom:1rem;"></div>
      -->

      <!-- Title + subtitle -->
      <div style="text-align:center; margin-bottom:1rem;">
        <h1 style="margin:1rem;">Where should we go for lunch?</h1>
        <div class="subtitle" style="font-size:0.95rem; color:#555;">
          Vote for this week's pick. Options refresh every Sunday at 09:00. Voting closes Tuesday 21:00.
        </div>
        {% if already_voted %}
          <div style="padding:10px 12px; color:#fbbf24;">Looks like you already voted this week.</div>
        {% endif %}
      </div>

      <div class="poll">
        {% if not voting_open %}
          <div style="padding:10px 12px; color:#fca5a5;">Voting is closed for this week.</div>
        {% endif %}
        <form method="POST" action="{{ url_for('poll.vote') }}">
          {% for opt in options %}
            <label class="option">
              <input type="checkbox" name="option_ids" value="{{ opt['id'] }}" {% if not can_vote or opt.get('is_excluded') %}disabled{% endif %}>
              <div>
                <div class="toprow">
                  <div class="rank">#{{ loop.index }}</div>
                  <div class="name">
                    {% if opt.get('url') %}
                      <a target="_blank" class="link" href="{{ opt['url'] }}">{{ opt['name'] }}</a>
                    {% else %}
                      {{ opt['name'] }}
                    {% endif %}
                    {% if opt.get('is_excluded') %} <span class="chip">Excluded</span>{% endif %}
                  </div>
                  {% if opt.get('cuisine') %}<span class="chip chip-cuisine">{{ opt['cuisine'] }}</span>{% endif %}
                  <div class="voter-avatars" style="display:flex; gap:4px; align-items:center; margin-left:auto;">
                    <button type="button" class="votes" data-target="voters-{{ opt['id'] }}">{{ opt['votes'] }} votes</button>
                  </div>
                  <div class="voter-popup" id="voters-{{ opt['id'] }}" role="dialog" aria-hidden="true">
                    <button type="button" class="voter-popup-close" data-target="voters-{{ opt['id'] }}" aria-label="Close">×</button>
                    <h4>Votes</h4>
                    {% if opt.get('voters') %}
                      <ul class="voter-popup-list">
                        {% for v in opt.get('voters', []) %}
                          <li>
                            {% if v.get('picture') %}
                              <img src="{{ v['picture'] }}" alt="{{ v.get('name') or 'NA' }}">
                            {% else %}
                              <div class="avatar-fallback">{{ (v.get('name') or '?')[0]|upper }}</div>
                            {% endif %}
                            <span>{{ v.get('name') or 'NA' }}</span>
                          </li>
                        {% endfor %}
                      </ul>
                    {% else %}
                      <div class="voter-popup-empty">No votes yet.</div>
                    {% endif %}
                  </div>
                  <!-- Simple total chip for cookie-only mode retained for later:
                  <div class="vote-count">{{ opt['votes'] }} votes</div>
                  -->
                </div>

                <div class="info">
                  {% if opt.get('address') %}<span>{{ opt['address'] }}</span>{% endif %}
                </div>

                <div class="meta">
                  <!-- Row 1: Cuisine -->
                  

                  <!-- Row 2: Net Average • Deal -->
                  <div style="display:flex; flex-wrap:wrap; gap:6px; width:100%;">
                    {% if opt.get('net_average') is not none %}
                      <span class="chip">
                        Net Average: £{{ '%.2f'|format(opt['net_average']) }}{% if opt.get('offer') %} • Deal: {{ opt['offer'] }}{% if opt['offer'] and ('%' not in (opt['offer']|string)) %}%{% endif %}{% endif %}
                      </span>
                    {% endif %}
                  </div>

                  <!-- Row 3: Rating (low5/hi5) + Reviews -->
                  <div style="display:flex; flex-wrap:wrap; gap:6px; width:100%;">
                    {% if opt.get('posterior_mean') is not none %}
                      <span class="chip">
                        Rating {{ '%.2f'|format(opt['posterior_mean']) }}
                        {% if opt.get('qlo5') is not none and opt.get('qhi5') is not none %}
                          ({{ '%.2f'|format(opt['qlo5']) }}–{{ '%.2f'|format(opt['qhi5']) }})
                        {% endif %}
                        {% if opt.get('reviews') %} • {{ opt['reviews'] }} reviews{% endif %}
                      </span>
                    {% endif %}
                  </div>

                  
                </div>
              </div>
            </label>
          {% endfor %}
          <div class="vote" style="width:100%; display:block"><button type="submit" {% if not can_vote %}disabled style="opacity:.6; cursor:not-allowed;"{% endif %}>Submit Votes</button></div>
        </form>
      </div>
    </div>
  <script>
    (function() {
      try {
        var chips = document.querySelectorAll('.chip');
        chips.forEach(function(el){
          var t = (el.textContent || '').trim();
          if (t.startsWith('Net Average')) {
            el.classList.add('chip-value');
          }
          if (t.startsWith('Rating')) {
            el.classList.add('chip-accent');
          }
        });
        var openPopup = null;
        var openButton = null;
        function closePopup() {
          if (openPopup) {
            openPopup.classList.remove('open');
            openPopup.setAttribute('aria-hidden', 'true');
            openPopup = null;
          }
          if (openButton) {
            openButton.setAttribute('aria-expanded', 'false');
            openButton = null;
          }
        }
        document.querySelectorAll('.votes').forEach(function(btn){
          btn.setAttribute('aria-expanded', 'false');
          btn.addEventListener('click', function(ev){
            ev.preventDefault();
            ev.stopPropagation();
            var targetId = btn.getAttribute('data-target');
            if (!targetId) {
              return;
            }
            var popup = document.getElementById(targetId);
            if (!popup) {
              return;
            }
            if (openPopup === popup) {
              closePopup();
              return;
            }
            closePopup();
            popup.classList.add('open');
            popup.setAttribute('aria-hidden', 'false');
            openPopup = popup;
            openButton = btn;
            btn.setAttribute('aria-expanded', 'true');
          });
        });
        document.querySelectorAll('.voter-popup').forEach(function(pop){
          pop.addEventListener('click', function(ev){
            ev.stopPropagation();
          });
        });
        document.querySelectorAll('.voter-popup-close').forEach(function(btn){
          btn.addEventListener('click', function(ev){
            ev.preventDefault();
            ev.stopPropagation();
            closePopup();
          });
        });
        document.addEventListener('click', function(ev){
          if (openPopup && !openPopup.contains(ev.target) && !ev.target.classList.contains('votes')) {
            closePopup();
          }
        });
        document.addEventListener('keydown', function(ev){
          if (ev.key === 'Escape') {
            closePopup();
          }
        });
        // For cookie-only mode without popups, comment out the block above and re-enable the vote-count chip.
      } catch (e) { /* no-op */ }
    })();
  </script>
  </body>
  </html>
"""


def _upcoming_saturday_iso(base_dt: datetime | None = None) -> str:
    """Return the next Saturday date (ISO) relative to the provided time."""
    dt = to_london(base_dt) if base_dt else now_london()
    days_ahead = (5 - dt.weekday()) % 7
    return (dt + timedelta(days=days_ahead)).date().isoformat()


@poll_bp.route("/")
def show_poll():
    # Ensure current week's selection exists and is up-to-date
    ensure_weekly_selection()
    options = get_current_week_selection()

    # derive identity and vote eligibility
    user = session.get("user")
    email = (user or {}).get("email") if user else None
    voter_id = email or request.cookies.get("voter_id")
    # Cookie-only mode snippet (kept for quick toggling):
    # voter_cookie = request.cookies.get("voter_id")
    # voter_id = voter_cookie or email
    client_ip = request.headers.get("Fly-Client-IP") or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr)
    already = voter_already_voted(voter_id, hash_ip(client_ip)) if voter_id or client_ip else False
    voting_open = is_voting_open()
    can_vote = voting_open and (user is not None) and not already
    # Cookie-only mode would drop the user requirement:
    # can_vote = voting_open and not already

    # Normalize mapping, trim addresses, and align URLs to the current Saturday
    normalized_options = []
    default_saturday_date = _upcoming_saturday_iso(now_london())
    try:
        window = get_voting_window()
        open_iso = window.get("open")
        if open_iso:
            open_dt = to_london(datetime.fromisoformat(open_iso))
            saturday_date = (open_dt + timedelta(days=6)).date().isoformat()
        else:
            saturday_date = default_saturday_date
    except Exception:
        saturday_date = default_saturday_date

    def _apply_date(url: str) -> str:
        try:
            parts = urlsplit(url)
            query_pairs = parse_qsl(parts.query, keep_blank_values=True)
            frag_pairs = parse_qsl(parts.fragment or "", keep_blank_values=True)

            def _upsert_date(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
                seen = False
                updated: list[tuple[str, str]] = []
                for k, v in pairs:
                    if k == "date":
                        v = saturday_date
                        seen = True
                    updated.append((k, v))
                if not seen:
                    updated.insert(0, ("date", saturday_date))
                return updated

            new_query = urlencode(_upsert_date(query_pairs))
            new_frag = urlencode(_upsert_date(frag_pairs))
            scheme = parts.scheme or "https"
            netloc = parts.netloc or "www.thefork.co.uk"
            return urlunsplit((scheme, netloc, parts.path, new_query, new_frag))
        except Exception:
            return url

    for opt in options:
        try:
            o = dict(opt)
        except Exception:
            normalized_options.append(opt)
            continue
        addr = o.get("address")
        if isinstance(addr, str):
            o["address"] = re.sub(r",\s*London\s*$", "", addr)
        url = o.get("url")
        if isinstance(url, str):
            o["url"] = _apply_date(url)
        normalized_options.append(o)
    options = normalized_options

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
    # Cookie-only mode would skip the redirect above and trust cookies/IP only.

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
# Cookie-only mode shortcut kept for easy toggling:
# def resume_vote():
#     return redirect(url_for("poll.show_poll"))
