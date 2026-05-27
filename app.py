import json
from datetime import datetime, date, time
from zoneinfo import Zone CONFIGfrom zoneinfo import ZoneInfo
# -----------------------------
st.set_page_config(page_title="Tipping Comp", page_icon="🏉", layout="wide")

TZ = ZoneInfo("Pacific/Auckland")
STORE_FILE = "tipping.json"

# Initial players (as requested)
DEFAULT_PLAYERS = ["moody", "coops", "dan"]

DEFAULT_STATE = {
    "players": DEFAULT_PLAYERS,
    "password_overrides": {},  # optional: {player: "custompw"}
    "current_round": "",       # admin sets this
    "rounds": {},              # round_name -> round object
}

# Optional Admin PIN via Streamlit secrets (Streamlit Cloud -> App -> Settings -> Secrets)
ADMIN_PIN = ""
try:
    ADMIN_PIN = str(st.secrets.get("ADMIN_PIN", "")).strip()
except Exception:
    ADMIN_PIN = ""

# -----------------------------
# STYLE
# -----------------------------
st.markdown(
    """
<style>
:root{
  --card: rgba(255,255,255,0.04);
  --border: rgba(255,255,255,0.14);
  --muted: rgba(255,255,255,0.70);
  --good: #34d399;
  --warn: #fbbf24;
  --bad:  #fb7185;
}

.block-container{ padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1250px;}
[data-testid="stSidebar"]{ border-right: 1px solid var(--border); }

.card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px 14px 10px 14px;
  box-shadow: 0 10px 18px rgba(0,0,0,0.18);
}
.kpi-title{ color: var(--muted); font-size: .85rem; margin-bottom: 6px;}
.kpi-value{ font-size: 1.6rem; font-weight: 800; line-height: 1.05;}
.kpi-sub{ color: var(--muted); font-size: .85rem; margin-top: 6px;}

.banner{
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 12px 14px;
  background: rgba(255,255,255,0.03);
  margin-bottom: 12px;
}
.banner .title{ font-size: 1.05rem; font-weight: 800; }
.banner .meta{ color: var(--muted); margin-top: 4px; font-size: .90rem; }
.pill{
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-size: .82rem;
  margin-right: 6px;
}
.pill.good{ border-color: rgba(52,211,153,0.55); color: var(--good); }
.pill.warn{ border-color: rgba(251,191,36,0.55); color: var(--warn); }
.pill.bad{ border-color: rgba(251,113,133,0.55); color: var(--bad); }

.small{ color: var(--muted); font-size: .90rem; }
.stButton>button{ border-radius: 12px; font-weight: 650; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# HELPERS
# -----------------------------
def now_nz():
    return datetime.now(TZ)

def iso_from_date_time(d, t):
    dt_ = datetime.combine(d, t).replace(tzinfo=TZ)
    return dt_.isoformat()

def parse_iso(iso_str):
    if not iso_str:
        return None
    try:
        dt_ = datetime.fromisoformat(iso_str)
        if dt_.tzinfo is None:
            dt_ = dt_.replace(tzinfo=TZ)
        return dt_.astimezone(TZ)
    except Exception:
        return None

def norm_text(s: str) -> str:
    return " ".join((s or "").strip().lower().split())

def compute_initials(name):
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return ""
    ini = "".join([p[0] for p in parts]).upper()
    return ini[:3]

def expected_password(state, player):
    overrides = state.get("password_overrides", {})
    if isinstance(overrides, dict) and overrides.get(player):
        return str(overrides[player]).strip()
    return compute_initials(player)

def round_deadline(round_obj):
    return parse_iso(round_obj.get("deadline", ""))

def round_multiplier(round_obj):
    try:
        return float(round_obj.get("multiplier", 1.0))
    except Exception:
        return 1.0

def round_locked(round_obj):
    if bool(round_obj.get("finalized", False)):
        return True
    dl = round_deadline(round_obj)
    if dl is None:
        return False
    return now_nz() >= dl

def fmt_countdown(dl_dt):
    if not dl_dt:
        return "No deadline set"
    delta = dl_dt - now_nz()
    if delta.total_seconds() <= 0:
        return "Closed"
    days = delta.days
    hrs, rem = divmod(delta.seconds, 3600)
    mins, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hrs}h {mins}m"
    return f"{hrs}h {mins}m"

def donut_or_zero(val, show_donut):
    if show_donut and (val == 0 or val == 0.0):
        return "🍩"
    return str(val)

# -----------------------------
# DATA MODEL
# -----------------------------
# round = {
#   "deadline": ISO string,
#   "multiplier": 1.0/1.5/2.0,
#   "double_up_enabled": True/False,
#   "finalized": True/False,
#   "games": [
#       {
#         "id": "R1G1",
#         "label": "Chiefs vs Blues" OR "Who will win Tour de France?",
#         "points": 1,
#         "type": "choice" or "text",
#         "options": [{"key":"A","label":"Chiefs"}, {"key":"B","label":"Blues"}] (2 or 3 options)   # only for type=choice
#       }
#   ],
#   "results": {game_id: option_key OR free text},
#   "tips": {player: {game_id: option_key OR free text}},
#   "double_up": {player: game_id or ""}  # per round
# }

def load_state():
    try:
        with open(STORE_FILE, "r") as f:
            s = json.load(f)
            if not isinstance(s, dict):
                s = {}
    except Exception:
        s = {}

    for k, v in DEFAULT_STATE.items():
        if k not in s:
            s[k] = v if not isinstance(v, list) else list(v)

    if not isinstance(s.get("players"), list):
        s["players"] = list(DEFAULT_PLAYERS)
    if not isinstance(s.get("password_overrides"), dict):
        s["password_overrides"] = {}
    if not isinstance(s.get("rounds"), dict):
        s["rounds"] = {}

    # normalize rounds
    for rn, r in list(s["rounds"].items()):
        if not isinstance(r, dict):
            s["rounds"][rn] = {}
            r = s["rounds"][rn]
        r.setdefault("deadline", "")
        r.setdefault("multiplier", 1.0)
        r.setdefault("double_up_enabled", False)
        r.setdefault("finalized", False)
        r.setdefault("games", [])
        r.setdefault("results", {})
        r.setdefault("tips", {})
        r.setdefault("double_up", {})

        if not isinstance(r["games"], list):
            r["games"] = []
        if not isinstance(r["results"], dict):
            r["results"] = {}
        if not isinstance(r["tips"], dict):
            r["tips"] = {}
        if not isinstance(r["double_up"], dict):
            r["double_up"] = {}

        fixed_games = []
        for i, g in enumerate(r["games"]):
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id") or f"{rn.replace(' ','')}G{i+1}")
            label = str(g.get("label") or f"Question {i+1}")
            try:
                pts = int(g.get("points", 1))
            except Exception:
                pts = 1

            gtype = g.get("type", "choice")
            if gtype not in ("choice", "text"):
                gtype = "choice"

            if gtype == "text":
                fixed_games.append({"id": gid, "label": label, "points": pts, "type": "text"})
                r["results"].setdefault(gid, "")
            else:
                options = g.get("options", [])
                if not isinstance(options, list) or len(options) not in (2, 3):
                    options = [{"key": "A", "label": "Option A"}, {"key": "B", "label": "Option B"}]

                norm_opts = []
                for j, o in enumerate(options):
                    if not isinstance(o, dict):
                        continue
                    k = str(o.get("key") or chr(65 + j))
                    lab = str(o.get("label") or f"Option {k}")
                    norm_opts.append({"key": k, "label": lab})
                if len(norm_opts) not in (2, 3):
                    norm_opts = [{"key": "A", "label": "Option A"}, {"key": "B", "label": "Option B"}]

                fixed_games.append({"id": gid, "label": label, "points": pts, "type": "choice", "options": norm_opts})
                r["results"].setdefault(gid, "")

        r["games"] = fixed_games

        for p in s["players"]:
            r["tips"].setdefault(p, {})
            if not isinstance(r["tips"][p], dict):
                r["tips"][p] = {}
            r["double_up"].setdefault(p, "")

    if not s.get("current_round"):
        non_final = [rn for rn in s["rounds"].keys() if not bool(s["rounds"][rn].get("finalized", False))]
        s["current_round"] = non_final[-1] if non_final else (list(s["rounds"].keys())[-1] if s["rounds"] else "")

    return s

def save_state(state):
    with open(STORE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# -----------------------------
# SCORING
# -----------------------------
def calc_all_scores(state):
    players = state["players"]
    totals = {p: 0.0 for p in players}
    round_points = {p: {} for p in players}
    correct = {p: 0 for p in players}
    decided = {p: 0 for p in players}

    for rn, r in state["rounds"].items():
        mult = round_multiplier(r)
        results = r.get("results", {})
        games = r.get("games", [])
        tips = r.get("tips", {})
        du = r.get("double_up", {})
        du_enabled = bool(r.get("double_up_enabled", False))

        pts_map = {g["id"]: int(g.get("points", 1)) for g in games}

        for p in players:
            rp = 0.0
            p_tips = tips.get(p, {})
            p_du_game = du.get(p, "") if du_enabled else ""

            for g in games:
                gid = g["id"]
                res = results.get(gid, "")
                if not res:
                    continue  # not decided
                decided[p] += 1
                pick = p_tips.get(gid, "")

                is_correct = False
                if g.get("type") == "text":
                    is_correct = norm_text(pick) != "" and norm_text(pick) == norm_text(res)
                else:
                    is_correct = pick and pick == res

                if is_correct:
                    correct[p] += 1
                    base = pts_map.get(gid, 1) * mult
                    if p_du_game == gid:
                        base *= 2
                    rp += base

            totals[p] += rp
            round_points[p][rn] = rp

    return totals, round_points, correct, decided

def accuracy_pct(corr, dec):
    return (corr / dec * 100.0) if dec else 0.0

# -----------------------------
# INIT
# -----------------------------
state = load_state()
players = state["players"]

if "auth_player" not in st.session_state:
    st.session_state.auth_player = None

# -----------------------------
# SIDEBAR: LOGIN + NAV
# -----------------------------
with st.sidebar:
    st.markdown("### 🏉 Tipping Comp")
    st.markdown('<div class="small">Log in (initials), enter tips, track rounds.</div>', unsafe_allow_html=True)
    st.write("")

    if st.session_state.auth_player:
        st.success(f"Logged in: {st.session_state.auth_player}")
        if st.button("Log out"):
            st.session_state.auth_player = None
            st.rerun()
    else:
        login_player = st.selectbox("Your name", players)
        login_pass = st.text_input("Password (your initials)", type="password")
        if st.button("Log in"):
            if login_pass.strip().upper() == expected_password(state, login_player).upper():
                st.session_state.auth_player = login_player
                st.rerun()
            else:
                st.error("Wrong password. Use your initials (e.g., John Moody → JM).")

    st.divider()
    page = st.radio("Go to", ["🏁 Current Round", "📝 Enter Tips", "🏆 Leaderboard", "📊 Stats", "✅ Admin"], index=0)

# -----------------------------
# GLOBAL BANNER
# -----------------------------
current_round = state.get("current_round", "")
current_obj = state["rounds"].get(current_round) if current_round else None

banner_title = f"Current Round: {current_round}" if current_round else "Current Round: (not set)"
pill_bits = []
meta_bits = []

if current_obj:
    dl = round_deadline(current_obj)
    cd = fmt_countdown(dl)
    locked = round_locked(current_obj)
    finalized = bool(current_obj.get("finalized", False))
    mult = round_multiplier(current_obj)
    du_enabled = bool(current_obj.get("double_up_enabled", False))

    if finalized:
        pill_bits.append('<span class="pill bad">FINALIZED</span>')
    elif locked:
        pill_bits.append('<span class="pill warn">CLOSED</span>')
    else:
        pill_bits.append('<span class="pill good">OPEN</span>')

    pill_bits.append(f'<span class="pill">x{mult:g}</span>')
    if du_enabled:
        pill_bits.append('<span class="pill">Double‑Up ON</span>')

    meta_bits.append(f"Deadline: {dl.strftime('%a %d %b %I:%M%p') if dl else 'Not set'}")
    meta_bits.append(f"Countdown: {cd}")

st.markdown(
    f"""
<div class="banner">
  <div class="title">{banner_title}</div>
  <div style="margin-top:6px;">{" ".join(pill_bits)}</div>
  <div class="meta">{" • ".join(meta_bits) if meta_bits else ""}</div>
</div>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# COMPUTE SCORES
# -----------------------------
totals, rp_map, correct, decided = calc_all_scores(state)

leader_df = pd.DataFrame({
    "Player": players,
    "Points": [round(totals[p], 1) for p in players],
    "Correct": [correct[p] for p in players],
    "Decided": [decided[p] for p in players],
    "Accuracy %": [round(accuracy_pct(correct[p], decided[p]), 1) for p in players],
}).sort_values(["Points", "Accuracy %", "Correct"], ascending=[False, False, False]).reset_index(drop=True)
leader_df.index = leader_df.index + 1

# -----------------------------
# PAGE: CURRENT ROUND
# -----------------------------
if page == "🏁 Current Round":
    st.markdown("### 🏁 Current Round Overview")

    if not current_round or current_round not in state["rounds"]:
        st.info("Admin hasn’t set a current round yet.")
    else:
        r = state["rounds"][current_round]
        games = r.get("games", [])
        results = r.get("results", {})
        finalized = bool(r.get("finalized", False))

        left, right = st.columns([2, 1])

        with left:
            st.markdown("#### Questions / Games")
            if not games:
                st.info("No questions added yet.")
            else:
                rows = []
                for g in games:
                    gid = g["id"]
                    pts = int(g.get("points", 1))
                    gtype = g.get("type", "choice")
                    res_val = results.get(gid, "")
                    if gtype == "text":
                        opt_txt = "Open text"
                        res_label = res_val.strip() if res_val else "—"
                    else:
                        opt_txt = " / ".join([o["label"] for o in g["options"]])
                        res_label = next((o["label"] for o in g["options"] if o["key"] == res_val), "—")
                        if not res_val:
                            res_label = "—"

                    rows.append({
                        "Question": g["label"],
                        "Type": "1 answer (text)" if gtype == "text" else f"{len(g['options'])} outcomes",
                        "Options": opt_txt,
                        "Points": pts,
                        "Result": res_label,
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=420)

        with right:
            st.markdown("#### Round snapshot")
            if players:
                data_rows = []
                for p in players:
                    pts = round(float(rp_map.get(p, {}).get(current_round, 0.0)), 1)
                    data_rows.append({"Player": p, "Round Points": donut_or_zero(pts, finalized), "Total": round(totals[p], 1)})
                df = pd.DataFrame(data_rows).sort_values("Total", ascending=False)
                st.dataframe(df, use_container_width=True, height=420)
            else:
                st.info("No players yet.")

# -----------------------------
# PAGE: ENTER TIPS
# -----------------------------
elif page == "📝 Enter Tips":
    st.markdown("### 📝 Enter Tips")

    if not st.session_state.auth_player:
        st.warning("Please log in in the sidebar first.")
        st.stop()

    if not current_round or current_round not in state["rounds"]:
        st.warning("No current round is set yet.")
        st.stop()

    r = state["rounds"][current_round]
    locked = round_locked(r)
    finalized = bool(r.get("finalized", False))
    games = r.get("games", [])
    du_enabled = bool(r.get("double_up_enabled", False))

    if finalized:
        st.warning("This round is FINALIZED — tips are closed.")
    elif locked:
        st.warning("This round is CLOSED — tips are locked.")
    else:
        st.success("Round is OPEN — enter your tips below.")

    if not games:
        st.info("No questions have been added for this round.")
        st.stop()

    player = st.session_state.auth_player
    p_tips = r["tips"].get(player, {})
    p_du = r["double_up"].get(player, "")

    st.markdown('<div class="small">Questions can be either open text (1 answer) or choice (2/3 outcomes). If Double‑Up is enabled, choose one question to double.</div>', unsafe_allow_html=True)
    st.write("")

    du_choices = ["— none —"] + [g["id"] for g in games]
    def du_fmt(gid):
        if gid == "— none —":
            return "— none —"
        g = next((x for x in games if x["id"] == gid), None)
        return g["label"] if g else gid

    with st.form("tips_form"):
        updated_tips = {}

        for g in games:
            gid = g["id"]
            pts = int(g.get("points", 1))
            gtype = g.get("type", "choice")

            if gtype == "text":
                current = p_tips.get(gid, "")
                ans = st.text_input(
                    f"{g['label']}  •  ({pts} pts)  •  (type your answer)",
                    value=current,
                    disabled=locked,
                    key=f"texttip_{current_round}_{player}_{gid}",
                )
                updated_tips[gid] = ans
            else:
                options = [""] + [o["key"] for o in g["options"]]
                label_map = {"": "— no pick —"}
                for o in g["options"]:
                    label_map[o["key"]] = o["label"]

                current = p_tips.get(gid, "")
                idx = options.index(current) if current in options else 0

                choice = st.selectbox(
                    f"{g['label']}  •  ({pts} pts)",
                    options=options,
                    index=idx,
                    format_func=lambda x: label_map.get(x, x),
                    disabled=locked,
                    key=f"choicetip_{current_round}_{player}_{gid}",
                )
                updated_tips[gid] = choice

        st.divider()
        if du_enabled:
            du_sel = st.selectbox(
                "Double‑Up: choose ONE question to double",
                options=du_choices,
                index=(du_choices.index(p_du) if p_du in du_choices else 0),
                format_func=du_fmt,
                disabled=locked,
                key=f"du_{current_round}_{player}",
            )
        else:
            du_sel = "— none —"
            st.info("Double‑Up is OFF for this round.")

        submitted = st.form_submit_button("Save tips", disabled=locked)

    if submitted:
        r["tips"].setdefault(player, {})

        # Save tips
        for gid, pick in updated_tips.items():
            g = next((x for x in games if x["id"] == gid), None)
            if not g:
                continue

            if g.get("type") == "text":
                # keep free text; allow empty to clear
                if norm_text(pick):
                    r["tips"][player][gid] = pick.strip()
                else:
                    r["tips"][player].pop(gid, None)
            else:
                if pick:
                    r["tips"][player][gid] = pick
                else:
                    r["tips"][player].pop(gid, None)

        # Save double-up (validate: must have a non-empty tip on that question)
        if du_enabled:
            if du_sel == "— none —":
                r["double_up"][player] = ""
            else:
                tip_val = r["tips"][player].get(du_sel, "")
                if not norm_text(str(tip_val)):
                    st.error("To use Double‑Up, you must also enter a tip for that question.")
                    save_state(state)
                    st.stop()
                r["double_up"][player] = du_sel
        else:
            r["double_up"][player] = ""

        save_state(state)
        st.success("Saved.")
        st.rerun()

# -----------------------------
# PAGE: LEADERBOARD
# -----------------------------
elif page == "🏆 Leaderboard":
    st.markdown("### 🏆 Leaderboard")
    st.dataframe(leader_df, use_container_width=True, height=520)

    st.markdown("### 📅 Round-by-round points")
    rnames = list(state["rounds"].keys())
    if not rnames:
        st.info("No rounds yet.")
    else:
        rp = pd.DataFrame({"Player": players})
        for rn in rnames:
            finalized = bool(state["rounds"][rn].get("finalized", False))
            col_vals = []
            for p in players:
                pts = round(float(rp_map.get(p, {}).get(rn, 0.0)), 1)
                col_vals.append(donut_or_zero(pts, finalized))
            rp[rn] = col_vals

        rp["_TotalNumeric"] = [round(float(totals[p]), 1) for p in players]
        rp["Total"] = rp["_TotalNumeric"].astype(str)
        rp = rp.sort_values("_TotalNumeric", ascending=False).drop(columns=["_TotalNumeric"]).reset_index(drop=True)
        st.dataframe(rp, use_container_width=True)

# -----------------------------
# PAGE: STATS
# -----------------------------
elif page == "📊 Stats":
    st.markdown("### 📊 Stats")
    if not state["rounds"]:
        st.info("No rounds yet.")
        st.stop()

    rnames = list(state["rounds"].keys())

    rows = []
    for p in players:
        running = 0.0
        for rn in rnames:
            pts = float(rp_map.get(p, {}).get(rn, 0.0))
            running += pts
            rows.append({"Player": p, "Round": rn, "Round Points": pts, "Total Points": running})
    ts = pd.DataFrame(rows)

    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("#### Total points over rounds")
        line = alt.Chart(ts).mark_line(point=True).encode(
            x=alt.X("Round:N", sort=rnames),
            y=alt.Y("Total Points:Q"),
            color=alt.Color("Player:N"),
            tooltip=["Player", "Round", "Round Points", "Total Points"],
        ).properties(height=360)
        st.altair_chart(line, use_container_width=True)

    with c2:
        st.markdown("#### Accuracy vs Points")
        sc = leader_df.copy()
        scatter = alt.Chart(sc).mark_circle(size=150).encode(
            x=alt.X("Accuracy %:Q", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("Points:Q"),
            color=alt.Color("Player:N"),
            tooltip=["Player", "Points", "Accuracy %", "Correct", "Decided"],
        ).properties(height=360)
        st.altair_chart(scatter, use_container_width=True)

# -----------------------------
# PAGE: ADMIN
# -----------------------------
elif page == "✅ Admin":
    st.markdown("### ✅ Admin")

    if ADMIN_PIN:
        pin = st.text_input("Admin PIN", type="password")
        if pin.strip() != ADMIN_PIN:
            st.warning("Enter the correct Admin PIN to use admin tools.")
            st.stop()

    st.markdown("#### Current round control")
    all_rounds = list(state["rounds"].keys())
    colA, colB = st.columns([2, 1])

    with colA:
        current_round_new = st.selectbox(
            "Set current round",
            options=[""] + all_rounds,
            index=([""] + all_rounds).index(state.get("current_round", "")) if state.get("current_round", "") in ([""] + all_rounds) else 0
        )
        if st.button("Save current round"):
            state["current_round"] = current_round_new
            save_state(state)
            st.success("Saved.")
            st.rerun()

    with colB:
        if state.get("current_round") and state["current_round"] in state["rounds"]:
            r = state["rounds"][state["current_round"]]
            if st.button("FINALISE current round", type="primary"):
                r["finalized"] = True
                save_state(state)
                st.success("Round finalised. Tips are locked and donuts will display for zero scores.")
                st.rerun()

    st.divider()

    st.markdown("#### Create / edit round settings")
    new_round_name = st.text_input("Round name (new or existing)", placeholder="e.g., Round 5")

    dcol1, dcol2, dcol3, dcol4 = st.columns([1, 1, 1, 1])
    with dcol1:
        dl_date = st.date_input("Deadline date", value=date.today(), key="dl_date")
    with dcol2:
        dl_time = st.time_input("Deadline time", value=time(18, 0), key="dl_time")
    with dcol3:
        mult = st.selectbox("Multiplier", [1.0, 1.5, 2.0], index=0, key="mult_sel")
    with dcol4:
        du_enabled = st.toggle("Enable Double‑Up", value=False, key="du_toggle")

    if st.button("Add / Update round settings"):
        rn = new_round_name.strip()
        if not rn:
            st.warning("Enter a round name.")
        else:
            state["rounds"].setdefault(rn, {
                "deadline": "",
                "multiplier": 1.0,
                "double_up_enabled": False,
                "finalized": False,
                "games": [],
                "results": {},
                "tips": {},
                "double_up": {},
            })
            r = state["rounds"][rn]
            r["deadline"] = iso_from_date_time(dl_date, dl_time)
            r["multiplier"] = float(mult)
            r["double_up_enabled"] = bool(du_enabled)

            for p in state["players"]:
                r["tips"].setdefault(p, {})
                r["double_up"].setdefault(p, "")

            save_state(state)
            st.success("Saved round settings.")
            st.rerun()

    st.divider()

    st.markdown("#### Add question/game (1 answer OR 2/3 outcomes)")
    if not state["rounds"]:
        st.info("Create a round first.")
        st.stop()

    rn = st.selectbox("Edit round", list(state["rounds"].keys()), key="edit_round")
    r = state["rounds"][rn]

    st.caption(
        f"Deadline: {round_deadline(r).strftime('%a %d %b %I:%M%p') if round_deadline(r) else 'Not set'} "
        f"• Locked: {'Yes' if round_locked(r) else 'No'} • Finalized: {'Yes' if bool(r.get('finalized', False)) else 'No'}"
    )

    gcol1, gcol2 = st.columns([2, 1])
    with gcol1:
        q_label = st.text_input("Question / match label", placeholder="e.g., Chiefs vs Blues OR Who will win Tour de France?")
    with gcol2:
        pts = st.number_input("Points", min_value=1, max_value=100, value=1, step=1)

    mode = st.selectbox(
        "Question type",
        ["1 answer (open text)", "2 outcomes (A/B)", "3 outcomes (A/Draw/B)"],
        index=1
    )

    game_obj = None

    if mode.startswith("1"):
        game_obj = {"type": "text"}
        st.info("Players will type a free-text answer. Admin also types the correct answer in Results.")
    elif mode.startswith("2"):
        o1, o2 = st.columns(2)
        with o1:
            optA = st.text_input("Option A label", value="Home / Team A")
        with o2:
            optB = st.text_input("Option B label", value="Away / Team B")
        game_obj = {"type": "choice", "options": [{"key": "A", "label": optA.strip() or "Option A"},
                                                  {"key": "B", "label": optB.strip() or "Option B"}]}
    else:
        o1, o2, o3 = st.columns(3)
        with o1:
            optA = st.text_input("Option A label", value="Home")
        with o2:
            optD = st.text_input("Draw label", value="Draw")
        with o3:
            optB = st.text_input("Option B label", value="Away")
        game_obj = {"type": "choice", "options": [{"key": "A", "label": optA.strip() or "A"},
                                                  {"key": "D", "label": optD.strip() or "Draw"},
                                                  {"key": "B", "label": optB.strip() or "B"}]}

    if st.button("Add question/game"):
        if not q_label.strip():
            st.warning("Enter a label for the question/game.")
        else:
            gid = f"{rn.replace(' ','')}G{len(r['games'])+1}"
            base = {"id": gid, "label": q_label.strip(), "points": int(pts)}
            base.update(game_obj)
            r["games"].append(base)
            r["results"][gid] = ""
            for p in state["players"]:
                r["tips"].setdefault(p, {})
                r["double_up"].setdefault(p, "")
            save_state(state)
            st.success("Added.")
            st.rerun()

    st.write("")
    st.markdown("##### Existing questions/games")
    if not r["games"]:
        st.info("None yet.")
    else:
        for g in r["games"]:
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                st.write(f"**{g['label']}**")
                if g.get("type") == "text":
                    st.caption("Type: 1 answer (open text)")
                else:
                    st.caption("Options: " + " / ".join([o["label"] for o in g["options"]]))
            with c2:
                st.write(f"{int(g.get('points',1))} pts")
            with c3:
                if st.button("🗑️", key=f"del_{rn}_{g['id']}"):
                    gid = g["id"]
                    r["games"] = [x for x in r["games"] if x["id"] != gid]
                    r["results"].pop(gid, None)
                    for p in state["players"]:
                        r["tips"].get(p, {}).pop(gid, None)
                        if r["double_up"].get(p) == gid:
                            r["double_up"][p] = ""
                    save_state(state)
                    st.rerun()

    st.divider()

    st.markdown("#### Enter results")
    if not r["games"]:
        st.info("Add games first.")
    else:
        with st.form("results_form"):
            updates = {}
            for g in r["games"]:
                gid = g["id"]
                current = r["results"].get(gid, "")
                if g.get("type") == "text":
                    val = st.text_input(f"Result (text): {g['label']}", value=current, key=f"res_text_{rn}_{gid}")
                    updates[gid] = val
                else:
                    opts = [""] + [o["key"] for o in g["options"]]
                    label_map = {"": "— no result —"}
                    for o in g["options"]:
                        label_map[o["key"]] = o["label"]
                    idx = opts.index(current) if current in opts else 0
                    choice = st.selectbox(
                        f"Result: {g['label']}",
                        options=opts,
                        index=idx,
                        format_func=lambda x: label_map.get(x, x),
                        key=f"res_choice_{rn}_{gid}",
                    )
                    updates[gid] = choice
            save_btn = st.form_submit_button("Save results")

        if save_btn:
            for gid, res in updates.items():
                r["results"][gid] = res.strip() if isinstance(res, str) else res
            save_state(state)
            st.success("Saved results.")
            st.rerun()

    st.divider()

    st.markdown("#### Players & passwords")
    st.markdown('<div class="small">Default password is initials (e.g., John Moody → JM). You can override. Add-player behaviour unchanged.</div>', unsafe_allow_html=True)

    pcol1, pcol2 = st.columns(2)
    with pcol1:
        new_player = st.text_input("Add player", placeholder="Name", key="add_player").strip()
        if st.button("Add player", key="btn_add_player"):
            if new_player and new_player not in state["players"]:
                state["players"].append(new_player)
                for rr in state["rounds"].values():
                    rr["tips"].setdefault(new_player, {})
                    rr["double_up"].setdefault(new_player, "")
                save_state(state)
                st.success("Added player.")
                st.rerun()
            else:
                st.warning("Blank or already exists.")

    with pcol2:
        remove_player = st.selectbox("Remove player", [""] + state["players"], key="remove_player")
        if remove_player and st.button("Remove selected", key="btn_remove_player"):
            state["players"] = [p for p in state["players"] if p != remove_player]
            state["password_overrides"].pop(remove_player, None)
            for rr in state["rounds"].values():
                rr["tips"].pop(remove_player, None)
                rr["double_up"].pop(remove_player, None)
            if st.session_state.auth_player == remove_player:
                st.session_state.auth_player = None
            save_state(state)
            st.success("Removed.")
            st.rerun()

    st.write("")
    st.markdown("##### Rename player (safe)")
    old_name = st.selectbox("Player to rename", state["players"], key="rename_old")
    new_name = st.text_input("New name", key="rename_new").strip()
    if st.button("Rename player", key="btn_rename"):
        if not new_name:
            st.warning("Enter a new name.")
        elif new_name in state["players"]:
            st.warning("That name already exists.")
        else:
            state["players"] = [new_name if p == old_name else p for p in state["players"]]
            for rr in state["rounds"].values():
                if old_name in rr["tips"]:
                    rr["tips"][new_name] = rr["tips"].pop(old_name)
                if old_name in rr["double_up"]:
                    rr["double_up"][new_name] = rr["double_up"].pop(old_name)
            if old_name in state["password_overrides"]:
                state["password_overrides"][new_name] = state["password_overrides"].pop(old_name)
            if st.session_state.auth_player == old_name:
                st.session_state.auth_player = new_name
            save_state(state)
            st.success("Renamed.")
            st.rerun()

    st.write("")
    st.markdown("##### Password override (optional)")
    tgt = st.selectbox("Choose player", state["players"], key="pw_tgt")
    override = st.text_input("Override password (blank = initials)", value=str(state["password_overrides"].get(tgt, "")), key="pw_override")
    if st.button("Save override", key="btn_save_override"):
        if override.strip():
            state["password_overrides"][tgt] = override.strip()
        else:
            state["password_overrides"].pop(tgt, None)
        save_state(state)
        st.success("Saved.")
        st.rerun()

    with st.expander("Show generated passwords (share with players)"):
        rows = [{"Player": p, "Initials": compute_initials(p), "Password": expected_password(state, p)} for p in state["players"]]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    st.divider()
    export = json.dumps(state, indent=2).encode("utf-8")
    st.download_button("Download backup JSON", data=export, file_name="tipping_export.json", mime="application/json")

import pandas as pd
import altair as alt
import streamlit as st

# -----------------------------
