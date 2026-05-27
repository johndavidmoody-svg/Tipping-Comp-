import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import altair as alt
import streamlit as st

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="Tipping Comp",
    page_icon="🏉",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------
# Styling (simple, pro look)
# -----------------------------
st.markdown(
    """
<style>
:root {
  --card: rgba(255,255,255,0.04);
  --border: rgba(255,255,255,0.10);
  --muted: rgba(255,255,255,0.65);
}

.block-container { padding-top: 1.15rem; padding-bottom: 2rem; max-width: 1200px; }
[data-testid="stSidebar"] { border-right: 1px solid var(--border); }
[data-testid="stHeader"] { background: rgba(0,0,0,0); }

.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 14px 14px 10px 14px;
  box-shadow: 0 10px 22px rgba(0,0,0,0.18);
}
.kpi-title { color: var(--muted); font-size: 0.85rem; margin-bottom: 6px; }
.kpi-value { font-size: 1.6rem; font-weight: 800; line-height: 1.05; }
.kpi-sub { color: var(--muted); font-size: 0.85rem; margin-top: 6px; }

.small { color: var(--muted); font-size: 0.88rem; }
.stButton>button { border-radius: 12px; font-weight: 650; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# Constants / defaults
# -----------------------------
STORE_FILE = "tipping.json"
TZ = ZoneInfo("Pacific/Auckland")  # NZ time

DEFAULT_PLAYERS = [
    "Player 1", "Player 2", "Player 3", "Player 4", "Player 5",
    "Player 6", "Player 7", "Player 8", "Player 9", "Player 10",
    "Player 11", "Player 12", "Player 13", "Player 14", "Player 15",
]

DEFAULT_SETTINGS = {
    "points_per_correct": 1,
    "perfect_round_bonus": 0,  # set to e.g. 2 if you want a bonus
}

# Optional admin PIN (set this in Streamlit Cloud -> App -> Settings -> Secrets)
# Streamlit secrets are accessed via st.secrets (docs). [2](https://docs.streamlit.io/develop/api-reference/connections/st.secrets)
ADMIN_PIN = ""
try:
    ADMIN_PIN = str(st.secrets.get("ADMIN_PIN", "")).strip()
except Exception:
    ADMIN_PIN = ""

# -----------------------------
# Data model
# -----------------------------
# state = {
#   "players": [..],
#   "settings": {points_per_correct, perfect_round_bonus},
#   "rounds": {
#      "Round 1": {
#         "games": [
#             {"id": "R1G1", "home": "Team A", "away": "Team B", "kickoff": "2026-05-27T19:00:00+12:00"}
#         ],
#         "results": {"R1G1": "home"|"away"|None},
#         "tips": {
#            "Player 1": {"R1G1": "home"},
#            ...
#         }
#      }
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

    # ensure top-level keys
    state.setdefault("players", DEFAULT_PLAYERS.copy())
    if not isinstance(state["players"], list):
        state["players"] = DEFAULT_PLAYERS.copy()

    state.setdefault("settings", DEFAULT_SETTINGS.copy())
    if not isinstance(state["settings"], dict):
        state["settings"] = DEFAULT_SETTINGS.copy()
    for k, v in DEFAULT_SETTINGS.items():
        state["settings"].setdefault(k, v)

    state.setdefault("rounds", {})
    if not isinstance(state["rounds"], dict):
        state["rounds"] = {}

    # ensure each round has correct keys
    for rname, r in list(state["rounds"].items()):
        if not isinstance(r, dict):
            state["rounds"][rname] = {"games": [], "results": {}, "tips": {}}
            continue
        r.setdefault("games", [])
        r.setdefault("results", {})
        r.setdefault("tips", {})
        if not isinstance(r["games"], list):
            r["games"] = []
        if not isinstance(r["results"], dict):
            r["results"] = {}
        if not isinstance(r["tips"], dict):
            r["tips"] = {}

        # ensure each game has id/home/away/kickoff
        fixed_games = []
        for i, g in enumerate(r["games"]):
            if not isinstance(g, dict):
                continue
            gid = g.get("id") or f"{rname.replace(' ', '')}G{i+1}"
            home = (g.get("home") or "").strip()
            away = (g.get("away") or "").strip()
            kickoff = (g.get("kickoff") or "").strip()  # ISO string optional
            fixed_games.append({"id": gid, "home": home, "away": away, "kickoff": kickoff})
            r["results"].setdefault(gid, None)
        r["games"] = fixed_games

        # ensure tips exist for all players
        for p in state["players"]:
            r["tips"].setdefault(p, {})
            if not isinstance(r["tips"][p], dict):
                r["tips"][p] = {}

    return state


def save_state(state: dict) -> None:
    with open(STORE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def parse_kickoff(iso_str: str):
    if not iso_str:
        return None
    try:
        # datetime.fromisoformat handles "+12:00"
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None


def is_locked(game: dict) -> bool:
    ko = parse_kickoff(game.get("kickoff", ""))
    if ko is None:
        return False
    return datetime.now(TZ) >= ko


def game_label(game: dict) -> str:
    ko = parse_kickoff(game.get("kickoff", ""))
    ko_txt = ko.strftime("%a %d %b %I:%M%p") if ko else "No kickoff set"
    return f"{game['home']} vs {game['away']}  •  {ko_txt}"


def calc_scores(state: dict):
    players = state["players"]
    ppc = int(state["settings"].get("points_per_correct", 1))
    bonus = int(state["settings"].get("perfect_round_bonus", 0))

    # outputs
    totals = {p: 0 for p in players}
    correct = {p: 0 for p in players}
    decided = {p: 0 for p in players}
    perfect_rounds = {p: 0 for p in players}
    per_round_points = {p: {} for p in players}

    for rname, r in state["rounds"].items():
        games = r.get("games", [])
        results = r.get("results", {})
        tips = r.get("tips", {})

        # count decided games in this round
        decided_games = [g for g in games if results.get(g["id"]) in ("home", "away")]
        n_decided = len(decided_games)

        for p in players:
            p_tips = tips.get(p, {})
            round_points = 0
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
                        round_points += ppc

            # perfect round bonus
            if n_decided > 0 and round_correct == n_decided:
                if bonus > 0:
                    round_points += bonus
                perfect_rounds[p] += 1

            totals[p] += round_points
            per_round_points[p][rname] = round_points

    return totals, correct, decided, perfect_rounds, per_round_points


def accuracy_pct(corr: int, dec: int) -> float:
    return (corr / dec * 100.0) if dec else 0.0


# -----------------------------
# Load / init state
# -----------------------------
state = load_state()
players = state["players"]

# -----------------------------
# Sidebar navigation
# -----------------------------
with st.sidebar:
    st.markdown("### 🏉 Tipping Comp")
    st.markdown('<div class="small">Manage rounds, enter tips, track leaderboard and stats.</div>', unsafe_allow_html=True)
    st.write("")

    tab = st.radio(
        "Go to",
        ["🏆 Leaderboard", "📝 Enter Tips", "✅ Enter Results (Admin)", "📊 Stats"],
        index=0,
    )

    st.divider()

    # Quick round selector
    round_names = list(state["rounds"].keys())
    if not round_names:
        st.info("No rounds yet. Create one in Admin.")
        selected_round = None
    else:
        selected_round = st.selectbox("Round", round_names, index=max(0, len(round_names) - 1))

    st.divider()
    st.markdown("### ⚙️ Settings")
    state["settings"]["points_per_correct"] = st.number_input(
        "Points per correct tip",
        min_value=1,
        max_value=10,
        value=int(state["settings"].get("points_per_correct", 1)),
        step=1,
    )
    state["settings"]["perfect_round_bonus"] = st.number_input(
        "Perfect round bonus",
        min_value=0,
        max_value=20,
        value=int(state["settings"].get("perfect_round_bonus", 0)),
        step=1,
        help="Extra points if a player gets every decided game in a round correct.",
    )
    save_state(state)

# -----------------------------
# Compute standings
# -----------------------------
totals, correct, decided, perfect_rounds, per_round_points = calc_scores(state)

leader_df = pd.DataFrame({
    "Player": players,
    "Points": [totals[p] for p in players],
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
leader_points = int(leader_df.iloc[0]["Points"]) if len(leader_df) else 0
n_rounds = len(state["rounds"])

# games decided total (approx)
total_decided_games = 0
for r in state["rounds"].values():
    total_decided_games += sum(1 for v in r.get("results", {}).values() if v in ("home", "away"))

with k1:
    st.markdown(
        f"""
        <div class="card">
          <div class="kpi-title">Current leader</div>
          <div class="kpi-value">{current_leader}</div>
          <div class="kpi-sub">{leader_points} point(s)</div>
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
          <div class="kpi-sub">With results entered</div>
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
    # build round points table
    rnames = list(state["rounds"].keys())
    if not rnames:
        st.info("No rounds yet.")
    else:
        rp = pd.DataFrame({"Player": players})
        for rn in rnames:
            rp[rn] = [per_round_points[p].get(rn, 0) for p in players]
        rp["Total"] = rp[rnames].sum(axis=1)
        rp = rp.sort_values("Total", ascending=False).reset_index(drop=True)
        st.dataframe(rp, use_container_width=True)

    if selected_round and selected_round in state["rounds"]:
        st.markdown(f"### 🔎 {selected_round} — Picks & Results")
        r = state["rounds"][selected_round]
        games = r.get("games", [])
        results = r.get("results", {})
        tips = r.get("tips", {})

        if not games:
            st.info("No games in this round yet. Add games in Admin.")
        else:
            # show games table
            rows = []
            for g in games:
                gid = g["id"]
                res = results.get(gid)
                res_team = g["home"] if res == "home" else g["away"] if res == "away" else ""
                rows.append({
                    "Game": f"{g['home']} vs {g['away']}",
                    "Kickoff": (parse_kickoff(g.get("kickoff","")).strftime("%a %d %b %I:%M%p") if parse_kickoff(g.get("kickoff","")) else ""),
                    "Result": res_team if res_team else "—",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

            # optional: player picks matrix (compact)
            with st.expander("Show picks matrix (compact)"):
                matrix = pd.DataFrame({"Player": players})
                for g in games:
                    gid = g["id"]
                    col = f"{g['home']} vs {g['away']}"
                    def fmt_pick(p):
                        pick = tips.get(p, {}).get(gid)
                        if pick == "home":
                            return g["home"]
                        if pick == "away":
                            return g["away"]
                        return ""
                    matrix[col] = [fmt_pick(p) for p in players]
                st.dataframe(matrix, use_container_width=True)

elif tab == "📝 Enter Tips":
    st.markdown("### 📝 Enter Tips")
    if not state["rounds"]:
        st.warning("No rounds exist yet. Go to Admin and create Round 1.")
    else:
        # Round selection
        rnames = list(state["rounds"].keys())
        rn = st.selectbox("Round", rnames, index=rnames.index(selected_round) if selected_round in rnames else 0)

        # Player selection
        p = st.selectbox("Your name", players)

        r = state["rounds"][rn]
        games = r.get("games", [])
        if not games:
            st.info("No games in this round yet. Ask the admin to add them.")
        else:
            st.markdown('<div class="small">Pick the winner for each game. If kickoff time is set and passed, the pick locks.</div>', unsafe_allow_html=True)
            st.write("")

            # tips editor form
            with st.form("tips_form", clear_on_submit=False):
                updated = {}
                for g in games:
                    gid = g["id"]
                    locked = is_locked(g)
                    current = r["tips"].get(p, {}).get(gid, "")

                    options = ["", "home", "away"]
                    display = {
                        "": "— no pick —",
                        "home": g["home"],
                        "away": g["away"],
                    }

                    # map current to index
                    idx = options.index(current) if current in options else 0
                    choice = st.selectbox(
                        game_label(g),
                        options=options,
                        index=idx,
                        format_func=lambda x: display[x],
                        disabled=locked,
                        key=f"tip_{rn}_{p}_{gid}",
                    )
                    updated[gid] = choice

                submitted = st.form_submit_button("Save tips")

            if submitted:
                r["tips"].setdefault(p, {})
                for gid, pick in updated.items():
                    if pick:
                        r["tips"][p][gid] = pick
                    else:
                        # remove empty pick
                        r["tips"][p].pop(gid, None)
                save_state(state)
                st.success("Tips saved.")
                st.rerun()

elif tab == "✅ Enter Results (Admin)":
    st.markdown("### ✅ Enter Results (Admin)")

    # Admin PIN gate (optional)
    if ADMIN_PIN:
        pin = st.text_input("Admin PIN", type="password")
        if pin.strip() != ADMIN_PIN:
            st.warning("Enter the correct Admin PIN to use admin tools.")
            st.stop()

    a1, a2 = st.columns([2, 1])

    with a1:
        st.markdown("#### Rounds & Games")

        # Create a round
        new_round = st.text_input("Create new round", placeholder="e.g., Round 1")
        if st.button("Add round"):
            nr = new_round.strip()
            if nr:
                state["rounds"].setdefault(nr, {"games": [], "results": {}, "tips": {p: {} for p in players}})
                # ensure tips dict for all players
                for p in players:
                    state["rounds"][nr]["tips"].setdefault(p, {})
                save_state(state)
                st.success(f"Added {nr}")
                st.rerun()

        st.write("")
        if not state["rounds"]:
            st.info("Create a round to begin.")
            st.stop()

        rnames = list(state["rounds"].keys())
        rn = st.selectbox("Edit round", rnames, index=rnames.index(selected_round) if selected_round in rnames else 0)
        r = state["rounds"][rn]

        st.markdown("##### Add a game")
        g1, g2, g3 = st.columns([1, 1, 1])
        with g1:
            home = st.text_input("Home team", key="home_team").strip()
        with g2:
            away = st.text_input("Away team", key="away_team").strip()
        with g3:
            kickoff = st.text_input("Kickoff (ISO, optional)", placeholder="2026-05-27T19:00:00+12:00", key="kickoff_iso").strip()

        if st.button("Add game"):
            if home and away:
                gid = f"{rn.replace(' ', '')}G{len(r['games'])+1}"
                r["games"].append({"id": gid, "home": home, "away": away, "kickoff": kickoff})
                r["results"].setdefault(gid, None)
                for p in players:
                    r["tips"].setdefault(p, {})
                save_state(state)
                st.success("Game added.")
                st.rerun()
            else:
                st.warning("Please enter both Home and Away team names.")

        st.write("")
        st.markdown("##### Existing games")
        if not r["games"]:
            st.info("No games yet.")
        else:
            # allow delete
            for g in r["games"]:
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                with c1:
                    st.write(f"**{g['home']} vs {g['away']}**")
                    st.caption(f"ID: {g['id']}")
                with c2:
                    ko = parse_kickoff(g.get("kickoff", ""))
                    st.write(ko.strftime("%a %d %b %I:%M%p") if ko else "No kickoff")
                with c3:
                    st.write("Locked" if is_locked(g) else "Open")
                with c4:
                    if st.button("🗑️", key=f"del_{rn}_{g['id']}"):
                        # remove game and related tips/results
                        gid = g["id"]
                        r["games"] = [x for x in r["games"] if x["id"] != gid]
                        r["results"].pop(gid, None)
                        for p in players:
                            r["tips"].get(p, {}).pop(gid, None)
                        save_state(state)
                        st.rerun()

    with a2:
        st.markdown("#### Players")
        st.markdown('<div class="small">Add/remove players (defaults to 15). Removing a player deletes their tips.</div>', unsafe_allow_html=True)

        new_player = st.text_input("Add player", placeholder="Name").strip()
        if st.button("Add player"):
            if new_player and new_player not in state["players"]:
                state["players"].append(new_player)
                # ensure tips dict exists for each round
                for rn2 in state["rounds"]:
                    state["rounds"][rn2]["tips"].setdefault(new_player, {})
                save_state(state)
                st.success("Player added.")
                st.rerun()

        if state["players"]:
            remove_player = st.selectbox("Remove player", [""] + state["players"])
            if remove_player and st.button("Remove selected player"):
                state["players"] = [p for p in state["players"] if p != remove_player]
                # remove tips
                for rn2 in state["rounds"]:
                    state["rounds"][rn2]["tips"].pop(remove_player, None)
                save_state(state)
                st.success("Player removed.")
                st.rerun()

    st.divider()
    st.markdown("#### Enter results")
    if not state["rounds"]:
        st.info("No rounds.")
    else:
        rn = st.selectbox("Round for results", list(state["rounds"].keys()), key="results_round")
        r = state["rounds"][rn]
        if not r["games"]:
            st.info("No games in this round.")
        else:
            with st.form("results_form"):
                updates = {}
                for g in r["games"]:
                    gid = g["id"]
                    current = r["results"].get(gid)
                    options = [None, "home", "away"]
                    label_map = {
                        None: "— no result —",
                        "home": g["home"],
                        "away": g["away"],
                    }
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

    st.divider()
    st.markdown("#### Export / Reset")
    export = json.dumps(state, indent=2).encode("utf-8")
    st.download_button("Download all data (JSON)", data=export, file_name="tipping_export.json", mime="application/json")

    if st.button("Reset ALL data (danger)", type="secondary"):
        state = {"players": DEFAULT_PLAYERS.copy(), "settings": DEFAULT_SETTINGS.copy(), "rounds": {}}
        save_state(state)
        st.success("Reset completed.")
        st.rerun()

elif tab == "📊 Stats":
    st.markdown("### 📊 Stats Dashboard")

    if not state["rounds"]:
        st.info("No rounds yet.")
        st.stop()

    # Build round list in stable order
    rnames = list(state["rounds"].keys())

    # Points over rounds chart
    chart_df = []
    for p in players:
        running = 0
        for rn in rnames:
            pts = per_round_points[p].get(rn, 0)
            running += pts
            chart_df.append({"Player": p, "Round": rn, "Round Points": pts, "Total Points": running})
    chart_df = pd.DataFrame(chart_df)

    c1, c2 = st.columns([2, 1])

    with c1:
        st.markdown("#### Total points over rounds")
        line = alt.Chart(chart_df).mark_line(point=True).encode(
            x=alt.X("Round:N", sort=rnames),
            y="Total Points:Q",
            color="Player:N",
            tooltip=["Player", "Round", "Round Points", "Total Points"],
        ).properties(height=360)
        st.altair_chart(line, use_container_width=True)

    with c2:
        st.markdown("#### Accuracy vs points")
        scatter_df = leader_df.copy()
        scatter = alt.Chart(scatter_df).mark_circle(size=140).encode(
            x=alt.X", scale=alt.Scale(domain=[0, 100])),
            y="Points:Q",
            color="Player:N",
            tooltip=["Player", "Points", "Accuracy %", "Correct", "Decided", "Perfect Rounds"],
        ).properties(height=360)
        st.altair_chart(scatter, use_container_width=True)

    st.divider()
    st.markdown("#### Round score table")
    rp = pd.DataFrame({"Player": players})
    for rn in rnames:
        rp[rn] = [per_round_points[p].get(rn, 0) for p in players]
    rp["Total"] = rp[rnames].sum(axis=1)
    rp = rp.sort_values("Total", ascending=False).reset_index(drop=True)

    st.dataframe(rp, use_container_width=True)

    st.markdown('<div class="small">Tip: If you want a “lockout” feature, set kickoff times on games. Once kickoff has passed (NZ time), picks disable automatically.</div>', unsafe_allow_html=True)