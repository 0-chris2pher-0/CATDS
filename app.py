imimport html
import math
import calendar as pycal
from collections import defaultdict
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime, date, timedelta
from streamlit_calendar import calendar
from engine import (
    process_imported_table,
    build_merge_plan,
    geocode_claim_rows,
    compute_openings,
    compute_day_gaps,
    get_busy_intervals,
    day_window,
    make_slot,
    order_openings,
    find_overlap,
    get_recommendations_for_slot,
    export_claims_to_ics,
    is_slot_conflicting,
    batch_geocode_addresses,
    normalize_priority,
    geocode_hotel_address,
    detect_deployment_timezone,
    get_zone,
    parse_wallclock,
    parse_coordinates,
    build_navigation_links,
    US_TIMEZONES,
    ACTIVITY_ONSITE,
    ACTIVITY_VIDEO,
    ACTIVITY_OPTIONS,
    VIDEO_DEFAULT_HRS,
    NOTE_MAX_CHARS,
    is_video,
    clean_text,
    normalize_phone,
    split_12h,
    parse_date_time_12h,
    build_export_table,
    plan_draft_schedule,
    capacity_report,
    best_spot_for_draft,
    get_osrm_route,
    GEO_MANUAL,
    GEO_CONFIRMED,
    GEO_REP_VERIFIED,
    GEO_UNKNOWN,
    GEO_NEEDS_REVIEW,
)

st.set_page_config(page_title="CAT Dynamic Scheduling", page_icon="🌀", layout="wide")

# =====================================================================
# STYLE
# Palette: storm navy for the header and primary actions, blue-gray
# workspace, white work surfaces. Status colors match the map pins:
# red = unscheduled, blue = scheduled, gray = ignored, amber = next up.
# =====================================================================
INK = "#0F1E2E"
STEEL = "#1D4E89"
SLATE = "#52637A"
LINE = "#DCE3EA"
AMBER = "#E8A317"
RED = "#D63E2A"
SCHEDULED_BLUE = "#2F6DB5"
IGNORED_GRAY = "#94A3B8"
ISSUE_ORANGE = "#F07C1B"
DRAFT_BLUE = "#9DB4CC"

# The theme is switched in the app menu (⋮ > Settings), using the two themes
# defined in .streamlit/config.toml. Streamlit restyles its own widgets; this
# CSS restyles the custom pieces (header, stats, cards) to match.
try:
    THEME_MODE = st.context.theme.base or "light"
except Exception:
    THEME_MODE = "light"
CONSOLE = THEME_MODE == "dark"

# Console (dark) palette
C_BG = "#0A0F14"
C_PANEL = "#111A22"
C_LINE = "#1E2A36"
C_TEXT = "#D7E1EA"
C_MUTED = "#7F92A6"
C_SIGNAL = "#3FD0E0"

MONO = "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
SANS = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

.stApp, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp p, .stApp label, .stApp li,
.stApp button, .stApp input, .stApp textarea {{ font-family: {SANS}; }}
.stApp code {{ font-family: {MONO}; }}
[data-testid="stDecoration"] {{ display: none; }}
.block-container {{ padding-top: 2rem; padding-bottom: 4rem; }}

.stApp h3 {{ font-size: 1.15rem; font-weight: 600; letter-spacing: -0.01em; }}
.stApp hr {{ border: none; border-top: 1px solid rgba(128, 140, 155, 0.28); margin: 1.5rem 0 1.25rem; }}
[data-testid="stSidebar"] h2 {{ font-size: 1.05rem; font-weight: 600; }}
[data-testid="stSidebar"] h3 {{ font-size: 0.95rem; font-weight: 600; }}

.stApp .stButton button, .stApp .stDownloadButton button, .stApp .stLinkButton a {{
    border-radius: 8px; font-weight: 500;
}}
.stTabs [data-baseweb="tab"] {{ font-weight: 500; font-size: 0.95rem; }}

/* Header strip: the one bold element on the page */
.cat-header {{
    background: {INK}; color: #FFFFFF;
    border-radius: 12px; padding: 1.1rem 1.4rem 1rem; margin-bottom: 1.25rem;
    border-bottom: 3px solid {AMBER};
}}
.cat-header-title {{ font-size: 1.55rem; font-weight: 600; letter-spacing: -0.015em; line-height: 1.2; }}
.cat-header-meta {{
    display: flex; flex-wrap: wrap; gap: 0.35rem 1.5rem;
    margin-top: 0.4rem; font-size: 0.88rem; color: #B9C6D3;
}}
.cat-header-meta b {{ color: #FFFFFF; font-weight: 500; }}

/* Status stats: color bar = the status color used on the map and calendar.
   Colors are inherited so the cards work in both themes. */
.cat-stats {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.75rem; margin: 0.25rem 0 0.5rem;
}}
.cat-stat {{
    background: rgba(128, 140, 155, 0.06);
    border: 1px solid rgba(128, 140, 155, 0.25);
    border-left: 5px solid var(--c);
    border-radius: 10px; padding: 0.7rem 1rem;
}}
.cat-stat-value {{ font-size: 1.7rem; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.2; }}
.cat-stat-label {{ font-size: 0.85rem; opacity: 0.72; }}

/* Month slot picker: keep the 7-day grid side by side, even on phones */
[class*="st-key-slotpicker"] [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap !important; gap: 0.25rem !important; }}
[class*="st-key-slotpicker"] [data-testid="stColumn"], [class*="st-key-slotpicker"] [data-testid="column"] {{
    min-width: 0 !important; width: auto !important; flex: 1 1 0 !important;
}}
[class*="st-key-slotpicker"] button {{ padding: 0.2rem 0 !important; min-height: 2.1rem; font-variant-numeric: tabular-nums; }}
[class*="st-key-slotpicker"] .stCaption, [class*="st-key-slotpicker"] [data-testid="stCaptionContainer"] {{ text-align: center; }}
[class*="st-key-pd_open"] [data-testid="stBaseButton-secondary"] {{ background: rgba(34, 160, 90, 0.16); border-color: rgba(34, 160, 90, 0.5); }}
[class*="st-key-pd_few"] [data-testid="stBaseButton-secondary"] {{ background: rgba(232, 163, 23, 0.18); border-color: rgba(232, 163, 23, 0.55); }}
[class*="st-key-pd_full"] button {{ background: repeating-linear-gradient(45deg, rgba(128, 140, 155, 0.16) 0 4px, transparent 4px 8px) !important; }}
[class*="st-key-pd_off"] button {{ opacity: 0.35; }}
[class*="st-key-pt_open"] [data-testid="stBaseButton-secondary"] {{ border-color: rgba(34, 160, 90, 0.55); }}

/* Next-up and selected-block cards */
.cat-card {{ border-left: 4px solid {AMBER}; padding: 0.1rem 0 0.1rem 0.85rem; margin-bottom: 0.6rem; }}
.cat-card.selected {{ border-left-color: {SCHEDULED_BLUE}; }}
.cat-card-kicker {{ font-size: 0.82rem; opacity: 0.72; }}
.cat-card-title {{ font-size: 1.05rem; font-weight: 600; margin: 0.1rem 0; }}
.cat-card-sub {{ font-size: 0.9rem; opacity: 0.8; }}
</style>
""", unsafe_allow_html=True)

if CONSOLE:
    # Console theme: dark command strip with a faint grid, instrument-style stats
    # in mono numerals, and one glow (on the next inspection). Nothing else moves.
    st.markdown(f"""
<style>
.cat-header {{
    background-color: {C_PANEL};
    background-image:
        linear-gradient(rgba(63, 208, 224, 0.06) 1px, transparent 1px),
        linear-gradient(90deg, rgba(63, 208, 224, 0.06) 1px, transparent 1px);
    background-size: 22px 22px;
    border: 1px solid {C_LINE};
    border-bottom: 2px solid {C_SIGNAL};
}}
.cat-header-title {{ color: {C_TEXT}; }}
.cat-header-meta {{ font-family: {MONO}; font-size: 0.82rem; color: {C_MUTED}; }}
.cat-header-meta b {{ color: {C_SIGNAL}; font-weight: 500; }}

.cat-stat {{
    background: {C_PANEL};
    border: 1px solid {C_LINE};
    border-left: 3px solid var(--c);
    box-shadow: -6px 0 18px -10px var(--c);
}}
.cat-stat-value {{ font-family: {MONO}; font-weight: 500; color: {C_TEXT}; }}
.cat-stat-label {{ color: {C_MUTED}; opacity: 1; }}

.cat-card-kicker, .cat-card-sub {{ font-family: {MONO}; font-size: 0.8rem; color: {C_MUTED}; opacity: 1; }}
.cat-card-title {{ color: {C_TEXT}; }}
.cat-card:not(.selected) {{
    border-left-color: {AMBER};
    box-shadow: -8px 0 22px -12px {AMBER};
    animation: cat-next-glow 2.4s ease-out 1;
}}
@keyframes cat-next-glow {{
    0%   {{ box-shadow: -8px 0 34px -6px {AMBER}; }}
    100% {{ box-shadow: -8px 0 22px -12px {AMBER}; }}
}}
@media (prefers-reduced-motion: reduce) {{ .cat-card {{ animation: none !important; }} }}

.stApp hr {{ border-top-color: {C_LINE}; }}
[data-testid="stSidebar"] {{ border-right: 1px solid {C_LINE}; }}
</style>
""", unsafe_allow_html=True)


# =====================================================================
# SESSION STATE & HELPERS
# =====================================================================
if "claims_df" not in st.session_state:
    st.session_state.claims_df = None

# Bumped whenever claims_df is changed outside the editor, so the data_editor
# starts fresh instead of re-applying stale row edits.
if "editor_version" not in st.session_state:
    st.session_state.editor_version = 0

# Bumped after a pin is moved, so the map resets its last click.
if "map_nonce" not in st.session_state:
    st.session_state.map_nonce = 0


def time_options(step_min=15):
    """Times of day in 12-hour order, for dropdowns (Streamlit's time box can show 24-hour)."""
    return [datetime.min.replace(hour=m // 60, minute=m % 60).time() for m in range(0, 24 * 60, step_min)]


def fmt_time12(t):
    return datetime.combine(date.today(), t).strftime("%I:%M %p").lstrip("0")


def book_claim_into_slot(claim_mask, slot):
    """
    Schedules (or reschedules) the claim(s) in claim_mask into the given slot.
    The first booking is recorded as the initial contact and is never overwritten
    by a reschedule (it can be edited in the claims pool).
    """
    cdf = st.session_state.claims_df
    for i in cdf.index[claim_mask]:
        if "first_booked_at" not in cdf.columns:
            cdf["first_booked_at"] = ""
        if not clean_text(cdf.at[i, "first_booked_at"]):
            cdf.at[i, "first_booked_at"] = now_local.replace(second=0, microsecond=0).isoformat()
        if "activity_type" not in cdf.columns or not clean_text(cdf.at[i, "activity_type"]):
            cdf.at[i, "activity_type"] = ACTIVITY_ONSITE
    st.session_state.claims_df.loc[claim_mask, "status"] = "Scheduled"
    st.session_state.claims_df.loc[claim_mask, "start_time"] = slot["start"]
    st.session_state.claims_df.loc[claim_mask, "end_time"] = slot["end"]
    st.session_state.claims_df.loc[claim_mask, "scheduled_date"] = slot["date_str"]
    st.session_state.claims_df.loc[claim_mask, "inspection_time"] = parse_wallclock(slot["start"]).strftime("%H:%M")
    st.session_state.editor_version += 1
    displace_drafts(slot, booked_ids={str(c) for c in cdf.loc[claim_mask, "claim_id"]})


def set_claim_times(cid, status, slot=None):
    """Sets a claim's status and time (or clears the time when slot is None)."""
    m = st.session_state.claims_df["claim_id"].astype(str) == str(cid)
    st.session_state.claims_df.loc[m, "status"] = status
    st.session_state.claims_df.loc[m, "start_time"] = slot["start"] if slot else None
    st.session_state.claims_df.loc[m, "end_time"] = slot["end"] if slot else None
    st.session_state.claims_df.loc[m, "scheduled_date"] = slot["date_str"] if slot else ""
    st.session_state.claims_df.loc[m, "inspection_time"] = (
        parse_wallclock(slot["start"]).strftime("%H:%M") if slot else "")


def displace_drafts(slot, booked_ids):
    """
    A confirmed booking takes priority over drafts. Any draft overlapping the new time
    moves to its best open spot (closest to that day's other stops), or back to
    Unscheduled if nothing is open.
    """
    s0, s1 = parse_wallclock(slot["start"]), parse_wallclock(slot["end"])
    cdf = st.session_state.claims_df
    hit = [str(r["claim_id"]) for _, r in cdf[cdf["status"] == "Draft"].iterrows()
           if str(r["claim_id"]) not in booked_ids and parse_wallclock(r["start_time"]) and parse_wallclock(r["end_time"])
           and max(s0, parse_wallclock(r["start_time"])) < min(s1, parse_wallclock(r["end_time"]))]
    notes = []
    for cid in hit:
        spot = best_spot_for_draft(st.session_state.claims_df, cid, schedule_settings, hotel_coords,
                                   now_local, FILL_LATEST_FIRST)
        if spot:
            set_claim_times(cid, "Draft", spot)
            notes.append(f"Draft {cid} moved to {fmt_dt(parse_wallclock(spot['start']))}.")
        else:
            set_claim_times(cid, "Unscheduled")
            notes.append(f"Draft {cid} had no open spot left, so it's back to Unscheduled.")
    if notes:
        st.session_state["draft_notice"] = " ".join(notes)


def confirm_draft(cid):
    """Confirms a draft at its current time and records the initial contact."""
    m = st.session_state.claims_df["claim_id"].astype(str) == str(cid)
    row = st.session_state.claims_df[m].iloc[0]
    book_claim_into_slot(m, {"start": row["start_time"], "end": row["end_time"], "date_str": row["scheduled_date"]})
    st.toast(f"Confirmed {cid}")


def save_manual_pin(claim_id, lat, lon):
    """Stores a rep-placed pin. Saved with progress, and kept on re-geocode."""
    mask = st.session_state.claims_df["claim_id"].astype(str) == str(claim_id)
    st.session_state.claims_df.loc[mask, "lat"] = float(lat)
    st.session_state.claims_df.loc[mask, "lon"] = float(lon)
    st.session_state.claims_df.loc[mask, "geo_quality"] = GEO_MANUAL
    st.session_state.map_nonce += 1
    st.session_state.editor_version += 1
    st.toast(f"Pin saved for {claim_id}")


def confirm_pin(claim_id):
    """Marks the current pin as correct without moving it."""
    mask = st.session_state.claims_df["claim_id"].astype(str) == str(claim_id)
    st.session_state.claims_df.loc[mask, "geo_quality"] = GEO_CONFIRMED
    st.session_state.map_nonce += 1
    st.session_state.editor_version += 1
    st.toast(f"Location confirmed for {claim_id}")


def queue_next_pin_to_fix(current_claim_id):
    """After a fix, jump the 'Claim to fix' picker to the next claim that still needs checking."""
    cdf = st.session_state.claims_df
    flagged = [str(c) for c, q in zip(cdf["claim_id"], cdf["geo_quality"])
               if q in GEO_NEEDS_REVIEW and str(c) != str(current_claim_id)]
    if flagged:
        ids = [str(c) for c in cdf["claim_id"]]
        cur_pos = ids.index(str(current_claim_id)) if str(current_claim_id) in ids else -1
        after = [c for c in flagged if ids.index(c) > cur_pos]
        st.session_state["pending_fix_claim_id"] = (after or flagged)[0]
    else:
        st.session_state["pending_fix_claim_id"] = None
        st.session_state["all_pins_checked"] = True


def _set_state(key, value):
    st.session_state[key] = value


def round_time_15(t):
    if t is None:
        return datetime.strptime("08:00", "%H:%M").time()
    total = (t.hour * 60 + t.minute + 14) // 15 * 15
    total = min(total, 23 * 60 + 45)
    return datetime.min.replace(hour=total // 60, minute=total % 60).time()


def render_slot_picker(claim_id, claims_df, now, settings, current=None, default_hrs=None):
    """
    Booking picker. Shows the next opening; with the calendar toggle on, shows a month
    view colored by real availability, then the chosen day's bookings and open time.
    Any start time (15-minute steps) and any length can be booked, as long as it doesn't
    overlap another inspection. Returns a slot dict to book, or None.
    `current` = (start, end) of this claim's existing booking when rescheduling.
    """
    cid = str(claim_id)
    S = settings
    busy = get_busy_intervals(claims_df, exclude_claim_id=cid)              # confirmed: can't overlap
    busy_all = get_busy_intervals(claims_df, exclude_claim_id=cid, include_drafts=True)
    drafts_busy = [b for b in busy_all if b.get("draft")]                  # drafts: a booking replaces them
    length_hrs = float(default_hrs or S["window_hrs"])
    openings = order_openings(
        compute_openings(S["start_date"], S["end_date"], S["active_days"], S["day_start"],
                         S["per_day"], S["window_hrs"], claims_df, now=now, exclude_claim_id=cid,
                         latest_end=S["latest_end"], duration_hrs=length_hrs, include_drafts=True),
        latest_days_first=S.get("latest_first", False)
    )

    def tfmt(dt):
        return dt.strftime("%I:%M %p").lstrip("0")

    # Free time for each inspection day in the date range
    gaps_by_day = {}
    d = S["start_date"]
    while d <= S["end_date"]:
        if d.strftime("%a") in S["active_days"]:
            gaps_by_day[d.isoformat()] = compute_day_gaps(d, S["day_start"], S["per_day"], S["window_hrs"],
                                                          busy_all, now, S["latest_end"])
        d += timedelta(days=1)
    openings_by_day = defaultdict(list)
    for o in openings:
        openings_by_day[o["date_str"]].append(o)

    days_with_time = [ds for ds, g in gaps_by_day.items() if g]
    if not days_with_time:
        st.info("No open time left in this date range. Extend the end date or adjust the day settings in the sidebar.")
        return None

    if not st.toggle("📅 Pick a day and time", key=f"pick_cal_{cid}"):
        if openings:
            nxt = openings[0]
            n_s, n_e = parse_wallclock(nxt["start"]), parse_wallclock(nxt["end"])
            st.markdown(f"**Next opening:** {n_s.strftime('%a %b %d')}, {tfmt(n_s)} - {tfmt(n_e)}")
            return nxt
        st.info("No full-length openings left, but there is shorter open time. "
                "Turn on **Pick a day and time** to book a shorter inspection.")
        return None

    day_key, time_key, dur_key, month_key = (f"pick_day_{cid}", f"pick_time_{cid}",
                                             f"pick_dur_{cid}", f"pick_month_{cid}")

    def first_free_start(ds):
        if openings_by_day.get(ds):
            return parse_wallclock(openings_by_day[ds][0]["start"])
        return gaps_by_day[ds][0][0]

    if st.session_state.get(day_key) not in days_with_time:
        st.session_state[day_key] = openings[0]["date_str"] if openings else days_with_time[0]
        st.session_state[time_key] = first_free_start(st.session_state[day_key]).time()
    if time_key not in st.session_state:
        st.session_state[time_key] = first_free_start(st.session_state[day_key]).time()
    # Default length: the window setting, or 1 hour for live video (resets if the type changes)
    if dur_key not in st.session_state or st.session_state.get(f"pick_dur_basis_{cid}") != length_hrs:
        st.session_state[dur_key] = length_hrs
        st.session_state[f"pick_dur_basis_{cid}"] = length_hrs
    sel_day = st.session_state[day_key]

    # Months covered by the date range
    months = []
    y, mo = S["start_date"].year, S["start_date"].month
    while (y, mo) <= (S["end_date"].year, S["end_date"].month):
        months.append((y, mo))
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    if st.session_state.get(month_key) not in months:
        d0 = date.fromisoformat(sel_day)
        st.session_state[month_key] = (d0.year, d0.month) if (d0.year, d0.month) in months else months[0]
    y, mo = st.session_state[month_key]
    m_idx = months.index((y, mo))

    with st.container(key=f"slotpicker_{cid}"):
        n1, n2, n3 = st.columns([1, 3, 1], vertical_alignment="center")
        n1.button("◀", key=f"pm_prev_{cid}", disabled=m_idx == 0, use_container_width=True,
                  on_click=_set_state, args=(month_key, months[max(m_idx - 1, 0)]))
        n2.markdown(f"<div style='text-align:center;font-weight:600'>{pycal.month_name[mo]} {y}</div>",
                    unsafe_allow_html=True)
        n3.button("▶", key=f"pm_next_{cid}", disabled=m_idx == len(months) - 1, use_container_width=True,
                  on_click=_set_state, args=(month_key, months[min(m_idx + 1, len(months) - 1)]))

        for col, wd in zip(st.columns(7), ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]):
            col.caption(wd)

        def pick_day(ds):
            st.session_state[day_key] = ds
            st.session_state[time_key] = first_free_start(ds).time()

        for week in pycal.Calendar(firstweekday=6).monthdatescalendar(y, mo):
            for col, d in zip(st.columns(7), week):
                if d.month != mo:
                    col.markdown("&nbsp;", unsafe_allow_html=True)
                    continue
                ds = d.isoformat()
                if ds not in gaps_by_day:
                    state, tip, can_pick = "off", "Not an inspection day", False
                elif not gaps_by_day[ds]:
                    state, tip, can_pick = "full", "No open time left", False
                else:
                    n_open = len(openings_by_day.get(ds, []))
                    state = "open" if n_open >= 2 else "few"
                    tip = "Open " + ", ".join(f"{tfmt(a)}-{tfmt(b)}" for a, b in gaps_by_day[ds])
                    can_pick = True
                col.button(str(d.day), key=f"pd_{state}_{cid}_{ds}", help=tip, disabled=not can_pick,
                           use_container_width=True, type="primary" if ds == sel_day else "secondary",
                           on_click=pick_day, args=(ds,))

        st.caption("Green: room for 2+ inspections. Amber: room for 1 or less. Hatched: no open time. "
                   "Faded: not an inspection day.")

    # ---- The selected day ----
    day_d = date.fromisoformat(sel_day)
    ws, we = day_window(day_d, S["day_start"], S["per_day"], S["window_hrs"], S["latest_end"])
    st.markdown(f"**{day_d.strftime('%A, %b %d')}** ({tfmt(ws)} - {tfmt(we)} working hours)")

    rows = [(b["start"], f"{tfmt(b['start'])} - {tfmt(b['end'])}",
             f"Draft (unconfirmed): {b['label']}" if b.get("draft") else f"Booked: {b['label']}")
            for b in busy_all if b["start"].date() == day_d]
    if current and current[0] and current[0].date() == day_d:
        rows.append((current[0], f"{tfmt(current[0])} - {tfmt(current[1])}", "This claim's current time"))
    rows += [(a, f"{tfmt(a)} - {tfmt(b)}", "Open") for a, b in gaps_by_day[sel_day]]
    rows.append((we, f"After {tfmt(we)}", "Evening: type a later start time if the insured is available"))
    st.markdown("  \n".join(
        f":green[**{when}** · open]" if what == "Open" else f"{when} · {what}"
        for _, when, what in sorted(rows, key=lambda r: r[0])
    ))

    # Quick starts: the beginning of each open block
    quick = sorted({parse_wallclock(o["start"]) for o in openings_by_day.get(sel_day, [])} |
                   {a for a, _ in gaps_by_day[sel_day]})
    if quick:
        st.caption("Quick start times")
        for i in range(0, len(quick), 3):
            for col, t in zip(st.columns(3), quick[i:i + 3]):
                col.button(tfmt(t), key=f"pt_open_{cid}_{t.isoformat()}", use_container_width=True,
                           type="primary" if st.session_state[time_key] == t.time() else "secondary",
                           on_click=_set_state, args=(time_key, t.time()))

    t1, t2 = st.columns(2)
    _t15 = time_options(15)
    if st.session_state.get(time_key) not in _t15:
        st.session_state[time_key] = round_time_15(st.session_state.get(time_key))
    t1.selectbox("Start time", _t15, key=time_key, format_func=fmt_time12)
    t2.number_input("Length (hours)", key=dur_key, min_value=0.25, max_value=8.0, step=0.25)

    start_dt = datetime.combine(day_d, st.session_state[time_key])
    requested_hrs = float(st.session_state[dur_key])
    slot = make_slot(start_dt, requested_hrs)
    end_dt = parse_wallclock(slot["end"])

    def hm(minutes):
        h, m = divmod(int(round(minutes)), 60)
        return f"{h} hr {m} min" if h and m else (f"{h} hr" if h else f"{m} min")

    if start_dt <= now:
        st.error("That start time has already passed. Pick a later time.")
        return None

    # Can't start in the middle of another inspection
    during = next((b for b in busy if b["start"] <= start_dt < b["end"]), None)
    if during:
        st.error(f"{tfmt(start_dt)} is during {during['label']} ({tfmt(during['start'])} - {tfmt(during['end'])}). "
                 "Pick a start time in an open block.")
        return None

    # Not enough room before the next inspection: offer a shortened inspection,
    # but only after the rep acknowledges it may not be enough time.
    next_booking = min((b for b in busy if b["start"] > start_dt), key=lambda b: b["start"], default=None)
    if next_booking and end_dt > next_booking["start"]:
        fit_end = next_booking["start"]
        fit_min = (fit_end - start_dt).total_seconds() / 60
        if fit_min < 15:
            st.error(f"Only {hm(fit_min)} open before {next_booking['label']} at {tfmt(fit_end)}. "
                     "Pick an earlier start time.")
            return None
        st.warning(
            f"Only **{hm(fit_min)}** is open before {next_booking['label']} at {tfmt(fit_end)}. "
            f"You asked for {hm(requested_hrs * 60)}, so this may not be enough time for the inspection. "
            f"If you continue, this inspection will be shortened to **{tfmt(start_dt)} - {tfmt(fit_end)}** to fit."
        )
        ack = st.checkbox("I understand. Book the shorter inspection.",
                          key=f"ack_short_{cid}_{start_dt.isoformat()}_{requested_hrs}")
        if not ack:
            return None
        slot = make_slot(start_dt, fit_min / 60)
        end_dt = fit_end

    if start_dt < ws:
        st.caption(f"Starts before your usual {tfmt(ws)} day start.")
    replaced = [b for b in drafts_busy if max(start_dt, b["start"]) < min(end_dt, b["end"])]
    if replaced:
        st.info("This replaces the draft for " + ", ".join(b["label"] for b in replaced) +
                ". It will move to its best open spot when you book.")
    st.markdown(f"**Selected:** {start_dt.strftime('%a %b %d')}, {tfmt(start_dt)} - {tfmt(end_dt)}")
    return slot


def core_view_points(points, share=0.9, min_points=5):
    """
    Returns the share of points (default 90%) closest to the middle of the group,
    plus how many were left out. Far-off pins (a bad address, a claim across the state)
    stay on the map but don't force the view to zoom way out.
    """
    if len(points) < min_points:
        return points, 0
    lats = sorted(p[0] for p in points)
    lons = sorted(p[1] for p in points)
    mid_lat, mid_lon = lats[len(lats) // 2], lons[len(lons) // 2]   # median resists outliers
    lon_scale = math.cos(math.radians(mid_lat))
    ranked = sorted(points, key=lambda p: (p[0] - mid_lat) ** 2 + ((p[1] - mid_lon) * lon_scale) ** 2)
    keep = max(min_points, math.ceil(len(points) * share))
    return ranked[:keep], len(points) - keep


def view_center_zoom(points, width_px=900, height_px=540, padding_px=50, max_zoom=16):
    """
    Center and zoom level that fit all points on a web map of the given size.
    Computed directly (instead of fit_bounds) so the map opens on this view.
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    north, south, east, west = max(lats), min(lats), max(lons), min(lons)
    center = [(north + south) / 2, (east + west) / 2]

    def lat_rad(lat):
        s = math.sin(math.radians(lat))
        return max(min(math.log((1 + s) / (1 - s)) / 2, math.pi), -math.pi) / 2

    lat_frac = (lat_rad(north) - lat_rad(south)) / math.pi
    lon_frac = (east - west) / 360.0
    w, h = max(width_px - 2 * padding_px, 100), max(height_px - 2 * padding_px, 100)
    zooms = [max_zoom]
    if lat_frac > 0:
        zooms.append(math.log2(h / 256.0 / lat_frac))
    if lon_frac > 0:
        zooms.append(math.log2(w / 256.0 / lon_frac))
    return center, max(3, int(math.floor(min(zooms))))


def render_nav_buttons(address, lat, lon, geo_quality=None):
    """Shows 'Google Maps' and 'Apple Maps' directions buttons side by side."""
    links = build_navigation_links(address, lat, lon, prefer_coords=(geo_quality in GEO_REP_VERIFIED))
    if not links:
        return
    b1, b2 = st.columns(2)
    with b1:
        st.link_button("🗺️ Google Maps", links["google"], use_container_width=True)
    with b2:
        st.link_button("🍎 Apple Maps", links["apple"], use_container_width=True)


def fmt_dt(dt):
    return dt.strftime("%a %m/%d %I:%M %p") if dt else ""


def esc(value):
    return html.escape(str(value)) if value is not None else ""


# =====================================================================
# SIDEBAR
# =====================================================================
st.sidebar.header("Schedule settings")
st.sidebar.caption("Switch between Field (light) and Console (dark) themes in the ⋮ menu at the top right, under Settings.")
hotel_address = st.sidebar.text_input(
    "Hotel base location", value="",
    placeholder="Street, city, state, ZIP",
    help="Where you're staying. The first stop of each day is measured from here, and with "
         "Least added driving, the last stop of the day favors claims on the way back."
)
hotel_coords = geocode_hotel_address(hotel_address)
if not hotel_address.strip():
    st.sidebar.caption("Add your hotel address so each day's first drive time starts there.")
elif hotel_coords is None:
    st.sidebar.warning("Couldn't find the hotel address. The first stop of each day will use "
                       "the center of your claims for drive times.")

col_d1, col_d2 = st.sidebar.columns(2)
start_date = col_d1.date_input("Start date", date.today())
end_date = col_d2.date_input("End date", date.today() + timedelta(days=5))

active_days = st.sidebar.multiselect(
    "Inspection days",
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    default=["Mon", "Tue", "Wed", "Thu", "Fri"]
)

inspections_per_day = st.sidebar.slider(
    "Inspections per day", 1, 8, 3,
    help="Sets the length of your working day: day start time + this many windows."
)

window_hrs = st.sidebar.number_input(
    "Window length (hours)",
    help="Default inspection length. Openings are suggested in blocks of this length, "
         "but you can book any start time and length.",
    min_value=0.25,
    max_value=8.00,
    value=2.50,
    step=0.25
)

_times30 = time_options(30)
start_time_input = st.sidebar.selectbox(
    "Day start time", _times30, index=_times30.index(datetime.strptime("08:00", "%H:%M").time()),
    format_func=fmt_time12, key="day_start_time"
)
latest_end_input = st.sidebar.selectbox(
    "Latest end for suggested openings", _times30,
    index=_times30.index(datetime.strptime("19:00", "%H:%M").time()),
    format_func=fmt_time12, key="latest_end_time",
    help="Suggested openings never run past this time. You can still book later by hand "
         "if the insured is available."
)

rec_mode_label = st.sidebar.radio(
    "Recommendations",
    ["Closest to previous stop (faster)", "Least added driving (smarter, may take longer)"],
    key="rec_mode",
    help="Closest: ranks claims by drive time from where you'll be before the opening. "
         "Least added driving: also counts the drive to where you're going next (your next "
         "inspection, or the hotel at the end of the day), so claims on the way rank higher. "
         "It looks up about twice as many drive times, so it can be slower."
)
REC_MODE = "detour" if rec_mode_label.startswith("Least") else "fast"

fill_label = st.sidebar.radio(
    "Fill your schedule from",
    ["Start of deployment (earliest days first)", "End of deployment (latest days first)"],
    key="fill_direction",
    help="Changes the order of suggested openings. Within each day, suggestions still "
         "run morning to afternoon. You can always pick any day and time yourself."
)
FILL_LATEST_FIRST = fill_label.startswith("End")

# --- DEPLOYMENT TIME ZONE ---
# All schedule times are local to the deployment; this zone is used for the
# Outlook export and for knowing which inspections are already in the past.
detected_tz, detected_source = detect_deployment_timezone(st.session_state.claims_df, hotel_address)
detected_label = next((k for k, v in US_TIMEZONES.items() if v == detected_tz), detected_tz)
tz_choices = [f"Auto-detect ({detected_label})"] + list(US_TIMEZONES.keys())
tz_choice = st.sidebar.selectbox(
    "Deployment time zone",
    tz_choices,
    index=0,
    help=f"Auto-detected from {detected_source}. Override if the deployment is in a split-zone "
         "area (e.g. El Paso, the Florida panhandle, western Kansas/Nebraska/Dakotas)."
)
deployment_tz = detected_tz if tz_choice.startswith("Auto-detect") else US_TIMEZONES[tz_choice]
tz_display = detected_label if tz_choice.startswith("Auto-detect") else tz_choice

try:
    deployment_zone = get_zone(deployment_tz)
    now_local = datetime.now(deployment_zone).replace(tzinfo=None)
    ics_tz = deployment_tz
except Exception:
    st.sidebar.error("Time zone data isn't installed. Run `pip install tzdata` (needed on Windows). "
                     "Until then, calendar exports use floating local times.")
    now_local = datetime.now()
    ics_tz = None

# Openings come from the real bookings: any free time inside each day's working
# window, in blocks of the default window length starting at the earliest free time.
schedule_settings = {
    "start_date": start_date, "end_date": end_date, "active_days": active_days,
    "day_start": start_time_input, "per_day": inspections_per_day, "window_hrs": window_hrs,
    "latest_end": latest_end_input,
    "latest_first": FILL_LATEST_FIRST,
}
all_slots = order_openings(compute_openings(
    start_date, end_date, active_days, start_time_input, inspections_per_day, window_hrs,
    st.session_state.claims_df, now=now_local, latest_end=latest_end_input, include_drafts=True
), latest_days_first=FILL_LATEST_FIRST)

# --- PLAN MY SCHEDULE ---
st.sidebar.markdown("---")
st.sidebar.subheader("Plan my schedule")
if st.session_state.claims_df is None:
    st.sidebar.caption("Import claims to build a draft schedule.")
else:
    _cdf = st.session_state.claims_df
    _n_drafts = int((_cdf["status"] == "Draft").sum()) if "status" in _cdf.columns else 0
    cap = capacity_report(_cdf, schedule_settings, now_local)
    st.sidebar.caption(
        "Builds draft appointments for your unscheduled claims, grouped by area and ordered as routes. "
        "Confirmed appointments never move. Confirm each draft after the insured agrees."
    )
    if cap["shortfall"]:
        msg = (f"**{cap['claims']} claims to place, but only {cap['openings']} openings fit your settings. "
               f"{cap['shortfall']} claim(s) won't be scheduled.** To fit everyone, you could:\n")
        msg += "\n".join(f"- {label}" + (f": +{extra} openings" if extra else "") for label, extra in cap["suggestions"])
        msg += "\n\nIf you plan anyway, the highest-priority claims are placed first."
        st.sidebar.warning(msg)
    elif cap["claims"]:
        st.sidebar.caption(f"{cap['claims']} claim(s) to place, {cap['openings']} openings available.")

    p1, p2 = st.sidebar.columns(2)
    plan_label = "Re-plan drafts" if _n_drafts else "Plan my schedule"
    if p1.button(plan_label, type="primary", use_container_width=True, disabled=cap["claims"] == 0,
                 help="Builds draft appointments for your unscheduled claims (and replaces current drafts). "
                      "This can take up to a minute for large lists."):
        bar = st.sidebar.progress(0.0, text="Starting...")
        drafts, summary = plan_draft_schedule(_cdf, schedule_settings, hotel_coords, now_local,
                                              latest_first=FILL_LATEST_FIRST,
                                              progress=lambda f, t: bar.progress(min(max(f, 0.0), 1.0), text=t))
        bar.empty()
        for cid in _cdf.loc[_cdf["status"] == "Draft", "claim_id"].astype(str).tolist():
            set_claim_times(cid, "Unscheduled")
        for dft in drafts:
            set_claim_times(dft["claim_id"], "Draft", {"start": dft["start"], "end": dft["end"],
                                                       "date_str": dft["start"][:10]})
        st.session_state["plan_summary"] = summary
        st.session_state.editor_version += 1
        st.session_state.map_nonce += 1
        st.rerun()
    if p2.button("Clear drafts", use_container_width=True, disabled=_n_drafts == 0,
                 help="Removes all unconfirmed draft appointments. Confirmed ones stay."):
        for cid in _cdf.loc[_cdf["status"] == "Draft", "claim_id"].astype(str).tolist():
            set_claim_times(cid, "Unscheduled")
        st.session_state.pop("plan_summary", None)
        st.session_state.editor_version += 1
        st.session_state.map_nonce += 1
        st.rerun()

# --- MAP TOOLS & SAVED PROGRESS ---
st.sidebar.markdown("---")
st.sidebar.subheader("Map & saved progress")

if st.session_state.claims_df is not None:
    if st.sidebar.button("🔄 Re-check all addresses", type="secondary",
                         help="Looks up every address again. Pins you placed or confirmed are kept."):
        cdf = st.session_state.claims_df
        if "geo_quality" not in cdf.columns:
            cdf["geo_quality"] = GEO_UNKNOWN
        redo_idx = cdf.index[~cdf["geo_quality"].isin(GEO_REP_VERIFIED)].tolist()
        with st.spinner("Re-checking addresses..."):
            addrs = [(cdf.at[i, "full_address"], cdf.at[i, "state"] if "state" in cdf.columns else "") for i in redo_idx]
            results = batch_geocode_addresses(addrs)
            for i, (lat, lon, quality) in zip(redo_idx, results):
                cdf.at[i, "lat"] = lat
                cdf.at[i, "lon"] = lon
                cdf.at[i, "geo_quality"] = quality
        st.session_state.map_nonce += 1
        st.rerun()

    st.sidebar.markdown(" ")
    csv_bytes = st.session_state.claims_df.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(
        label="📥 Save progress",
        data=csv_bytes,
        file_name=f"cat_scheduler_state_{date.today().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

saved_file = st.sidebar.file_uploader("📂 Load saved progress", type=["csv"], key="load_state_csv")
if saved_file is not None:
    # Only load a given file once. Without this check the saved CSV would be
    # re-read on every rerun and overwrite any edits.
    file_sig = (saved_file.name, saved_file.size)
    if st.session_state.get("loaded_state_sig") != file_sig:
        try:
            loaded_df = pd.read_csv(saved_file)
            st.session_state.claims_df = loaded_df
            st.session_state.loaded_state_sig = file_sig
            st.session_state.editor_version += 1
            st.session_state.map_nonce += 1
            st.sidebar.success("Progress restored.")
        except Exception as e:
            st.sidebar.error(f"Couldn't load that file: {e}")


# =====================================================================
# HEADER
# =====================================================================
st.markdown(f"""
<div class="cat-header">
  <div class="cat-header-title">CAT Dynamic Scheduling</div>
  <div class="cat-header-meta">
    <span><b>{esc(tz_display)}</b> time</span>
    <span><b>{start_date.strftime('%b %d')}</b> to <b>{end_date.strftime('%b %d, %Y')}</b></span>
    <span>Base: <b>{esc(hotel_address) or 'not set'}</b></span>
  </div>
</div>
""", unsafe_allow_html=True)


# =====================================================================
# IMPORT
# =====================================================================
st.subheader("Import claims")
if st.session_state.claims_df is not None:
    st.caption("To add an updated claims list, upload it here. Claims you already have keep their "
               "schedule, priority, and pin fixes. Starting a new session? Load your saved progress first.")
uploaded_file = st.file_uploader("Upload a CSV or Excel claims list", type=["csv", "xlsx"])


def read_claims_file(f):
    return pd.read_csv(f) if f.name.lower().endswith(".csv") else pd.read_excel(f)


if uploaded_file is not None:
    upload_sig = (uploaded_file.name, uploaded_file.size)

    if st.session_state.claims_df is None:
        # First list of the session: import everything
        try:
            with st.spinner("Reading the claims list and looking up addresses..."):
                st.session_state.claims_df = process_imported_table(read_claims_file(uploaded_file))
                st.session_state.processed_upload_sig = upload_sig
                st.rerun()
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")

    elif st.session_state.get("processed_upload_sig") != upload_sig:
        # An updated list while claims are loaded: compare first, change nothing yet
        if st.session_state.get("merge_plan_sig") != upload_sig:
            try:
                st.session_state.merge_plan = build_merge_plan(st.session_state.claims_df,
                                                               read_claims_file(uploaded_file))
                st.session_state.merge_plan_sig = upload_sig
            except Exception as e:
                st.error(f"Couldn't read that file: {e}")
                st.session_state.merge_plan = None

        plan = st.session_state.get("merge_plan")
        if plan is not None:
            n_new, n_chg, n_miss = len(plan["new"]), len(plan["address_changes"]), len(plan["missing"])
            if n_new == n_chg == n_miss == 0:
                st.info(f"This list matches the claims you already have ({plan['unchanged']} claims). Nothing to update.")
                st.session_state.processed_upload_sig = upload_sig
            else:
                with st.container(border=True):
                    st.markdown(f"**Updated claims list: {uploaded_file.name}**")
                    st.markdown(
                        f"- **{n_new}** new claim(s) to add\n"
                        f"- **{n_chg}** address change(s) to review\n"
                        f"- **{n_miss}** claim(s) not in this list, to review\n"
                        f"- {plan['unchanged']} claim(s) unchanged"
                    )
                    st.caption("New claims are added right away. Address changes and missing claims are "
                               "reviewed one at a time after you apply. Nothing changes until then.")
                    a1, a2 = st.columns(2)
                    if a1.button("Apply update", type="primary", use_container_width=True):
                        if plan["new"]:
                            with st.spinner(f"Looking up {n_new} new address(es)..."):
                                added = geocode_claim_rows(plan["new"])
                            st.session_state.claims_df = pd.concat(
                                [st.session_state.claims_df, added], ignore_index=True)
                        for fill in plan.get("contact_fills", []):
                            fmask = st.session_state.claims_df["claim_id"].astype(str) == fill["claim_id"]
                            for field in ("phone", "email"):
                                if fill.get(field):
                                    st.session_state.claims_df.loc[fmask, field] = fill[field]
                        queue = ([{"type": "address", **c} for c in plan["address_changes"]] +
                                 [{"type": "missing", "claim_id": cid} for cid in plan["missing"]])
                        st.session_state.review_queue = queue
                        st.session_state.review_total = len(queue)
                        st.session_state.processed_upload_sig = upload_sig
                        st.session_state.merge_plan = None
                        st.session_state.editor_version += 1
                        st.session_state.map_nonce += 1
                        st.toast(f"Added {n_new} new claim(s)" if n_new else "Update applied")
                        st.rerun()
                    if a2.button("Not now", use_container_width=True):
                        st.session_state.processed_upload_sig = upload_sig
                        st.session_state.merge_plan = None
                        st.rerun()


# --- Review flagged claims from an updated list, one at a time ---
review_queue = st.session_state.get("review_queue") or []
if review_queue and st.session_state.claims_df is not None:
    cdf = st.session_state.claims_df
    item = review_queue[0]
    cid = str(item["claim_id"])
    match = cdf[cdf["claim_id"].astype(str) == cid]

    def finish_review_item():
        st.session_state.review_queue = st.session_state.review_queue[1:]
        st.session_state.editor_version += 1
        st.session_state.map_nonce += 1

    if match.empty:
        finish_review_item()   # claim no longer exists; skip it
        st.rerun()

    row = match.iloc[0]
    position = st.session_state.get("review_total", len(review_queue)) - len(review_queue) + 1
    sched_note = ""
    if row["status"] == "Scheduled":
        s_dt = parse_wallclock(row.get("start_time"))
        sched_note = f"It's scheduled for **{fmt_dt(s_dt)}**." if s_dt else "It's scheduled."

    with st.container(border=True):
        st.caption(f"Reviewing updated list: {position} of {st.session_state.get('review_total', len(review_queue))}")

        if item["type"] == "missing":
            st.markdown(f"**{cid} - {row['insured_name']}** isn't in the new list. "
                        f"It may have been closed or reassigned. {sched_note}")
            st.caption(row["full_address"])
            b1, b2 = st.columns(2)
            if b1.button("Keep", use_container_width=True, key=f"rv_keep_{cid}",
                         help="Leaves this claim in your pool and schedule as it is."):
                finish_review_item()
                st.rerun()
            remove_label = "Remove from pool and schedule" if row["status"] == "Scheduled" else "Remove from pool"
            if b2.button(remove_label, type="primary", use_container_width=True, key=f"rv_remove_{cid}"):
                st.session_state.claims_df = cdf[cdf["claim_id"].astype(str) != cid].reset_index(drop=True)
                finish_review_item()
                st.toast(f"Removed {cid}")
                st.rerun()

        else:
            st.markdown(f"**{cid} - {row['insured_name']}** has a new address in this list. {sched_note}")
            st.markdown(f"Current: {item['old_address']}  \nNew: **{item['new_address']}**")
            if row.get("geo_quality") in GEO_REP_VERIFIED:
                st.caption(f"You {'placed' if row['geo_quality'] == GEO_MANUAL else 'confirmed'} this pin by hand. "
                           "Updating looks up the new address and replaces your pin.")
            b1, b2 = st.columns(2)
            if b1.button("Ignore", use_container_width=True, key=f"rv_ignore_{cid}",
                         help="Keeps the current address and pin."):
                finish_review_item()
                st.rerun()
            if b2.button("Update address", type="primary", use_container_width=True, key=f"rv_update_{cid}"):
                with st.spinner("Looking up the new address..."):
                    lat, lon, quality = batch_geocode_addresses([(item["new_address"], item.get("new_state", ""))])[0]
                mask = cdf["claim_id"].astype(str) == cid
                st.session_state.claims_df.loc[mask, "full_address"] = item["new_address"]
                if item.get("new_state"):
                    st.session_state.claims_df.loc[mask, "state"] = item["new_state"]
                st.session_state.claims_df.loc[mask, "lat"] = lat
                st.session_state.claims_df.loc[mask, "lon"] = lon
                st.session_state.claims_df.loc[mask, "geo_quality"] = quality
                finish_review_item()
                st.toast(f"Address updated for {cid}")
                st.rerun()


# =====================================================================
# DASHBOARD
# =====================================================================
if st.session_state.claims_df is not None:
    cdf = st.session_state.claims_df
    for required_col in ["scheduled_date", "inspection_time", "start_time", "end_time"]:
        if required_col not in cdf.columns:
            cdf[required_col] = ""
    for text_col in ["scheduled_date", "inspection_time"]:
        cdf[text_col] = cdf[text_col].fillna("").astype(str)
    if "priority" not in cdf.columns:
        cdf["priority"] = None
    if "geo_quality" not in cdf.columns:
        cdf["geo_quality"] = GEO_UNKNOWN
    for text_col in ["phone", "email", "activity_type", "contact_note", "first_booked_at", "last_exported"]:
        if text_col not in cdf.columns:
            cdf[text_col] = ""
        cdf[text_col] = cdf[text_col].apply(clean_text).astype(object)
    cdf["phone"] = cdf["phone"].apply(normalize_phone)
    cdf["geo_quality"] = cdf["geo_quality"].fillna(GEO_UNKNOWN).astype(str)
    cdf["lat"] = pd.to_numeric(cdf["lat"], errors="coerce")
    cdf["lon"] = pd.to_numeric(cdf["lon"], errors="coerce")

    # Keep priority as a float column (NaN = unranked) so it accepts both
    # integer ranks and blanks from the editor without dtype errors.
    cdf["priority"] = pd.to_numeric(cdf["priority"].apply(normalize_priority), errors="coerce").astype(float)

    df = st.session_state.claims_df
    review_mask = df["geo_quality"].isin(GEO_NEEDS_REVIEW)

    # --- STATUS STATS ---
    scheduled_count = int((df["status"] == "Scheduled").sum())
    stats = [
        ("Total claims", len(df), INK),
        ("Unscheduled", int((df["status"] == "Unscheduled").sum()), RED),
        ("Scheduled", scheduled_count, SCHEDULED_BLUE),
        ("Drafts", int((df["status"] == "Draft").sum()), DRAFT_BLUE),
        ("Ignored", int((df["status"] == "Ignored").sum()), IGNORED_GRAY),
        ("Location issues", int(review_mask.sum()), ISSUE_ORANGE),
    ]
    st.markdown(
        '<div class="cat-stats">' + "".join(
            f'<div class="cat-stat" style="--c:{color}">'
            f'<div class="cat-stat-value">{value}</div><div class="cat-stat-label">{label}</div></div>'
            for label, value, color in stats
        ) + "</div>",
        unsafe_allow_html=True
    )

    summ = st.session_state.get("plan_summary")
    if summ:
        line = f"Drafted {summ['placed']} appointment(s) across {summ['days']} day(s)."
        if summ["unplaced"]:
            line += (f" {len(summ['unplaced'])} claim(s) didn't fit and stay Unscheduled: "
                     + ", ".join(summ["unplaced"][:12]) + ("..." if len(summ["unplaced"]) > 12 else "") + ".")
        line += " Confirm each draft after the insured agrees: select it in the calendar or under Manage a claim."
        s1, s2 = st.columns([6, 1], vertical_alignment="center")
        s1.success(line)
        if s2.button("Dismiss", key="dismiss_plan"):
            st.session_state.pop("plan_summary", None)
            st.rerun()
    if st.session_state.get("draft_notice"):
        st.info(st.session_state.pop("draft_notice"))

    if review_mask.any():
        st.warning(f"{int(review_mask.sum())} claim(s) have an approximate or missing location. "
                   "Turn on **Fix pin locations** in the Map tab to confirm or move them.")

    st.markdown("---")

    if scheduled_count > 0:
        ics_data = export_claims_to_ics(df, ics_tz)
        st.download_button(
            label=f"📅 Export {scheduled_count} inspection(s) to Outlook ({tz_display} time)",
            data=ics_data,
            file_name="cat_inspection_schedule.ics",
            mime="text/calendar"
        )
        st.markdown(" ")

    tab_cal, tab_map = st.tabs(["Calendar", "Map"])

    # -----------------------------------------------------------------
    # CALENDAR
    # -----------------------------------------------------------------
    with tab_cal:
        scheduled_claims = df[df["status"].isin(["Scheduled", "Draft"])].copy()
        scheduled_claims["_start_dt"] = [parse_wallclock(v) for v in scheduled_claims["start_time"]]
        scheduled_claims["_end_dt"] = [parse_wallclock(v) for v in scheduled_claims["end_time"]]
        # Boolean Series (not a plain list): with zero scheduled claims, an empty list
        # would select zero COLUMNS instead of zero rows and drop "_start_dt".
        has_times = pd.Series(
            [s is not None and e is not None for s, e in zip(scheduled_claims["_start_dt"], scheduled_claims["_end_dt"])],
            index=scheduled_claims.index, dtype=bool
        )
        scheduled_claims = scheduled_claims.loc[has_times]

        # --- NEXT UP ---
        is_upcoming = pd.Series([s > now_local and st_ == "Scheduled"
                                 for s, st_ in zip(scheduled_claims["_start_dt"], scheduled_claims["status"])],
                                index=scheduled_claims.index, dtype=bool)
        upcoming = scheduled_claims.loc[is_upcoming]
        upcoming = upcoming.sort_values("_start_dt") if not upcoming.empty else upcoming
        next_id = str(upcoming.iloc[0]["claim_id"]) if not upcoming.empty else None

        if next_id:
            nr = upcoming.iloc[0]
            mins_until = int((nr["_start_dt"] - now_local).total_seconds() // 60)
            until_txt = f"{mins_until // 60}h {mins_until % 60}m" if mins_until >= 60 else f"{mins_until} min"
            with st.container(border=True):
                st.markdown(f"""
<div class="cat-card">
  <div class="cat-card-kicker">Next inspection, starts in {until_txt}</div>
  <div class="cat-card-title">{esc(nr['claim_id'])} - {esc(nr['insured_name'])}</div>
  <div class="cat-card-sub">{fmt_dt(nr['_start_dt'])}<br>{esc(nr['full_address'])}</div>
</div>""", unsafe_allow_html=True)
                render_nav_buttons(nr["full_address"], nr["lat"], nr["lon"], nr["geo_quality"])

        # --- EVENTS: past = hatched, next = amber, others = blue ---
        # Past blocks stay draggable in case the calendar wasn't kept up to date.
        # Drive time from each draft to the next on-site stop that day (a guide, not a rule)
        drive_next = {}
        if not scheduled_claims.empty:
            for _day, grp in scheduled_claims.groupby(scheduled_claims["_start_dt"].apply(lambda x: x.date())):
                stops = [r for _, r in grp.sort_values("_start_dt").iterrows()
                         if not is_video(r.get("activity_type")) and pd.notna(r["lat"]) and pd.notna(r["lon"])]
                for a, b in zip(stops, stops[1:]):
                    drive_next[str(a["claim_id"])] = get_osrm_route(float(a["lat"]), float(a["lon"]),
                                                                    float(b["lat"]), float(b["lon"]))[1]

        calendar_events = []
        for _, row in scheduled_claims.iterrows():
            cid = str(row["claim_id"])
            event = {
                "id": cid,
                "title": f"[{cid}] {row['insured_name']}",
                "start": row["_start_dt"].isoformat(),
                "end": row["_end_dt"].isoformat(),
                # Inspections can't be dragged or resized over each other
                "overlap": False,
            }
            if row["status"] == "Draft":
                nxt_txt = f" · {drive_next[cid]} min to next" if cid in drive_next else ""
                event.update({
                    "title": f"Draft · [{cid}] {row['insured_name']}{nxt_txt}",
                    "classNames": ["draft-event"],
                    "backgroundColor": "#2A3A4C" if CONSOLE else "#E6EEF8",
                    "borderColor": DRAFT_BLUE if CONSOLE else SCHEDULED_BLUE,
                    "textColor": "#C9D6E4" if CONSOLE else "#1D3A5F",
                })
            elif row["_end_dt"] <= now_local:
                event.update({
                    "classNames": ["past-event"],
                    "backgroundColor": "#3A4654" if CONSOLE else "#A3AFBF",
                    "borderColor": "#566373" if CONSOLE else "#7B8797",
                    "textColor": "#C3CFDB" if CONSOLE else "#1F2937",
                })
            elif cid == next_id:
                event.update({
                    "title": f"⏭️ {event['title']}",
                    "classNames": ["next-event"],
                    "backgroundColor": AMBER,
                    "borderColor": "#B7800F",
                    "textColor": "#111827",
                })
            elif is_video(row.get("activity_type")):
                # Live video: a lighter shade of the inspection blue
                event.update({"title": f"📹 {event['title']}", "backgroundColor": "#8DB0DC",
                              "borderColor": SCHEDULED_BLUE, "textColor": "#0F1E2E"})
            else:
                event.update({"backgroundColor": SCHEDULED_BLUE, "borderColor": STEEL})
            calendar_events.append(event)

        # --- SHADING: dates outside the inspection date range ---
        # (Inactive weekdays and off-hours are shaded by businessHours below.)
        def shade_range(d_from, d_to):
            if d_from >= d_to:
                return
            for all_day in (True, False):  # all-day version for month view, timed for week/day views
                calendar_events.append({
                    "start": d_from.isoformat() if all_day else f"{d_from.isoformat()}T00:00:00",
                    "end": d_to.isoformat() if all_day else f"{d_to.isoformat()}T00:00:00",
                    "allDay": all_day,
                    "display": "background",
                    "backgroundColor": IGNORED_GRAY,
                })

        shade_range(start_date - timedelta(days=28), start_date)
        shade_range(end_date + timedelta(days=1), end_date + timedelta(days=60))

        # --- OPEN TIME: light green behind the free parts of each working day ---
        cal_busy = get_busy_intervals(df)
        d = start_date
        while d <= end_date:
            if d.strftime("%a") in active_days:
                for g0, g1 in compute_day_gaps(d, start_time_input, inspections_per_day, window_hrs,
                                               cal_busy, now_local, latest_end_input):
                    calendar_events.append({
                        "start": g0.isoformat(), "end": g1.isoformat(),
                        "display": "background", "backgroundColor": "#22A05A",
                    })
            d += timedelta(days=1)

        # --- VISIBLE HOURS ---
        # Show until 7 PM by default, but extend to fit the inspection windows
        # and any inspection that runs later (or starts earlier) than that.
        def minutes_of_day(dt, base_date):
            if dt.date() > base_date:
                return 24 * 60
            return dt.hour * 60 + dt.minute

        day_start_dt = datetime.combine(start_date, start_time_input)
        day_end_dt = day_start_dt + timedelta(hours=inspections_per_day * window_hrs)
        window_end_min = minutes_of_day(day_end_dt, start_date)

        latest_min = max([19 * 60, window_end_min] +
                         [minutes_of_day(e, s.date()) for s, e in zip(scheduled_claims["_start_dt"], scheduled_claims["_end_dt"])])
        earliest_min = min([start_time_input.hour * 60 + start_time_input.minute] +
                           [s.hour * 60 + s.minute for s in scheduled_claims["_start_dt"]])
        slot_max_min = min(24 * 60, int(math.ceil(latest_min / 60.0)) * 60)
        slot_min_min = (earliest_min // 60) * 60

        def hhmm(total_min):
            return f"{total_min // 60:02d}:{total_min % 60:02d}:00"

        js_day = {"Sun": 0, "Mon": 1, "Tue": 2, "Wed": 3, "Thu": 4, "Fri": 5, "Sat": 6}

        calendar_options = {
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": "timeGridWeek,timeGridDay,dayGridMonth"},
            "initialView": "timeGridWeek",
            "initialDate": start_date.strftime("%Y-%m-%d"),
            "slotMinTime": hhmm(slot_min_min),
            "slotMaxTime": hhmm(slot_max_min),
            "expandRows": True,
            "allDaySlot": False,
            "editable": True,
            "selectable": True,
            "slotEventOverlap": True,
            # Drag and resize in 15-minute steps
            "snapDuration": "00:15:00",
            # Show stored times exactly as entered (deployment-local), regardless
            # of the time zone of the computer viewing the app.
            "timeZone": "UTC",
            # "now" in deployment-local time, so today's highlight and the
            # current-time line are correct for the deployment.
            "now": now_local.isoformat(),
            "nowIndicator": True,
            # 12-hour times
            "eventTimeFormat": {"hour": "numeric", "minute": "2-digit", "meridiem": "short"},
            "slotLabelFormat": {"hour": "numeric", "minute": "2-digit", "meridiem": "short"},
            # Gray shading outside your usual working hours and on non-inspection days
            "businessHours": {
                "daysOfWeek": [js_day[d] for d in active_days],
                "startTime": start_time_input.strftime("%H:%M"),
                "endTime": day_window(start_date, start_time_input, inspections_per_day, window_hrs,
                                      latest_end_input)[1].strftime("%H:%M"),
            },
            # Inspections can be dragged on inspection days from the day start into the
            # evening (insureds are often available late), but not onto days off.
            "eventConstraint": {
                "daysOfWeek": [js_day[d] for d in active_days],
                "startTime": start_time_input.strftime("%H:%M"),
                "endTime": "24:00",
            },
        }

        calendar_css = f"""
            @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
            .fc {{
                font-family: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
                --fc-border-color: {LINE};
                --fc-button-bg-color: #FFFFFF;
                --fc-button-border-color: {LINE};
                --fc-button-text-color: {INK};
                --fc-button-hover-bg-color: #EEF2F6;
                --fc-button-hover-border-color: #C9D3DD;
                --fc-button-active-bg-color: {STEEL};
                --fc-button-active-border-color: {STEEL};
                --fc-today-bg-color: rgba(232, 163, 23, 0.07);
                --fc-now-indicator-color: {RED};
                --fc-non-business-color: rgba(148, 163, 184, 0.22);
                --fc-neutral-bg-color: #F4F6F9;
            }}
            .fc .fc-toolbar-title {{ font-size: 1.05rem; font-weight: 600; color: {INK}; }}
            .fc .fc-button {{ font-size: 0.82rem; font-weight: 500; border-radius: 7px; box-shadow: none !important; text-transform: capitalize; }}
            .fc .fc-button-primary:not(:disabled).fc-button-active {{ color: #FFFFFF; }}
            .fc .fc-col-header-cell-cushion {{ color: {SLATE}; font-weight: 600; font-size: 0.82rem; text-decoration: none; }}
            .fc .fc-timegrid-slot-label-cushion {{ color: {SLATE}; font-size: 0.78rem; }}
            .fc .fc-daygrid-day-number {{ color: {SLATE}; text-decoration: none; }}
            .fc-event {{ border-radius: 6px; font-size: 0.8rem; }}
            .fc-event.past-event {{
                background-image: repeating-linear-gradient(
                    45deg, rgba(255,255,255,0.55) 0 5px, transparent 5px 10px) !important;
                opacity: 0.85;
            }}
            .fc-event.past-event .fc-event-title {{ text-decoration: line-through; }}
            .fc-event.next-event {{ box-shadow: 0 0 0 3px rgba(232, 163, 23, 0.45); font-weight: 600; }}
            .fc-event.draft-event {{ border-style: dashed !important; border-width: 2px !important; font-style: italic; }}
        """
        if CONSOLE:
            calendar_css += f"""
            @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap');
            html, body {{ background: {C_BG}; }}
            .fc {{
                color: {C_TEXT};
                background: {C_BG};
                --fc-page-bg-color: {C_BG};
                --fc-neutral-bg-color: {C_PANEL};
                --fc-border-color: {C_LINE};
                --fc-button-bg-color: {C_PANEL};
                --fc-button-border-color: {C_LINE};
                --fc-button-text-color: {C_TEXT};
                --fc-button-hover-bg-color: #18242F;
                --fc-button-hover-border-color: #2A3A4A;
                --fc-button-active-bg-color: #0891B2;
                --fc-button-active-border-color: {C_SIGNAL};
                --fc-today-bg-color: rgba(63, 208, 224, 0.06);
                --fc-now-indicator-color: {C_SIGNAL};
                --fc-non-business-color: rgba(0, 0, 0, 0.35);
                --fc-list-event-hover-bg-color: {C_PANEL};
            }}
            .fc .fc-toolbar-title {{ color: {C_TEXT}; font-family: {MONO}; font-weight: 500; font-size: 0.98rem; }}
            .fc .fc-col-header-cell-cushion, .fc .fc-timegrid-slot-label-cushion,
            .fc .fc-daygrid-day-number {{ color: {C_MUTED}; font-family: {MONO}; }}
            .fc-event {{ font-family: {MONO}; font-size: 0.76rem; }}
            .fc-event.past-event {{
                background-image: repeating-linear-gradient(
                    45deg, rgba(255,255,255,0.10) 0 5px, transparent 5px 10px) !important;
            }}
            .fc-event.next-event {{ box-shadow: 0 0 14px rgba(232, 163, 23, 0.55); }}
            """

        cal_event = calendar(
            events=calendar_events,
            options=calendar_options,
            custom_css=calendar_css,
            # Only click and drag/resize. The default also reports "eventsSet" on every
            # render, which reruns the whole app and keeps rebuilding the map.
            callbacks=["eventClick", "eventChange"],
            key="claims_calendar"
        ) or {}

        # --- CLICK A BLOCK: directions + manage ---
        clicked = (cal_event.get("eventClick") or {}).get("event") or {}
        clicked_id = str(clicked.get("id") or "")
        if clicked_id:
            c_rows = df[(df["claim_id"].astype(str) == clicked_id) & (df["status"].isin(["Scheduled", "Draft"]))]
            if not c_rows.empty:
                c_row = c_rows.iloc[0]
                with st.container(border=True):
                    st.markdown(f"""
<div class="cat-card selected">
  <div class="cat-card-kicker">{'Draft appointment (not confirmed yet)' if c_row['status'] == 'Draft' else 'Selected inspection'}</div>
  <div class="cat-card-title">{esc(c_row['claim_id'])} - {esc(c_row['insured_name'])}</div>
  <div class="cat-card-sub">{fmt_dt(parse_wallclock(c_row['start_time']))}<br>{esc(c_row['full_address'])}</div>
</div>""", unsafe_allow_html=True)
                    render_nav_buttons(c_row["full_address"], c_row["lat"], c_row["lon"], c_row["geo_quality"])
                    if c_row["status"] == "Draft":
                        if st.button("✓ Confirm this time", key=f"cal_confirm_{clicked_id}", type="primary",
                                     help="The insured agreed. Confirms the appointment and records the initial contact."):
                            confirm_draft(clicked_id)
                            st.rerun()
                    if st.button("Manage this claim", key=f"cal_manage_{clicked_id}"):
                        st.session_state["selected_claim_id"] = clicked_id
                        st.rerun()

        # --- DRAG / RESIZE A BLOCK ---
        # The calendar keeps returning its last event on every rerun, so only
        # apply a given change once (otherwise the app can loop on reruns).
        if cal_event.get("eventChange"):
            changed_event = cal_event["eventChange"]["event"]
            change_sig = (str(changed_event.get("id")), changed_event.get("start"), changed_event.get("end"))
            if st.session_state.get("last_calendar_change") != change_sig:
                st.session_state["last_calendar_change"] = change_sig
                cid = str(changed_event["id"])
                new_start = parse_wallclock(changed_event["start"])
                new_end = parse_wallclock(changed_event.get("end")) or (new_start + timedelta(hours=window_hrs))

                c_mask = st.session_state.claims_df["claim_id"].astype(str) == cid
                st.session_state.claims_df.loc[c_mask, "start_time"] = new_start.isoformat()
                st.session_state.claims_df.loc[c_mask, "end_time"] = new_end.isoformat()
                st.session_state.claims_df.loc[c_mask, "scheduled_date"] = new_start.strftime("%Y-%m-%d")
                st.session_state.claims_df.loc[c_mask, "inspection_time"] = new_start.strftime("%H:%M")
                st.session_state.editor_version += 1
                st.toast(f"Moved {cid} to {fmt_dt(new_start)}")
                st.rerun()

    # -----------------------------------------------------------------
    # MAP
    # Runs as a fragment: clicking or panning the map reruns only this
    # section, not the whole page, so the map isn't rebuilt by unrelated
    # parts of the app while you're fixing pins.
    # -----------------------------------------------------------------
    @st.fragment
    def render_map_tab():
        mdf = st.session_state.claims_df
        m_review = mdf["geo_quality"].isin(GEO_NEEDS_REVIEW)

        fix_mode = st.toggle(
            "Fix pin locations",
            key="pin_fix_mode",
            help="Zoom to a claim on the satellite view, click the right roof, and save. "
                 "Or paste coordinates from Google Maps."
        )

        fix_row = None
        if fix_mode:
            # Claims that need a check come first
            fix_order = mdf.assign(_ok=~m_review).sort_values("_ok", kind="mergesort")
            fix_map = {}
            for _, r in fix_order.iterrows():
                flag = "⚠️ " if r["geo_quality"] in GEO_NEEDS_REVIEW else ""
                fix_map[f"{flag}{r['claim_id']} - {r['insured_name']} ({r['geo_quality']})"] = str(r["claim_id"])
            pending = st.session_state.pop("pending_fix_claim_id", None)
            if pending:
                pending_label = next((lbl for lbl, cid in fix_map.items() if cid == pending), None)
                if pending_label:
                    st.session_state["pin_fix_claim"] = pending_label
            if st.session_state.get("pin_fix_claim") not in fix_map:
                st.session_state.pop("pin_fix_claim", None)
            if st.session_state.pop("all_pins_checked", False):
                st.success("All flagged locations are checked.")
            fix_label = st.selectbox("Claim to fix", list(fix_map.keys()), key="pin_fix_claim")
            fix_id = fix_map[fix_label]
            fix_row = mdf[mdf["claim_id"].astype(str) == fix_id].iloc[0]
            st.caption(f"{fix_row['full_address']}")

        valid_coords_df = mdf[(mdf["status"] != "Ignored") & (mdf["lat"].notna()) & (mdf["lon"].notna())]
        hidden_pins = 0

        if fix_row is not None and pd.notna(fix_row["lat"]) and pd.notna(fix_row["lon"]):
            map_center, map_zoom = [float(fix_row["lat"]), float(fix_row["lon"])], 18
        elif fix_row is not None and hotel_coords:
            map_center, map_zoom = list(hotel_coords), 13
        elif not valid_coords_df.empty:
            # Default view: the ~90% of pins nearest the middle of the group, so a
            # far-off pin or two doesn't zoom the map way out. The hotel is included
            # when it's in or near that area.
            all_pts = valid_coords_df[["lat", "lon"]].astype(float).values.tolist()
            view_pts, hidden_pins = core_view_points(all_pts)
            if hotel_coords:
                lat_lo, lat_hi = min(p[0] for p in view_pts), max(p[0] for p in view_pts)
                lon_lo, lon_hi = min(p[1] for p in view_pts), max(p[1] for p in view_pts)
                pad_lat, pad_lon = (lat_hi - lat_lo) * 0.25, (lon_hi - lon_lo) * 0.25
                if (lat_lo - pad_lat <= hotel_coords[0] <= lat_hi + pad_lat and
                        lon_lo - pad_lon <= hotel_coords[1] <= lon_hi + pad_lon):
                    view_pts = view_pts + [list(hotel_coords)]
            map_center, map_zoom = view_center_zoom(view_pts)
        elif hotel_coords:
            map_center, map_zoom = list(hotel_coords), 12
        else:
            map_center, map_zoom = [29.4241, -98.4936], 10

        m = folium.Map(location=map_center, zoom_start=map_zoom, tiles=None, max_zoom=20)

        esri_satellite_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        if CONSOLE:
            street_layer = folium.TileLayer("CartoDB dark_matter", name="Street map", show=not fix_mode, max_zoom=20)
        else:
            street_layer = folium.TileLayer("OpenStreetMap", name="Street map", show=not fix_mode, max_zoom=20)
        satellite_layer = folium.TileLayer(tiles=esri_satellite_url, attr="Esri World Imagery",
                                           name="Satellite", show=fix_mode, max_zoom=20, max_native_zoom=19)
        # The first base layer added is the one shown; satellite first when fixing pins
        for layer in ([satellite_layer, street_layer] if fix_mode else [street_layer, satellite_layer]):
            layer.add_to(m)

        day_colors = ["blue", "green", "purple", "darkblue", "darkred", "cadetblue", "darkgreen", "pink"]
        scheduled_dates = sorted([d for d in mdf[mdf["status"].isin(["Scheduled", "Draft"])]["scheduled_date"].unique() if d])
        date_color_map = {d: day_colors[i % len(day_colors)] for i, d in enumerate(scheduled_dates)}

        bounds = []
        for _, row in mdf.iterrows():
            if row["status"] == "Ignored" or pd.isna(row["lat"]) or pd.isna(row["lon"]):
                continue

            lat = float(row["lat"])
            lon = float(row["lon"])
            needs_review = row["geo_quality"] in GEO_NEEDS_REVIEW
            is_fix_target = fix_row is not None and str(row["claim_id"]) == str(fix_row["claim_id"])

            # Pin style:
            #   color = status (red = unscheduled; scheduled = one color per day)
            #   "!"   = location needs checking (approximate)
            #   none  = unscheduled with a good location; check = scheduled with a good location
            if is_fix_target:
                marker_color, icon_type = "orange", "screenshot"
            elif row["status"] == "Unscheduled":
                marker_color = "red"
                icon_type = "exclamation-sign" if needs_review else ""
            else:
                marker_color = date_color_map.get(row.get("scheduled_date"), "blue")
                icon_type = "exclamation-sign" if needs_review else (
                    "hourglass" if row["status"] == "Draft" else
                    "facetime-video" if is_video(row.get("activity_type")) else "ok-sign")

            nav = build_navigation_links(row["full_address"], lat, lon, prefer_coords=(row["geo_quality"] in GEO_REP_VERIFIED))
            links_html = " &nbsp; ".join(
                f'<a href="{url}" target="_blank" rel="noopener">{name}</a>'
                for name, url in [("Google Maps", nav.get("google")), ("Apple Maps", nav.get("apple"))] if url
            )
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(
                    f"<b>{esc(row['claim_id'])}</b><br>{esc(row['insured_name'])}<br>{esc(row['full_address'])}"
                    f"<br><span style='color:#52637A'>Location: {esc(row['geo_quality'])}</span><br>{links_html}",
                    max_width=280
                ),
                tooltip=f"{row['claim_id']} - {row['insured_name']}" + (" (location needs checking)" if needs_review else ""),
                icon=folium.Icon(color=marker_color, icon=icon_type)
            ).add_to(m)

            bounds.append([lat, lon])

        if hotel_coords:
            folium.Marker(
                location=list(hotel_coords),
                popup=f"<b>Hotel base</b><br>{esc(hotel_address)}",
                tooltip="Hotel base",
                icon=folium.Icon(color="black", icon="home")
            ).add_to(m)


        folium.LayerControl().add_to(m)

        map_key = f"claims_map_{st.session_state.map_nonce}_{fix_row['claim_id'] if fix_row is not None else 'all'}"

        # In fix mode, show a crosshair where you last clicked. It's drawn as a separate
        # layer so the map updates in place instead of reloading and losing your zoom.
        preview_group = None
        if fix_mode:
            prev_state = st.session_state.get(map_key) or {}
            prev_click = prev_state.get("last_clicked") if isinstance(prev_state, dict) else None
            preview_group = folium.FeatureGroup(name="Selected spot")
            if prev_click:
                folium.CircleMarker(
                    location=[prev_click["lat"], prev_click["lng"]],
                    radius=9, color="#FFFFFF", weight=3, fill=True,
                    fill_color=AMBER, fill_opacity=0.9,
                    tooltip="New spot (not saved yet)"
                ).add_to(preview_group)

        try:
            map_state = st_folium(m, width=1100, height=540, key=map_key,
                                  returned_objects=["last_clicked"],
                                  feature_group_to_add=preview_group) or {}
        except TypeError:
            # Older streamlit-folium without feature_group_to_add
            map_state = st_folium(m, width=1100, height=540, key=map_key,
                                  returned_objects=["last_clicked"]) or {}

        st.caption("Red pins are unscheduled. Scheduled pins are colored by day, with a check mark "
                   "(an hourglass for drafts not confirmed yet). "
                   "A **!** means the location is approximate and should be checked.")
        if hidden_pins:
            st.caption(f"{hidden_pins} pin(s) far from the rest are outside this view. Zoom out to see them.")

        if fix_mode and fix_row is not None:
            has_pin = pd.notna(fix_row["lat"]) and pd.notna(fix_row["lon"])
            if has_pin and fix_row["geo_quality"] not in GEO_REP_VERIFIED:
                if st.button("✓ Pin is correct", type="primary", key=f"confirm_pin_{fix_row['claim_id']}",
                             help="Keeps the pin where it is and marks the location as checked."):
                    confirm_pin(fix_row["claim_id"])
                    queue_next_pin_to_fix(fix_row["claim_id"])
                    st.rerun()
            elif fix_row["geo_quality"] in GEO_REP_VERIFIED:
                st.caption(f"✓ {fix_row['geo_quality']}. You can still move it below.")
            fc1, fc2 = st.columns(2)
            with fc1:
                clicked_pt = map_state.get("last_clicked")
                if clicked_pt:
                    st.markdown(f"Selected spot  \n`{clicked_pt['lat']:.6f}, {clicked_pt['lng']:.6f}`")
                    if st.button(f"Move {fix_row['claim_id']} pin here"):
                        save_manual_pin(fix_row["claim_id"], clicked_pt["lat"], clicked_pt["lng"])
                        queue_next_pin_to_fix(fix_row["claim_id"])
                        st.rerun()
                else:
                    st.caption("Click the map to choose the spot for this claim.")
            with fc2:
                pasted = st.text_input("Or paste coordinates or a Google Maps link",
                                       key=f"paste_coords_{fix_row['claim_id']}",
                                       placeholder="29.4241, -98.4936")
                if st.button("Save pasted location", key=f"save_paste_{fix_row['claim_id']}"):
                    coords = parse_coordinates(pasted)
                    if coords:
                        save_manual_pin(fix_row["claim_id"], coords[0], coords[1])
                        queue_next_pin_to_fix(fix_row["claim_id"])
                        st.rerun()
                    else:
                        st.error("No coordinates found. Paste something like 29.4241, -98.4936 "
                                 "or a Google Maps link that contains them.")

    with tab_map:
        render_map_tab()

    st.markdown("---")

    # --- MANAGEMENT & CLAIMS POOL ---
    col_left, col_right = st.columns([1.5, 1])

    with col_left:
        st.subheader("Claims pool")
        st.caption("Edit priority, status, contact details and notes right in the table. Click a column "
                   "header to sort. Check **Export** to choose claims for the claim platform export below.")

        if st.session_state.get("editor_notice"):
            st.warning(st.session_state.pop("editor_notice"))

        if "export_ids" not in st.session_state:
            st.session_state.export_ids = set()

        show_status = st.multiselect("Show statuses", ["Unscheduled", "Draft", "Scheduled", "Ignored"],
                                     default=["Unscheduled", "Draft", "Scheduled"])
        view = df[df["status"].isin(show_status)]

        # Table shown to the rep: friendly columns, using the claim platform's header names
        def last_exported_label(v):
            dt = parse_wallclock(v)
            return dt.strftime("%m/%d/%Y %I:%M %p") if dt else ""

        rows = {}
        for i, r in view.iterrows():
            contact_dt = parse_wallclock(r.get("first_booked_at"))
            act_dt = parse_wallclock(r.get("start_time")) if r["status"] == "Scheduled" else None
            c_date, c_time, c_ap = split_12h(contact_dt)
            a_date, a_time, a_ap = split_12h(act_dt)
            rows[i] = {
                "Export": str(r["claim_id"]) in st.session_state.export_ids,
                "Claim": str(r["claim_id"]),
                "Insured": r["insured_name"],
                "Address": r["full_address"],
                "Priority": normalize_priority(r["priority"]),
                "Status": r["status"],
                "Phone Number": r.get("phone", ""),
                "Email": r.get("email", ""),
                "Type of Contact": "Initial contact" if contact_dt else "",
                "Date Contact Completed": c_date,
                "Time Contact Completed": c_time,
                "Contact AM or PM": c_ap,
                "Type of Activity": r.get("activity_type", ""),
                "Date Activity Completed": a_date,
                "Time Activity Completed": a_time,
                "Activity AM or PM": a_ap,
                "Initial Contact Note": r.get("contact_note", ""),
                "Location": r["geo_quality"],
                "Last Exported": last_exported_label(r.get("last_exported")),
            }
        table = pd.DataFrame.from_dict(rows, orient="index")
        if not table.empty:
            table["Priority"] = pd.to_numeric(table["Priority"], errors="coerce").astype("Int64")

        editor_key = f"claims_editor_{st.session_state.editor_version}_{'_'.join(sorted(show_status))}"
        edited = st.data_editor(
            table,
            key=editor_key,
            disabled=["Claim", "Insured", "Address", "Type of Contact", "Date Activity Completed",
                      "Time Activity Completed", "Activity AM or PM", "Location", "Last Exported"],
            column_config={
                "Export": st.column_config.CheckboxColumn("Export", help="Include in the claim platform export."),
                "Priority": st.column_config.NumberColumn("Priority", help="1 = highest. Leave blank for unranked claims.",
                                                          min_value=1, step=1, format="%d"),
                "Status": st.column_config.SelectboxColumn(
                    "Status", options=["Unscheduled", "Draft", "Scheduled", "Ignored"], required=True,
                    help="Schedule a claim from Manage a claim, so it gets a real time. "
                         "Changing a Draft to Scheduled confirms it."),
                "Type of Contact": st.column_config.TextColumn(
                    "Type of Contact", help="Initial contact, once a contact date and time are recorded."),
                "Date Contact Completed": st.column_config.TextColumn(
                    "Date Contact Completed", help="Recorded when the claim is first booked. Format: 10/07/2026"),
                "Time Contact Completed": st.column_config.TextColumn("Time Contact Completed", help="Format: 2:15"),
                "Contact AM or PM": st.column_config.SelectboxColumn("Contact AM or PM", options=["", "AM", "PM"]),
                "Type of Activity": st.column_config.SelectboxColumn("Type of Activity", options=[""] + ACTIVITY_OPTIONS),
                "Date Activity Completed": st.column_config.TextColumn(
                    "Date Activity Completed", help="The inspection date, from the schedule."),
                "Time Activity Completed": st.column_config.TextColumn(
                    "Time Activity Completed", help="The inspection start time, from the schedule."),
                "Initial Contact Note": st.column_config.TextColumn(
                    "Initial Contact Note", max_chars=NOTE_MAX_CHARS, width="large"),
                "Location": st.column_config.TextColumn("Location", help="How the map pin was placed."),
            },
            hide_index=True,
            use_container_width=True
        )

        # --- SYNC TABLE EDITS BACK INTO THE CLAIMS ---
        # The table keeps the claims' row index, so each edited row maps straight back.
        cdf = st.session_state.claims_df
        changes_made, blocked_claims, bad_times = False, [], []

        for row_idx in edited.index:
            old, new = table.loc[row_idx], edited.loc[row_idx]
            cid = str(old["Claim"])

            if bool(new["Export"]) != bool(old["Export"]):
                (st.session_state.export_ids.add if new["Export"] else st.session_state.export_ids.discard)(cid)

            old_prio, new_prio = normalize_priority(old["Priority"]), normalize_priority(new["Priority"])
            if new_prio != old_prio:
                cdf.at[row_idx, "priority"] = new_prio if new_prio is not None else float("nan")
                changes_made = True

            if new["Status"] != old["Status"]:
                if new["Status"] in ("Unscheduled", "Ignored"):
                    cdf.at[row_idx, "status"] = new["Status"]
                    cdf.at[row_idx, "start_time"] = None
                    cdf.at[row_idx, "end_time"] = None
                    cdf.at[row_idx, "scheduled_date"] = ""
                    cdf.at[row_idx, "inspection_time"] = ""
                    changes_made = True
                elif new["Status"] == "Scheduled" and old["Status"] == "Draft":
                    confirm_draft(cid)   # confirms at the drafted time, records initial contact
                    changes_made = True
                else:
                    blocked_claims.append(cid)

            for col, field, fix in [("Phone Number", "phone", normalize_phone),
                                    ("Email", "email", clean_text),
                                    ("Type of Activity", "activity_type", clean_text),
                                    ("Initial Contact Note", "contact_note", lambda v: clean_text(v)[:NOTE_MAX_CHARS])]:
                if clean_text(new[col]) != clean_text(old[col]):
                    cdf.at[row_idx, field] = fix(new[col])
                    changes_made = True

            contact_cols = ["Date Contact Completed", "Time Contact Completed", "Contact AM or PM"]
            if any(clean_text(new[c]) != clean_text(old[c]) for c in contact_cols):
                dt, err = parse_date_time_12h(*(new[c] for c in contact_cols))
                if err:
                    bad_times.append(f"{cid}: {err}")
                else:
                    cdf.at[row_idx, "first_booked_at"] = dt.isoformat() if dt else ""
                    changes_made = True

        notices = []
        if blocked_claims:
            notices.append(f"Claim(s) {', '.join(blocked_claims)} weren't scheduled. Select the claim under "
                           "Manage a claim to pick a time.")
        if bad_times:
            notices.append("Contact date or time not saved. " + "; ".join(bad_times) + ".")
        if notices:
            st.session_state["editor_notice"] = " ".join(notices)

        if changes_made or blocked_claims or bad_times:
            st.session_state.editor_version += 1
            st.rerun()

        # --- EXPORT FOR THE CLAIM PLATFORM ---
        valid_ids = {str(c) for c in cdf["claim_id"]}
        st.session_state.export_ids &= valid_ids
        n_sel = len(st.session_state.export_ids)

        def select_contacted():
            st.session_state.export_ids = {str(c) for c, f in zip(st.session_state.claims_df["claim_id"],
                                                                st.session_state.claims_df["first_booked_at"])
                                           if clean_text(f)}
            st.session_state.editor_version += 1

        def clear_selection():
            st.session_state.export_ids = set()
            st.session_state.editor_version += 1

        def mark_exported(ids):
            stamp = now_local.replace(second=0, microsecond=0).isoformat()
            m = st.session_state.claims_df["claim_id"].astype(str).isin(ids)
            st.session_state.claims_df.loc[m, "last_exported"] = stamp
            st.session_state.editor_version += 1

        e1, e2, e3 = st.columns([1.2, 0.8, 1.3], vertical_alignment="center")
        e1.button("Select claims with initial contact", on_click=select_contacted, use_container_width=True)
        e2.button("Clear selection", on_click=clear_selection, use_container_width=True, disabled=n_sel == 0)
        export_ids = sorted(st.session_state.export_ids)
        e3.download_button(
            f"⬇️ Export {n_sel} for claim platform",
            data=build_export_table(cdf, export_ids).to_csv(index=False).encode("utf-8"),
            file_name=f"claim_platform_export_{now_local.strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            type="primary",
            disabled=n_sel == 0,
            use_container_width=True,
            on_click=mark_exported,
            args=(export_ids,),
        )
        st.caption("Save progress (in the sidebar) still saves everything. This export holds only the claim "
                   "platform columns for the selected claims, and stamps them with the export time.")

    # Default day for "Fill an opening": the first suggested opening in the chosen fill order
    selected_target_date_str = all_slots[0]["date_str"] if all_slots else start_date.strftime("%Y-%m-%d")

    with col_right:
        st.subheader("Manage a claim")
        claim_options = df["display_label"].tolist()

        if "managed_claim_select" not in st.session_state or st.session_state["managed_claim_select"] not in claim_options:
            st.session_state["managed_claim_select"] = claim_options[0]

        if "selected_claim_id" in st.session_state and st.session_state["selected_claim_id"]:
            matching = [opt for opt in claim_options if opt.startswith(str(st.session_state["selected_claim_id"]) + " -")]
            if matching:
                st.session_state["managed_claim_select"] = matching[0]
            del st.session_state["selected_claim_id"]

        selected_label = st.selectbox(
            "Claim",
            claim_options,
            key="managed_claim_select"
        )

        if selected_label:
            selected_claim_id = selected_label.split(" - ")[0].strip()
            claim_mask = st.session_state.claims_df["claim_id"].astype(str) == selected_claim_id
            
            if claim_mask.any():
                current_claim = st.session_state.claims_df[claim_mask].iloc[0]
                
                loc_note = current_claim["geo_quality"]
                if loc_note in GEO_NEEDS_REVIEW:
                    loc_note = f":orange[⚠️ {loc_note}]. Fix it in the Map tab."
                st.markdown(
                    f"**Claim:** `{current_claim['claim_id']}`  \n"
                    f"**Insured:** {current_claim['insured_name']}  \n"
                    f"**Address:** {current_claim['full_address']}  \n"
                    f"**Location:** {loc_note}  \n"
                    f"**Status:** `{current_claim['status']}`"
                )
                render_nav_buttons(current_claim["full_address"], current_claim["lat"], current_claim["lon"], current_claim["geo_quality"])

                # --- Initial contact details (all optional) ---
                ck = f"contact_{selected_claim_id}_{st.session_state.editor_version}"
                first_dt = parse_wallclock(current_claim.get("first_booked_at"))
                with st.expander("Initial contact", expanded=False):
                    st.caption(
                        f"Initial contact: **{first_dt.strftime('%m/%d/%Y %I:%M %p')}** (recorded when first booked)"
                        if first_dt else "Initial contact is recorded automatically the first time this claim is booked."
                    )
                    phone_in = st.text_input("Best contact number", value=current_claim.get("phone", ""), key=f"{ck}_phone")
                    email_in = st.text_input("Email", value=current_claim.get("email", ""), key=f"{ck}_email")
                    cur_act = current_claim.get("activity_type") or ACTIVITY_ONSITE
                    act_in = st.selectbox("Type of activity", ACTIVITY_OPTIONS, key=f"{ck}_act",
                                          index=ACTIVITY_OPTIONS.index(cur_act) if cur_act in ACTIVITY_OPTIONS else 0,
                                          help="Live video inspections default to 1 hour and don't count as "
                                               "a location for drive times.")
                    note_in = st.text_area("Initial Contact Discussion & Notes", value=current_claim.get("contact_note", ""),
                                           max_chars=NOTE_MAX_CHARS, key=f"{ck}_note", height=120)
                    if st.button("Save contact details", key=f"{ck}_save"):
                        st.session_state.claims_df.loc[claim_mask, "phone"] = normalize_phone(phone_in)
                        st.session_state.claims_df.loc[claim_mask, "email"] = email_in.strip()
                        st.session_state.claims_df.loc[claim_mask, "activity_type"] = act_in
                        st.session_state.claims_df.loc[claim_mask, "contact_note"] = note_in.strip()[:NOTE_MAX_CHARS]
                        st.session_state.editor_version += 1
                        st.toast(f"Contact details saved for {selected_claim_id}")
                        st.rerun()
                claim_length = VIDEO_DEFAULT_HRS if is_video(current_claim.get("activity_type")) else None

                st.markdown("---")

                if current_claim["status"] == "Scheduled":
                    if current_claim["scheduled_date"]:
                        selected_target_date_str = str(current_claim["scheduled_date"])

                    st.write(f"**Currently:** {fmt_dt(parse_wallclock(current_claim['start_time'])) or 'no time set'}")

                    move_slot = render_slot_picker(
                        selected_claim_id, st.session_state.claims_df, now_local, schedule_settings,
                        current=(parse_wallclock(current_claim["start_time"]), parse_wallclock(current_claim["end_time"])),
                        default_hrs=claim_length
                    )
                    if move_slot:
                        if st.button("🔁 Move to this slot", type="primary"):
                            book_claim_into_slot(claim_mask, move_slot)
                            st.rerun()

                    if st.button("Remove from schedule"):
                        st.session_state.claims_df.loc[claim_mask, "status"] = "Unscheduled"
                        st.session_state.claims_df.loc[claim_mask, "start_time"] = None
                        st.session_state.claims_df.loc[claim_mask, "end_time"] = None
                        st.session_state.claims_df.loc[claim_mask, "scheduled_date"] = ""
                        st.session_state.claims_df.loc[claim_mask, "inspection_time"] = ""
                        st.session_state.editor_version += 1
                        st.rerun()

                elif current_claim["status"] == "Draft":
                    d_start, d_end = parse_wallclock(current_claim["start_time"]), parse_wallclock(current_claim["end_time"])
                    if d_start:
                        selected_target_date_str = d_start.strftime("%Y-%m-%d")
                    st.markdown(f"**Draft:** {fmt_dt(d_start)} to {d_end.strftime('%I:%M %p').lstrip('0') if d_end else ''}, "
                                "not confirmed yet")
                    if st.button("✓ Confirm this time", type="primary", key=f"confirm_{selected_claim_id}",
                                 help="The insured agreed. Confirms the appointment and records the initial contact."):
                        confirm_draft(selected_claim_id)
                        st.rerun()
                    st.caption("Insured wants a different time? Pick it below, then confirm.")
                    alt_slot = render_slot_picker(
                        selected_claim_id, st.session_state.claims_df, now_local, schedule_settings,
                        current=(d_start, d_end), default_hrs=claim_length
                    )
                    if alt_slot and st.button("Confirm at this time", key=f"confirm_alt_{selected_claim_id}"):
                        book_claim_into_slot(claim_mask, alt_slot)
                        st.rerun()
                    if st.button("Send back to Unscheduled", key=f"undraft_{selected_claim_id}"):
                        set_claim_times(selected_claim_id, "Unscheduled")
                        st.session_state.editor_version += 1
                        st.rerun()

                elif current_claim["status"] in ["Unscheduled", "Ignored"]:
                    chosen_slot = render_slot_picker(selected_claim_id, st.session_state.claims_df,
                                                     now_local, schedule_settings, default_hrs=claim_length)
                    if chosen_slot:
                        selected_target_date_str = chosen_slot["date_str"]
                        if st.button("Book this slot", type="primary"):
                            book_claim_into_slot(claim_mask, chosen_slot)
                            st.rerun()

    # -----------------------------------------------------------------
    # RECOMMENDATIONS
    # -----------------------------------------------------------------
    st.markdown("---")
    st.subheader("Fill an opening")

    open_slots = [
        s for s in all_slots
        if parse_wallclock(s["start"]) > now_local
        and not is_slot_conflicting(s, st.session_state.claims_df, current_claim_id="")
    ]

    if not open_slots:
        st.info("No open slots left in this date range. Extend the end date or add inspections per day in the sidebar.")
    else:
        rc1, rc2 = st.columns([1.3, 1])
        with rc1:
            # Default to the first opening on the date in context (selected claim / chosen slot)
            default_idx = next((i for i, s in enumerate(open_slots) if s["date_str"] == selected_target_date_str), 0)
            opening_label = st.selectbox("Opening", [s["slot_label"] for s in open_slots], index=default_idx)
            opening = next(s for s in open_slots if s["slot_label"] == opening_label)
        with rc2:
            pool_choice = st.radio(
                "Show",
                ["Unscheduled", "Scheduled (reschedule)", "Both"],
                horizontal=True,
                key="rec_pool",
                help="Scheduled claims are shown as candidates to move into this opening. "
                     "Inspections that have already started are left out."
            )
        include = {
            "Unscheduled": ("Unscheduled",),
            "Scheduled (reschedule)": ("Scheduled",),
            "Both": ("Unscheduled", "Scheduled"),
        }[pool_choice]

        recs, anchor_info = get_recommendations_for_slot(
            st.session_state.claims_df,
            opening,
            hotel_coords=hotel_coords,
            include_statuses=include,
            now_local=now_local,
            mode=REC_MODE
        )

        nxt = anchor_info.get("next")
        if REC_MODE == "detour" and nxt:
            st.caption(f"Ranked by added driving between **{anchor_info['label']}** and **{nxt['label']}**. "
                       "Ranked claims (❗) still come first by priority.")
        elif REC_MODE == "detour":
            st.caption(f"Drive times from **{anchor_info['label']}**. Set a hotel address so the last stop "
                       "of the day can favor claims on the way back. Ranked claims (❗) come first.")
        else:
            st.caption(f"Drive times from **{anchor_info['label']}**. Ranked claims (❗) come first by priority; "
                       "drive time breaks ties and orders unranked claims.")

        if recs is None or recs.empty:
            st.info("No claims match this opening. Try showing both unscheduled and scheduled claims.")
        else:
            opening_time = parse_wallclock(opening["start"]).strftime("%I:%M %p").lstrip("0")
            for idx, rec_row in recs.head(5).reset_index(drop=True).iterrows():
                with st.container(border=True):
                    col_rec1, col_rec2, col_rec3 = st.columns([3, 0.9, 0.7], vertical_alignment="center")
                    with col_rec1:
                        claim_label = f"{rec_row['claim_id']} - {rec_row['insured_name']}"
                        rank = normalize_priority(rec_row.get("priority_rank"))

                        # Ranked claim: bold red ❗ badge; unranked: no badge, proximity only
                        title = f":red[**❗ P{rank}**] **{claim_label}**" if rank is not None else f"**{claim_label}**"
                        if rec_row["rec_type"] == "Reschedule":
                            title += f" :blue[🔁 currently {rec_row['current_slot']}]"

                        if pd.notna(rec_row["drive_time_mins"]) and rec_row["drive_time_mins"] is not None:
                            approx = "≈ " if rec_row["geo_quality"] in GEO_NEEDS_REVIEW else ""
                            drive_txt = f"⏱️ {approx}{int(rec_row['drive_time_mins'])} min · {rec_row['drive_miles']} mi"
                            detour = rec_row.get("detour_mins")
                            if REC_MODE == "detour" and detour is not None and pd.notna(detour):
                                drive_txt += f" · adds {int(detour)} min to your route"
                                if rec_row.get("late_for_next"):
                                    drive_txt += (f"  \n:orange[⚠️ {int(rec_row['drive_to_next_mins'])} min drive to "
                                                  f"{nxt['label']}. You may be late.]")
                        elif rec_row.get("is_video"):
                            drive_txt = "📹 Live video inspection, no drive needed (books 1 hour)"
                        else:
                            drive_txt = ":orange[📍 No map pin yet. Set it in the Map tab.]"

                        st.markdown(f"{title}  \n{rec_row['full_address']}  \n{drive_txt}")
                    with col_rec2:
                        action = f"🔁 Move to {opening_time}" if rec_row["rec_type"] == "Reschedule" else f"📌 Book {opening_time}"
                        if st.button(action, key=f"btn_book_{idx}_{rec_row['claim_id']}", use_container_width=True,
                                     type="primary" if idx == 0 else "secondary"):
                            mask = st.session_state.claims_df["claim_id"].astype(str) == str(rec_row["claim_id"])
                            slot_to_book = opening
                            if rec_row.get("is_video"):
                                slot_to_book = make_slot(parse_wallclock(opening["start"]), VIDEO_DEFAULT_HRS)
                            book_claim_into_slot(mask, slot_to_book)
                            st.toast(f"Booked {rec_row['claim_id']} for {opening_label}")
                            st.rerun()
                    with col_rec3:
                        if st.button("Manage", key=f"btn_rec_{idx}_{rec_row['claim_id']}", use_container_width=True):
                            st.session_state["selected_claim_id"] = str(rec_row["claim_id"])
                            st.rerun()
