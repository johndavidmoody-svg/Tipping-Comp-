import json
from datetime import datetime, date, time
from zoneinfo import ZoneInfo

import pandas as pd
import altair as alt
import streamlit as st

# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="Tipping Comp", page_icon="🏉", layout="wide")

TZ = ZoneInfo("Pacific/Auckland")
STORE_FILE = "tipping.json"

DEFAULT_SETTINGS = {
    "perfect_round_bonus": 0,  # optional bonus points for a perfect round
}

DEFAULT_PLAYERS = [
    "Player 1", "Player 2", "Player 3", "Player 4", "Player 5",
    "Player 6", "Player 7", "Player 8", "Player 9", "Player 10",
    "Player 11", "Player 12", "Player 13", "Player 14", "Player 15",
]

# Optional Admin PIN from Streamlit secrets (Streamlit Cloud -> App -> Settings -> Secrets)
ADMIN_PIN = ""
try:
    ADMIN_PIN = str(st.secrets.get("ADMIN_PIN", "")).strip()
except Exception:
    ADMIN_PIN = ""

# -----------------------------
# Styling (simple + clean)
# -----------------------------
st.markdown(
    """
<style>
:root{
  --card: rgba(255,255,255,0.04);
  --border: rgba(255,255,255,0.12);
  --muted: rgba(255,255,255,0.70);
}
.block-container{ padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1200px;}
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
.small{ color: var(--muted); font-size: .90rem; }
.stButton>button{ border-radius: 12px; font-weight: 650; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# Helpers
# -----------------------------
def now_nz() -> datetime:
    return datetime.now(TZ)

def iso_from_date_time(d: date, t: time) -> str:
    dt = datetime.combine(d, t).replace(tzinfo=TZ)
    return dt.isoformat()

def parse_iso(iso_str: str) -> datetime | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None

def compute_initials(name: str) -> str:
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return ""
    # initials from first letters of each word, max 3 chars
    ini = "".join([p[0] for p in parts]).upper()
    return ini[:3]

def expected_password(state: dict, player: str) -> str:
    # Allow optional override in admin
    overrides = state.get("password_overrides", {})
    if isinstance(overrides, dict) and player in overrides and overrides[player]:
        return str(overrides[player]).strip()
    return compute_initials(player)

def round_is_locked(round_obj: dict) -> bool:
    close_iso = round_obj.get("close_time", "")
    close_dt = parse_iso(close_iso)
    if close_dt is None:
        return False
    return now_nz() >= close_dt

def round_multiplier(round_obj: dict) -> float:
    try:
        return float(round_obj.get("multiplier", 1.0))
    except Exception:
        return 1.0

def safe_float(x, default=1.0):
    try:
        return float(x)
    except Exception:
        return default

# -----------------------------
# Storage model (V2)
# -----------------------------
# state = {
#   "players": [...],
#   "settings": {"perfect_round_bonus": 0},
#   "password_overrides": { "Some Name": "custom" },  # optional
#   "rounds": {
#     "Round 1": {
#        "close_time": "2026-05-27T19:00:00+12:00" (optional),
#        "multiplier": 1.0,
#        "games": [
#           {"id":"R1G1","home":"A","away":"B","points":1}
#        ],
#        "results": {"R1G1":"home"|"away"|None},
#        "tips": { "Player": {"R1G1":"home"} }
#     }
#   }
# }

def load_state() -> dict:
    try:
        with open(STORE_FILE, "r") as f:
            state = json.load(f)
            if not isinstance(state, dict):
                state = {}
    except Exception:
        state = {}

    state.setdefault("players", DEFAULT_PLAYERS.copy())
    if not isinstance(state["players"], list):
        state["players"] = DEFAULT_PLAYERS.copy()

    state.setdefault("settings", DEFAULT_SETTINGS.copy())
    if not isinstance(state["settings"], dict):
        state["settings"] = DEFAULT_SETTINGS.copy()
    for k, v in DEFAULT_SETTINGS.items():
        state["settings"].setdefault(k, v)

    state.setdefault("password_overrides", {})
    if not isinstance(state["password_overrides"], dict):
        state["password_overrides"] = {}

    state.setdefault("rounds", {})
    if not isinstance(state["rounds"], dict):
        state["rounds"] = {}

    # Migration / normalization
    for rname, r in list(state["rounds"].items()):
        if not isinstance(r, dict):
            state["rounds"][rname] = {"close_time": "", "multiplier": 1.0, "games": [], "results": {}, "tips": {}}
            r = state["rounds"][rname]

        r.setdefault("close_time", "")
        r.setdefault("multiplier", 1.0)
        r.setdefault("games", [])
        r.setdefault("results", {})
        r.setdefault("tips", {})

        if not isinstance(r["games"], list):
            r["games"] = []
        if not isinstance(r["results"], dict):
            r["results"] = {}
        if not isinstance(r["tips"], dict):
            r["tips"] = {}

        fixed_games = []
        for i, g in enumerate(r["games"]):
            if not isinstance(g, dict):
                continue
            gid = g.get("id") or f"{rname.replace(' ', '')}G{i+1}"
            home = str(g.get("home", "")).strip()
            away = str(g.get("away", "")).strip()
            pts = g.get("points", 1)
            try:
                pts = int(pts)
            except Exception:
                pts = 1
            fixed_games.append({"id": gid, "home": home, "away": away, "points": pts})
            r["results"].setdefault(gid, None)
        r["games"] = fixed_games

        # Ensure each player has a tips dict
        for p in state["players"]:
            r["tips"].setdefault(p, {})
            if not isinstance(r["tips"][p], dict):
                r["tips"][p] = {}

    return state

def save_state(state: dict) -> None:
    with open(STORE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# -----------------------------
# Scoring
# -----------------------------
def calc_scores(state: dict):
    players = state["players"]
    bonus = int(state["settings"].get("perfect_round_bonus", 0))

    totals = {p: 0.0 for p in players}
    correct = {p: 0 for p in players}
    decided = {p: 0 for p in players}
    perfect_rounds = {p: 0 for p in players}
    per_round_points = {p: {} for p in players}

    for rname, r in state["rounds"].items():
        mult = round_multiplier(r)
        games = r.get("games", [])
        results = r.get("results", {})
        tips = r.get("tips", {})

        decided_games = [g for g in games if results.get(g["id"]) in ("home", "away")]
        n_decided = len(decided_games)

        for p in players:
            p_tips = tips.get(p, {})
            round_points = 0.0
            round_correct = 0
            round_decided = 0

            for g in decided_games:
                gid = g["id"]
                res = results.get(gid)
                pick = p_tips.get(gid)

                if res in ("home", "away"):
                    round_decided += 1
                    decided[p] += 1
                    if pick == res:
                        round_correct += 1
                        correct[p] += 1
                        # Points per game are set on the game
                        pts = int(g.get("points", 1))
                        round_points += pts * mult

            # Perfect round bonus (also affected by multiplier)
            if n_decided > 0 and round_correct == n_decided:
                perfect_rounds[p] += 1
                if bonus > 0:
                    round_points += bonus * mult

            totals[p] += round_points
            per_round_points[p][rname] = round_points

    return totals, correct, decided, perfect_rounds, per_round_points

def accuracy_pct(corr: int, dec: int) -> float:
    return (corr / dec * 100.0) if dec else 0.0

# -----------------------------
# App state
# -----------------------------
state = load_state()
players = state["players"]

if "auth_player" not in st.session_state:
    st.session_state.auth_player = None

# -----------------------------
# Sidebar: Login + Nav
# -----------------------------
with st.sidebar:
    st.markdown("### 🏉 Tipping Comp")
    st.markdown('<div class="small">Log in, enter tips, and track the leaderboard.</div>', unsafe_allow_html=True)
    st.write("")

    if st.session_state.auth_player:
        st.success(f"Logged in as: {st.session_state.auth_player}")
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

    tab = st.radio(
        "Go to",
        ["🏆 Leaderboard", "📝 Enter Tips", "✅ Admin", "📊 Stats"],
        index=0,
    )

    st.divider()
    round_names = list(state["rounds"].keys())
    selected_round = st.selectbox("Round", round_names) if round_names else None

    st.divider()
    st.markdown("### ⚙️ Scoring")
    state["settings"]["perfect_round_bonus"] = st.number_input(
        "Perfect round bonus (optional)",
        min_value=0,
        max_value=50,
        value=int(state["settings"].get("perfect_round_bonus", 0)),
        step=1,
        help="Added if a player gets every decided game in a round correct.",
    )
    save_state(state)

# -----------------------------
# Compute standings
# -----------------------------
totals, correct, decided, perfect_rounds, per_round_points = calc_scores(state)

leader_df = pd.DataFrame({
    "Player": players,
    "Points": [round(totals[p], 1) for p in players],
    "Correct": [correct[p] for p in players],
    "Decided": [decided[p] for p in players],
    "Accuracy %": [round(accuracy_pct(correct[p], decided[p]), 1) for p in players],
    "Perfect Rounds": [perfect_rounds[p] for p in players],
})
leader_df = leader_df.sort_values(["Points", "Accuracy %", "Correct"], ascending=[False, False, False]).reset_index(drop=True)
leader_df.index = leader_df.index + 1

# -----------------------------
# Header KPIs
# -----------------------------
st.markdown("## 🏉 Tipping Comp")

k1, k2, k3, k4 = st.columns(4)

current_leader = leader_df.iloc[0]["Player"] if len(leader_df) else "-"
leader_points = leader_df.iloc[0]["Points"] if len(leader_df) else 0
n_rounds = len(state["rounds"])

total_decided_games = 0
for r in state["rounds"].values():
    total_decided_games += sum(1 for v in r.get("results", {}).values() if v in ("home", "away"))

with k1:
    st.markdown(
        f"""
        <div class="card">
          <div class="kpi-title">Current leader</div>
          <div class="kpi-value">{current_leader}</div>
          <div class="kpi-sub">{leader_points} points</div>
        </div>
        """, unsafe_allow_html=True
    )
with k2:
    st.markdown(
        f"""
        <div class="card">
          <div class="kpi-title">Rounds</div>
          <div class="kpi-value">{n_rounds}</div>
          <div class="kpi-sub">Created so far</div>
        </div>
        """, unsafe_allow_html=True
    )
with k3:
    st.markdown(
        f"""
        <div class="card">
          <div class="kpi-title">Decided games</div>
          <div class="kpi-value">{total_decided_games}</div>
          <div class="kpi-sub">Results entered</div>
        </div>
        """, unsafe_allow_html=True
    )
with k4:
    st.markdown(
        f"""
        <div class="card">
          <div class="kpi-title">Players</div>
          <div class="kpi-value">{len(players)}</div>
          <div class="kpi-sub">In the comp</div>
        </div>
        """, unsafe_allow_html=True
    )

st.write("")

# -----------------------------
# Pages
# -----------------------------
if tab == "🏆 Leaderboard":
    st.markdown("### 🏆 Leaderboard")
    st.dataframe(leader_df, use_container_width=True, height=520)

    st.markdown("### 📅 Round-by-round points")
    rnames = list(state["rounds"].keys())
    if not rnames:
        st.info("No rounds yet.")
    else:
        rp = pd.DataFrame({"Player": players})
        for rn in rnames:
            rp[rn] = [round(per_round_points[p].get(rn, 0.0), 1) for p in players]
        rp["Total"] = rp[rnames].sum(axis=1).round(1)
        rp = rp.sort_values("Total", ascending=False).reset_index(drop=True)
        st.dataframe(rp, use_container_width=True)

    if selected_round and selected_round in state["rounds"]:
        r = state["rounds"][selected_round]
        st.markdown(f"### 🔎 {selected_round} — Games & Results")
        close_dt = parse_iso(r.get("close_time", ""))
        mult = round_multiplier(r)
        st.caption(f"Close-off: {close_dt.strftime('%a %d %b %I:%M%p') if close_dt else 'Not set'} • Multiplier: {mult}x")

        if not r["games"]:
            st.info("No games in this round yet.")
        else:
            rows = []
            for g in r["games"]:
                gid = g["id"]
                res = r["results"].get(gid)
                res_team = g["home"] if res == "home" else g["away"] if res == "away" else "—"
                rows.append({
                    "Game": f"{g['home']} vs {g['away']}",
                    "Points": int(g.get("points", 1)),
                    "Result": res_team,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

            with st.expander("Show picks matrix (compact)"):
                matrix = pd.DataFrame({"Player": players})
                for g in r["games"]:
                    gid = g["id"]
                    col = f"{g['home']} vs {g['away']}"
                    def fmt_pick(p):
                        pick = r["tips"].get(p, {}).get(gid)
                        if pick == "home":
                            return g["home"]
                        if pick == "away":
                            return g["away"]
                        return ""
                    matrix[col] = [fmt_pick(p) for p in players]
                st.dataframe(matrix, use_container_width=True)

elif tab == "📝 Enter Tips":
    st.markdown("### 📝 Enter Tips")

    if not st.session_state.auth_player:
        st.warning("Please log in in the sidebar first.")
        st.stop()

    if not state["rounds"]:
        st.warning("No rounds exist yet. Ask admin to create Round 1.")
        st.stop()

    rnames = list(state["rounds"].keys())
    rn = st.selectbox("Round", rnames, index=rnames.index(selected_round) if selected_round in rnames else 0)
    r = state["rounds"][rn]

    locked = round_is_locked(r)
    close_dt = parse_iso(r.get("close_time", ""))
    mult = round_multiplier(r)

    st.caption(
        f"Round close-off: {close_dt.strftime('%a %d %b %I:%M%p') if close_dt else 'Not set'} • "
        f"Locked: {'Yes' if locked else 'No'} • Multiplier: {mult}x"
    )

    games = r.get("games", [])
    if not games:
        st.info("No games in this round yet.")
        st.stop()

    st.markdown('<div class="small">Pick the winner for each game. When the round closes, tips lock.</div>', unsafe_allow_html=True)
    st.write("")

    player = st.session_state.auth_player

    with st.form("tips_form"):
        updated = {}
        for g in games:
            gid = g["id"]
            current = r["tips"].get(player, {}).get(gid, "")

            options = ["", "home", "away"]
            display = {"": "— no pick —", "home": g["home"], "away": g["away"]}

            idx = options.index(current) if current in options else 0
            choice = st.selectbox(
                f"{g['home']} vs {g['away']}  •  ({int(g.get('points', 1))} pts)",
                options=options,
                index=idx,
                format_func=lambda x: display[x],
                disabled=locked,
                key=f"tip_{rn}_{player}_{gid}",
            )
            updated[gid] = choice

        submitted = st.form_submit_button("Save tips", disabled=locked)

    if submitted:
        r["tips"].setdefault(player, {})
        for gid, pick in updated.items():
            if pick:
                r["tips"][player][gid] = pick
            else:
                r["tips"][player].pop(gid, None)
        save_state(state)
        st.success("Tips saved.")
        st.rerun()

elif tab == "✅ Admin":
    st.markdown("### ✅ Admin")

    # Admin PIN gate (optional)
    if ADMIN_PIN:
        pin = st.text_input("Admin PIN", type="password")
        if pin.strip() != ADMIN_PIN:
            st.warning("Enter the correct Admin PIN to use admin tools.")
            st.stop()

    left, right = st.columns([2, 1])

    with left:
        st.markdown("#### Rounds")

        new_round = st.text_input("Round name", placeholder="e.g., Round 1")
        close_date = st.date_input("Close-off date", value=date.today())
        close_time = st.time_input("Close-off time", value=time(18, 0))
        mult = st.selectbox("Round multiplier", [1.0, 1.5, 2.0], index=0)

        if st.button("Add / Update round"):
            rn = new_round.strip()
            if rn:
                state["rounds"].setdefault(rn, {"close_time": "", "multiplier": 1.0, "games": [], "results": {}, "tips": {}})
                r = state["rounds"][rn]
                r["close_time"] = iso_from_date_time(close_date, close_time)
                r["multiplier"] = float(mult)
                # ensure tips dict for all players
                for p in players:
                    r.setdefault("tips", {})
                    r["tips"].setdefault(p, {})
                save_state(state)
                st.success(f"Saved {rn}")
                st.rerun()
            else:
                st.warning("Please enter a round name.")

        st.write("")
        if not state["rounds"]:
            st.info("Create a round to begin.")
        else:
            rn = st.selectbox("Edit round", list(state["rounds"].keys()), key="admin_round_edit")
            r = state["rounds"][rn]
            st.caption(f"Close-off: {parse_iso(r.get('close_time','')).strftime('%a %d %b %I:%M%p') if parse_iso(r.get('close_time','')) else 'Not set'} • Multiplier: {round_multiplier(r)}x")

            st.markdown("#### Games (points set per game)")

            g1, g2, g3 = st.columns([1, 1, 1])
            with g1:
                home = st.text_input("Home team", key="home_team").strip()
            with g2:
                away = st.text_input("Away team", key="away_team").strip()
            with g3:
                pts = st.number_input("Points for this game", min_value=1, max_value=20, value=1, step=1)

            if st.button("Add game"):
                if home and away:
                    gid = f"{rn.replace(' ', '')}G{len(r['games'])+1}"
                    r["games"].append({"id": gid, "home": home, "away": away, "points": int(pts)})
                    r["results"].setdefault(gid, None)
                    for p in players:
                        r["tips"].setdefault(p, {})
                    save_state(state)
                    st.success("Game added.")
                    st.rerun()
                else:
                    st.warning("Please enter both Home and Away team names.")

            st.write("")
            if not r["games"]:
                st.info("No games yet.")
            else:
                for g in r["games"]:
                    c1, c2, c3 = st.columns([4, 1, 1])
                    with c1:
                        st.write(f"**{g['home']} vs {g['away']}**")
                        st.caption(f"ID: {g['id']}")
                    with c2:
                        st.write(f"{int(g.get('points',1))} pts")
                    with c3:
                        if st.button("🗑️", key=f"del_{rn}_{g['id']}"):
                            gid = g["id"]
                            r["games"] = [x for x in r["games"] if x["id"] != gid]
                            r["results"].pop(gid, None)
                            for p in players:
                                r["tips"].get(p, {}).pop(gid, None)
                            save_state(state)
                            st.rerun()

            st.divider()
            st.markdown("#### Enter results")
            with st.form("results_form"):
                updates = {}
                for g in r["games"]:
                    gid = g["id"]
                    current = r["results"].get(gid)
                    options = [None, "home", "away"]
                    label_map = {None: "— no result —", "home": g["home"], "away": g["away"]}
                    idx = options.index(current) if current in options else 0
                    choice = st.selectbox(
                        f"Result: {g['home']} vs {g['away']}",
                        options=options,
                        index=idx,
                        format_func=lambda x: label_map[x],
                        key=f"res_{rn}_{gid}",
                    )
                    updates[gid] = choice

                save_btn = st.form_submit_button("Save results")

            if save_btn:
                for gid, res in updates.items():
                    r["results"][gid] = res
                save_state(state)
                st.success("Results saved.")
                st.rerun()

    with right:
        st.markdown("#### Players & Passwords")
        st.markdown('<div class="small">Default password = initials (e.g., “John Moody” → JM). You can override any password below.</div>', unsafe_allow_html=True)

        new_player = st.text_input("Add player", placeholder="Name").strip()
        if st.button("Add player"):
            if new_player and new_player not in state["players"]:
                state["players"].append(new_player)
                for rn2 in state["rounds"]:
                    state["rounds"][rn2]["tips"].setdefault(new_player, {})
                save_state(state)
                st.success("Player added.")
                st.rerun()

        if state["players"]:
            remove_player = st.selectbox("Remove player", [""] + state["players"])
            if remove_player and st.button("Remove selected player"):
                state["players"] = [p for p in state["players"] if p != remove_player]
                for rn2 in state["rounds"]:
                    state["rounds"][rn2]["tips"].pop(remove_player, None)
                state["password_overrides"].pop(remove_player, None)
                save_state(state)
                st.success("Player removed.")
                st.rerun()

        st.write("")
        st.markdown("##### Password overrides (optional)")
        target = st.selectbox("Choose player", state["players"])
        override = st.text_input("Override password (leave blank to use initials)", value=str(state["password_overrides"].get(target, "")))
        if st.button("Save override"):
            if override.strip():
                state["password_overrides"][target] = override.strip()
            else:
                state["password_overrides"].pop(target, None)
            save_state(state)
            st.success("Saved.")
            st.rerun()

        st.write("")
        with st.expander("Show generated passwords (share with players)"):
            rows = []
            for p in state["players"]:
                rows.append({"Player": p, "Initials": compute_initials(p), "Password": expected_password(state, p)})
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

    st.divider()
    st.markdown("#### Export / Reset")
    export = json.dumps(state, indent=2).encode("utf-8")
    st.download_button("Download all data (JSON backup)", data=export, file_name="tipping_export.json", mime="application/json")

    if st.button("Reset ALL data (danger)", type="secondary"):
        state = {"players": DEFAULT_PLAYERS.copy(), "settings": DEFAULT_SETTINGS.copy(), "password_overrides": {}, "rounds": {}}
        save_state(state)
        st.success("Reset completed.")
        st.rerun()

elif tab == "📊 Stats":
    st.markdown("### 📊 Stats Dashboard")

    if not state["rounds"]:
        st.info("No rounds yet.")
        st.stop()

    rnames = list(state["rounds"].keys())

    # Build time series
    chart_rows = []
    for p in players:
        running = 0.0
        for rn in rnames:
            pts = float(per_round_points[p].get(rn, 0.0))
            running += pts
            chart_rows.append({"Player": p, "Round": rn, "Round Points": pts, "Total Points": running})
    chart_df = pd.DataFrame(chart_rows)

    c1, c2 = st.columns([2, 1])

    with c1:
        st.markdown("#### Total points over rounds")
        line = alt.Chart(chart_df).mark_line(point=True).encode(
            x=alt.X("Round:N", sort=rnames),
            y=alt.Y("Total Points:Q"),
            color=alt.Color("Player:N"),
            tooltip=["Player", "Round", "Round Points", "Total Points"],
        ).properties(height=360)
        st.altair_chart(line, use_container_width=True)

    with c2:
        st.markdown("#### Accuracy vs points")
        scatter_df = leader_df.copy()
        scatter = alt.Chart(scatter_df).mark_circle(size=140).encode(
            x=alt.X("Accuracy %:Q", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("Points:Q"),
            color=alt.Color("Player:N"),
            tooltip=["Player", "Points", "Accuracy %", "Correct", "Decided", "Perfect Rounds"],
        ).properties(height=360)
        st.altair_chart(scatter, use_container_width=True)

    st.divider()
    st.markdown("#### Round score table")
    rp = pd.DataFrame({"Player": players})
    for rn in rnames:
        rp[rn] = [round(float(per_round_points[p].get(rn, 0.0)), 1) for p in players]
    rp["Total"] = rp[rnames].sum(axis=1).round(1)
    rp = rp.sort_values("Total", ascending=False).reset_index(drop=True)
    st.dataframe(rp, use_container_width=True)

    st.markdown('<div class="small">Tips lock at the round close-off time (not per game). Admin sets game points and the round multiplier.</div>', unsafe_allow_html=True) games. Once kickoff has passed (NZ time), picks disable automatically.</div>', unsafe_allow_html=True)