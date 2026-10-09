import html
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
    per_day_for,
    active_days_from,
    typical_drive_minutes,
    estimated_return,
    leave_by,
    LEAVE_BUFFER_MIN,
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
#   Red: main action buttons and selected states only, used sparingly.
#   Dark red: hover/pressed on red buttons.
#   Navy: header and scheduled inspections.  Gray scale: text and borders.
#   Teal: links and clickable items only.  Gold: small non-interactive accents.
#   No red for errors, no red text on dark backgrounds, no see-through red.
# =====================================================================
BRAND_RED = "#E01719"
BRAND_DARK_RED = "#AF1214"
NAVY = "#003557"
TEAL = "#007395"
TEAL_40 = "#99C7D5"
TEAL_20 = "#CCE3EA"
GRAY = "#46494D"
GRAY_80 = "#6B6D71"
GRAY_60 = "#909294"
GRAY_40 = "#B5B6B8"
GRAY_20 = "#DADBDB"
GRAY_5 = "#F6F6F6"
GOLD = "#F5C318"

# Names used throughout the app, mapped to brand colors
INK = GRAY
STEEL = NAVY
SLATE = GRAY_80
LINE = GRAY_20
AMBER = GOLD            # "next inspection" accent
RED = BRAND_RED              # Unscheduled = needs action
SCHEDULED_BLUE = NAVY
IGNORED_GRAY = GRAY_20
ISSUE_ORANGE = GOLD     # location issues
DRAFT_BLUE = GRAY_40

# Light or dark comes from the viewer's Streamlit setting, using the two themes
# in .streamlit/config.toml. Streamlit restyles its own widgets; this CSS restyles
# the custom pieces to match.
try:
    THEME_MODE = st.context.theme.base or "light"
except Exception:
    THEME_MODE = "light"
CONSOLE = THEME_MODE == "dark"   # dark theme flag (kept name for the rest of the app)

SANS = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"

st.markdown(f"""
<style>
.stApp, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp p, .stApp label, .stApp li,
.stApp button, .stApp input, .stApp textarea {{ font-family: {SANS}; }}
[data-testid="stDecoration"] {{ display: none; }}
.block-container {{ padding-top: 2rem; padding-bottom: 4rem; }}

.stApp h3 {{ font-size: 1.15rem; font-weight: 600; letter-spacing: -0.01em; }}
.stApp hr {{ border: none; border-top: 1px solid {GRAY_20}; margin: 1.5rem 0 1.25rem; }}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ font-size: 1rem; font-weight: 600; }}
.stMarkdown a {{ color: {TEAL}; }}

/* Buttons: red fill for main actions (Dark Red on hover); neutral outline for the rest */
.stApp .stButton button, .stApp .stDownloadButton button, .stApp .stLinkButton a {{
    border-radius: 6px; font-weight: 600;
}}
.stApp [data-testid="stBaseButton-primary"] {{
    background: {BRAND_RED}; border-color: {BRAND_RED}; color: #FFFFFF;
}}
.stApp [data-testid="stBaseButton-primary"]:hover {{
    background: {BRAND_DARK_RED}; border-color: {BRAND_DARK_RED}; color: #FFFFFF;
}}
.stApp [data-testid="stBaseButton-primary"]:active {{ background: #5E0A0B; border-color: #5E0A0B; }}
.stApp [data-testid="stBaseButton-secondary"] {{
    background: #FFFFFF; border: 1px solid {GRAY_40}; color: {GRAY};
}}
.stApp [data-testid="stBaseButton-secondary"]:hover {{
    background: {GRAY_5}; border-color: {GRAY_80}; color: {GRAY};
}}
.stApp :is(button, a):focus-visible {{ outline: 2px solid {BRAND_RED}; outline-offset: 2px; }}

/* Calendar / Map switch: selected = red fill, white text */
.stApp [data-testid="stBaseButton-segmented_controlActive"] {{
    background: {BRAND_RED}; border-color: {BRAND_RED}; color: #FFFFFF;
}}
.stApp [data-testid="stBaseButton-segmented_control"] {{ color: {GRAY}; }}

/* Header strip: navy with a red rule */
.cat-header {{
    background: {NAVY};
    color: #FFFFFF;
    border-radius: 10px;
    padding: 1.1rem 1.4rem 1rem;
    margin-bottom: 1.25rem;
    border-bottom: 4px solid {BRAND_RED};
}}
.cat-header-title {{ font-size: 1.6rem; font-weight: 700; line-height: 1.2; }}
.cat-header-meta {{
    display: flex; flex-wrap: wrap; gap: 0.35rem 1.5rem;
    margin-top: 0.4rem; font-size: 0.9rem; color: {GRAY_20};
}}
.cat-header-meta b {{ color: #FFFFFF; font-weight: 600; }}

/* Status stats: the bar color matches the status */
.cat-stats {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 0.75rem; margin: 0.25rem 0 0.5rem;
}}
.cat-stat {{
    background: #FFFFFF;
    border: 1px solid {GRAY_20};
    border-left: 5px solid var(--c);
    border-radius: 8px; padding: 0.7rem 1rem;
}}
.cat-stat-value {{ font-size: 1.7rem; font-weight: 700; color: {GRAY}; font-variant-numeric: tabular-nums; line-height: 1.2; }}
.cat-stat-label {{ font-size: 0.85rem; color: {GRAY_80}; }}

/* Month slot picker: keep the 7-day grid side by side, even on phones */
[class*="st-key-slotpicker"] [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap !important; gap: 0.25rem !important; }}
[class*="st-key-slotpicker"] [data-testid="stColumn"], [class*="st-key-slotpicker"] [data-testid="column"] {{
    min-width: 0 !important; width: auto !important; flex: 1 1 0 !important;
}}
[class*="st-key-slotpicker"] button {{ padding: 0.2rem 0 !important; min-height: 2.1rem; font-variant-numeric: tabular-nums; }}
[class*="st-key-slotpicker"] .stCaption, [class*="st-key-slotpicker"] [data-testid="stCaptionContainer"] {{ text-align: center; }}
[class*="st-key-pd_open"] [data-testid="stBaseButton-secondary"] {{ background: {TEAL_20}; border-color: {TEAL}; }}
[class*="st-key-pd_few"] [data-testid="stBaseButton-secondary"] {{ background: #FFFFFF; border: 2px solid {GOLD}; }}
[class*="st-key-pd_full"] button {{ background: repeating-linear-gradient(45deg, {GRAY_20} 0 4px, transparent 4px 8px) !important; }}
[class*="st-key-pd_off"] button {{ opacity: 0.35; }}
[class*="st-key-pd_dayoff"] [data-testid="stBaseButton-secondary"] {{ border: 1px dashed {GRAY_60}; color: {GRAY_80}; }}
[class*="st-key-pt_open"] [data-testid="stBaseButton-secondary"] {{ border-color: {TEAL}; }}

/* Next-up and selected-block cards */
.cat-card {{ border-left: 4px solid {GOLD}; padding: 0.1rem 0 0.1rem 0.85rem; margin-bottom: 0.6rem; }}
.cat-card.selected {{ border-left-color: {NAVY}; }}
.cat-card-kicker {{ font-size: 0.82rem; color: {GRAY_80}; }}
.cat-card-title {{ font-size: 1.05rem; font-weight: 600; margin: 0.1rem 0; color: {GRAY}; }}
.cat-card-sub {{ font-size: 0.9rem; color: {GRAY_80}; }}

@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{ transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }}
}}
</style>
""", unsafe_allow_html=True)

if CONSOLE:
    # Dark theme: navy page, gray panels, white text. Red appears only as filled
    # buttons with white text (no red text on dark backgrounds).
    st.markdown(f"""
<style>
.stMarkdown a {{ color: {TEAL_40}; }}
.stApp [data-testid="stBaseButton-secondary"] {{
    background: transparent; border: 1px solid {GRAY_60}; color: #FFFFFF;
}}
.stApp [data-testid="stBaseButton-secondary"]:hover {{
    background: rgba(255, 255, 255, 0.08); border-color: {GRAY_20}; color: #FFFFFF;
}}
.stApp [data-testid="stBaseButton-segmented_control"] {{ color: #FFFFFF; }}
.cat-header {{ background: {GRAY}; }}
.cat-stat {{ background: rgba(255, 255, 255, 0.06); border-color: {GRAY_80}; }}
.cat-stat-value {{ color: #FFFFFF; }}
.cat-stat-label, .cat-card-kicker, .cat-card-sub {{ color: {GRAY_20}; }}
.cat-card-title {{ color: #FFFFFF; }}
.cat-card.selected {{ border-left-color: #FFFFFF; }}
.stApp hr {{ border-top-color: {GRAY_80}; }}
[class*="st-key-pd_open"] [data-testid="stBaseButton-secondary"] {{ background: {TEAL}; border-color: {TEAL_40}; }}
[class*="st-key-pd_few"] [data-testid="stBaseButton-secondary"] {{ background: transparent; border: 2px solid {GOLD}; }}
[class*="st-key-pd_full"] button {{ background: repeating-linear-gradient(45deg, {GRAY_80} 0 4px, transparent 4px 8px) !important; }}
[class*="st-key-pt_open"] [data-testid="stBaseButton-secondary"] {{ border-color: {TEAL_40}; }}
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


def create_block(start_dt, end_dt, label):
    """
    Adds blocked time (a rep's own non-inspection time). It can't overlap a confirmed
    inspection or another block; drafts under it move to their next best spot.
    Returns an error message, or None when it worked.
    """
    if end_dt <= start_dt:
        return "The end time needs to be after the start time."
    cdf = st.session_state.claims_df
    clash = find_overlap(start_dt, end_dt, get_busy_intervals(cdf))
    if clash:
        return (f"That overlaps {clash['label']} ({clash['start'].strftime('%I:%M %p').lstrip('0')} - "
                f"{clash['end'].strftime('%I:%M %p').lstrip('0')}). Move it first, or pick another time.")
    import uuid
    bid = f"BLOCK-{uuid.uuid4().hex[:6].upper()}"
    label = (label or "").strip() or "Blocked"
    row = {c: "" for c in cdf.columns}
    row.update({"claim_id": bid, "insured_name": label, "display_label": f"{bid} - {label}",
                "full_address": "", "status": "Blocked", "geo_quality": "Blocked time",
                "lat": float("nan"), "lon": float("nan"), "priority": float("nan"),
                "start_time": start_dt.isoformat(), "end_time": end_dt.isoformat(),
                "scheduled_date": start_dt.strftime("%Y-%m-%d"), "inspection_time": start_dt.strftime("%H:%M")})
    st.session_state.claims_df = pd.concat([cdf, pd.DataFrame([row])], ignore_index=True)
    st.session_state.editor_version += 1
    displace_drafts({"start": start_dt.isoformat(), "end": end_dt.isoformat(),
                     "date_str": start_dt.strftime("%Y-%m-%d")}, booked_ids={bid})
    return None


def remove_block(bid):
    cdf = st.session_state.claims_df
    st.session_state.claims_df = cdf[cdf["claim_id"].astype(str) != str(bid)].reset_index(drop=True)
    st.session_state.editor_version += 1


def remove_claim(cid):
    """
    Deletes a claim from the pool and the schedule. Nothing is remembered: if it's
    reassigned back later, it comes in as a new claim on the next updated list.
    """
    cdf = st.session_state.claims_df
    st.session_state.claims_df = cdf[cdf["claim_id"].astype(str) != str(cid)].reset_index(drop=True)
    st.session_state.export_ids = st.session_state.get("export_ids", set()) - {str(cid)}
    st.session_state.editor_version += 1
    st.session_state.map_nonce += 1


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

    # For each inspection day:
    #   gaps_by_day      = truly free time (no confirmed inspection and no draft), shown as "Open"
    #   bookable_by_day  = time free of CONFIRMED inspections. Drafts are placeholders, so a
    #                      booking can go over one (the draft then moves to its next best spot).
    gaps_by_day, bookable_by_day = {}, {}
    d = S["start_date"]
    while d <= S["end_date"]:
        if d.strftime("%a") in S["active_days"]:
            gaps_by_day[d.isoformat()] = compute_day_gaps(d, S["day_start"], S["per_day"], S["window_hrs"],
                                                          busy_all, now, S["latest_end"])
            bookable_by_day[d.isoformat()] = compute_day_gaps(d, S["day_start"], S["per_day"], S["window_hrs"],
                                                              busy, now, S["latest_end"])
        d += timedelta(days=1)
    # Days off inside the deployment dates: bookable by hand, from the day start to the
    # latest-end time. They never get suggestions or drafts.
    off_days = set()
    d = S["start_date"]
    while d <= S["end_date"]:
        if d.strftime("%a") not in S["active_days"]:
            ds_ = d.isoformat()
            off_days.add(ds_)
            manual = {d.strftime("%a"): 24}
            gaps_by_day[ds_] = compute_day_gaps(d, S["day_start"], manual, S["window_hrs"], busy_all, now, S["latest_end"])
            bookable_by_day[ds_] = compute_day_gaps(d, S["day_start"], manual, S["window_hrs"], busy, now, S["latest_end"])
        d += timedelta(days=1)
    drafts_by_day = defaultdict(list)
    for b in drafts_busy:
        drafts_by_day[b["start"].strftime("%Y-%m-%d")].append(b)
    openings_by_day = defaultdict(list)
    for o in openings:
        openings_by_day[o["date_str"]].append(o)

    days_with_time = [ds for ds, g in bookable_by_day.items() if g]
    if not days_with_time:
        st.info("No open time left in this date range. Extend the end date or adjust the day settings in the sidebar.")
        return None

    if not st.toggle("📅 Pick a day and time", key=f"pick_cal_{cid}"):
        if openings:
            nxt = openings[0]
            n_s, n_e = parse_wallclock(nxt["start"]), parse_wallclock(nxt["end"])
            st.markdown(f"**Next opening:** {n_s.strftime('%a %b %d')}, {tfmt(n_s)} - {tfmt(n_e)}")
            return nxt
        if drafts_busy:
            st.info("Your open time is filled with drafts. Turn on **Pick a day and time** to book over a "
                    "draft; the draft moves to its next best spot.")
        else:
            st.info("No full-length openings left, but there is shorter open time. "
                    "Turn on **Pick a day and time** to book a shorter inspection.")
        return None

    day_key, time_key, dur_key, month_key = (f"pick_day_{cid}", f"pick_time_{cid}",
                                             f"pick_dur_{cid}", f"pick_month_{cid}")

    def first_free_start(ds):
        if openings_by_day.get(ds):
            return parse_wallclock(openings_by_day[ds][0]["start"])
        if gaps_by_day.get(ds):
            return gaps_by_day[ds][0][0]
        return bookable_by_day[ds][0][0]   # only drafted time left: start of the first drafted block

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
                    state, tip, can_pick = "off", "Outside your deployment dates", False
                elif ds in off_days:
                    state = "dayoff"
                    tip = "Day off: book by hand if needed" if bookable_by_day[ds] else "No time left"
                    can_pick = bool(bookable_by_day[ds])
                elif not bookable_by_day[ds]:
                    state, tip, can_pick = "full", "Fully booked with confirmed inspections", False
                else:
                    n_open = len(openings_by_day.get(ds, []))
                    state = "open" if n_open >= 2 else "few"
                    parts = []
                    if gaps_by_day[ds]:
                        parts.append("Open " + ", ".join(f"{tfmt(a)}-{tfmt(b)}" for a, b in gaps_by_day[ds]))
                    if drafts_by_day.get(ds):
                        parts.append(f"{len(drafts_by_day[ds])} draft(s) you can book over")
                    if not openings_by_day.get(ds):
                        parts.append("At your daily limit: book by hand if needed")
                    tip = ". ".join(parts)
                    can_pick = True
                col.button(str(d.day), key=f"pd_{state}_{cid}_{ds}", help=tip, disabled=not can_pick,
                           use_container_width=True, type="primary" if ds == sel_day else "secondary",
                           on_click=pick_day, args=(ds,))

        st.caption("Teal: room for 2+ inspections. Gold outline: room for 1 or less. Dashed: a day off "
                   "(book by hand). Hatched: no time left. Faded: outside your deployment dates.")

    # ---- The selected day ----
    day_d = date.fromisoformat(sel_day)
    if sel_day in off_days:
        ws, we = day_window(day_d, S["day_start"], {day_d.strftime("%a"): 24}, S["window_hrs"], S["latest_end"])
        st.markdown(f"**{day_d.strftime('%A, %b %d')}** (a day off in your settings, so it's never suggested; "
                    "you can still book it by hand)")
    else:
        ws, we = day_window(day_d, S["day_start"], S["per_day"], S["window_hrs"], S["latest_end"])
        st.markdown(f"**{day_d.strftime('%A, %b %d')}** ({tfmt(ws)} - {tfmt(we)} working hours)")

    rows = [(b["start"], f"{tfmt(b['start'])} - {tfmt(b['end'])}",
             f"Draft (unconfirmed): {b['label']}" if b.get("draft") else
             (f"🚫 {b['label'][0].upper()}{b['label'][1:]}" if b.get("block") else f"Booked: {b['label']}"))
            for b in busy_all if b["start"].date() == day_d]
    if current and current[0] and current[0].date() == day_d:
        rows.append((current[0], f"{tfmt(current[0])} - {tfmt(current[1])}", "This claim's current time"))
    rows += [(a, f"{tfmt(a)} - {tfmt(b)}", "Open") for a, b in gaps_by_day[sel_day]]
    rows.append((we, f"After {tfmt(we)}", "Evening: type a later start time if the insured is available"))
    st.markdown("  \n".join(
        f":green[**{when}** · open]" if what == "Open" else f"{when} · {what}"
        for _, when, what in sorted(rows, key=lambda r: r[0])
    ))

    # Leave-by for the day's first on-site stop, and when you'd be back after the last one
    hotel_pt, typ = S.get("hotel"), S.get("typical_drive") or 30
    stops = []
    if hotel_pt:
        for _, r in claims_df[claims_df["status"].isin(["Scheduled", "Draft"])].iterrows():
            s_, e_ = parse_wallclock(r.get("start_time")), parse_wallclock(r.get("end_time"))
            if (s_ and s_.date() == day_d and str(r["claim_id"]) != cid and pd.notna(r["lat"])
                    and not is_video(r.get("activity_type"))):
                stops.append((s_, (float(r["lat"]), float(r["lon"]))))
    stops.sort(key=lambda x: x[0])
    if stops:
        lb = leave_by(stops[0][0], stops[0][1], hotel_pt)
        ret = estimated_return(stops[-1][0], S["window_hrs"], typ, stops[-1][1], hotel_pt)
        bits = []
        if lb:
            bits.append(f"leave the hotel by {tfmt(lb)} for the first stop")
        if ret:
            bits.append(f"you'd be back around {tfmt(ret)} after the last")
        if bits:
            line = " and ".join(bits)
            st.caption(line[0].upper() + line[1:] + ". Drive times don't include traffic, "
                       "so check your map app before you leave.")

    # Quick starts: the beginning of each open block, plus each draft's time (booking there
    # replaces the draft, which then moves to its next best spot)
    open_starts = ({parse_wallclock(o["start"]) for o in openings_by_day.get(sel_day, [])} |
                   {a for a, _ in gaps_by_day[sel_day]})
    draft_starts = {b["start"] for b in drafts_by_day.get(sel_day, []) if b["start"] > now} - open_starts
    quick = sorted([(t, False) for t in open_starts] + [(t, True) for t in draft_starts])
    if quick:
        st.caption("Quick start times" + (" (times marked draft replace that draft)" if draft_starts else ""))
        for i in range(0, len(quick), 3):
            for col, (t, is_draft) in zip(st.columns(3), quick[i:i + 3]):
                col.button(tfmt(t) + (" · draft" if is_draft else ""), key=f"pt_open_{cid}_{t.isoformat()}",
                           use_container_width=True,
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
    # If this would be the day's last on-site stop, show when you'd be back at base
    me = claims_df[claims_df["claim_id"].astype(str) == cid]
    if (hotel_pt and not me.empty and pd.notna(me.iloc[0]["lat"]) and not is_video(me.iloc[0].get("activity_type"))
            and all(s_ < start_dt for s_, _ in stops)):
        ret_me = estimated_return(start_dt, S["window_hrs"], typ,
                                  (float(me.iloc[0]["lat"]), float(me.iloc[0]["lon"])), hotel_pt)
        if ret_me:
            limit_dt = datetime.combine(day_d, S["latest_end"])
            note = f"As your last stop, you'd be back at base around {tfmt(ret_me)}"
            st.caption(note + (f", past your {tfmt(limit_dt)} limit." if ret_me > limit_dt else "."))
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
#   Your progress (daily) > Deployment > Daily schedule > Preferences > Tools
#   Settings live in collapsible sections, each with a one-line summary.
# =====================================================================
sb = st.sidebar

# --- YOUR PROGRESS (top: used every day) ---
sb.subheader("Your progress")
saved_file = sb.file_uploader("📂 Load saved progress", type=["csv"], key="load_state_csv")
if saved_file is not None:
    # Only load a given file once. Without this check the saved CSV would be
    # re-read on every rerun and overwrite any edits.
    file_sig = (saved_file.name, saved_file.size)
    if st.session_state.get("loaded_state_sig") != file_sig:
        try:
            st.session_state.claims_df = pd.read_csv(saved_file)
            st.session_state.loaded_state_sig = file_sig
            st.session_state.editor_version += 1
            st.session_state.map_nonce += 1
            sb.success("Progress restored.")
        except Exception as e:
            sb.error(f"Couldn't load that file: {e}")
save_slot = sb.empty()   # the Save button is drawn at the end of the run, so it saves the latest changes

# --- DEPLOYMENT PARAMETERS (deployment + daily schedule) ---
_times30 = time_options(30)
with sb.expander("Deployment parameters", expanded=not st.session_state.get("hotel_address", "").strip()):
    hotel_address = st.text_input(
        "Hotel base location", value="", key="hotel_address",
        placeholder="Street, city, state, ZIP",
        help="Where you're staying. The first stop of each day is measured from here, and with "
             "Least added driving, the last stop of the day favors claims on the way back."
    )
    hotel_coords = geocode_hotel_address(hotel_address)
    if not hotel_address.strip():
        st.caption("Add your hotel address so each day's first drive time starts there.")
    elif hotel_coords is None:
        st.warning("Couldn't find the hotel address. The first stop of each day will use "
                   "the center of your claims for drive times.")

    col_d1, col_d2 = st.columns(2)
    start_date = col_d1.date_input("Start date", date.today(), key="start_date")
    end_date = col_d2.date_input("End date", date.today() + timedelta(days=5), key="end_date")

    # All schedule times are local to the deployment; this zone is used for the
    # Outlook export and for knowing which inspections are already in the past.
    detected_tz, detected_source = detect_deployment_timezone(st.session_state.claims_df, hotel_address)
    detected_label = next((k for k, v in US_TIMEZONES.items() if v == detected_tz), detected_tz)
    tz_choices = [f"Auto-detect ({detected_label})"] + list(US_TIMEZONES.keys())
    if st.session_state.get("tz_choice") not in tz_choices:
        st.session_state.pop("tz_choice", None)
    tz_choice = st.selectbox(
        "Deployment time zone", tz_choices, index=0, key="tz_choice",
        help=f"Auto-detected from {detected_source}. Override if the deployment is in a split-zone "
             "area (e.g. El Paso, the Florida panhandle, western Kansas/Nebraska/Dakotas)."
    )

    st.markdown("**Daily schedule**")
    start_time_input = st.selectbox(
        "Day starts", _times30, index=_times30.index(datetime.strptime("08:00", "%H:%M").time()),
        format_func=fmt_time12, key="day_start_time",
        help="The time of your first inspection. The app tells you when to leave the hotel to make it."
    )
    # Inspections per day, set for each day of the week (0 = day off). Suggestions and the
    # planner follow these; days off and evenings can still be booked by hand.
    _week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if "per_day_counts" not in st.session_state:
        st.session_state.per_day_counts = {d: 3 for d in _week}
    st.caption("Inspections per day: the most the app suggests or drafts each day (0 = day off)")
    # Days run down (not across) so the table fits the sidebar without sideways scrolling
    _per_day_edit = st.data_editor(
        pd.DataFrame({"Day": _week, "Inspections": [st.session_state.per_day_counts.get(d, 3) for d in _week]}),
        key="per_day_editor_rows", hide_index=True, use_container_width=True, disabled=["Day"],
        column_config={
            "Day": st.column_config.TextColumn("Day"),
            "Inspections": st.column_config.NumberColumn("Inspections", min_value=0, max_value=8, step=1,
                                                         format="%d", required=True),
        },
    )
    inspections_per_day = {}
    for d, n in zip(_per_day_edit["Day"], _per_day_edit["Inspections"]):
        try:
            inspections_per_day[d] = max(0, min(8, int(n)))
        except (TypeError, ValueError):
            inspections_per_day[d] = st.session_state.per_day_counts.get(d, 3)
    st.session_state.per_day_counts = inspections_per_day
    active_days = active_days_from(inspections_per_day)
    window_hrs = st.number_input(
        "Window length (hours)", min_value=0.25, max_value=8.00, value=2.50, step=0.25, key="window_hrs",
        help="Starts at the inspection time and covers inspection, estimate, payment and travel. "
             "Suggested openings use this length, but you can book any start time and length."
    )
    latest_end_input = st.selectbox(
        "Back at base by", _times30,
        index=_times30.index(datetime.strptime("19:00", "%H:%M").time()),
        format_func=fmt_time12, key="latest_end_time",
        help="The latest you want to be back at the hotel. The day's last suggested inspection is "
             "timed so you're back by then, using the real drive home. You can still book later by hand."
    )
deployment_tz = detected_tz if tz_choice.startswith("Auto-detect") else US_TIMEZONES[tz_choice]
tz_display = detected_label if tz_choice.startswith("Auto-detect") else tz_choice

try:
    deployment_zone = get_zone(deployment_tz)
    now_local = datetime.now(deployment_zone).replace(tzinfo=None)
    ics_tz = deployment_tz
except Exception:
    sb.error("Time zone data isn't installed. Run `pip install tzdata` (needed on Windows). "
             "Until then, calendar exports use floating local times.")
    now_local = datetime.now()
    ics_tz = None


# --- PREFERENCES ---
with sb.expander("Preferences", expanded=False):
    rec_mode_label = st.radio(
        "Recommendations",
        ["Closest to previous stop (faster)", "Least added driving (smarter, may take longer)"],
        key="rec_mode",
        help="Closest: ranks claims by drive time from where you'll be before the opening. "
             "Least added driving: also counts the drive to where you're going next (your next "
             "inspection, or the hotel at the end of the day), so claims on the way rank higher. "
             "It looks up about twice as many drive times, so it can be slower."
    )
    fill_label = st.radio(
        "Fill your schedule from",
        ["Start of deployment (earliest days first)", "End of deployment (latest days first)"],
        key="fill_direction",
        help="Changes the order of suggested openings and drafts. Priority claims still go to the "
             "earliest days. Within each day, suggestions run morning to afternoon."
    )
REC_MODE = "detour" if rec_mode_label.startswith("Least") else "fast"
FILL_LATEST_FIRST = fill_label.startswith("End")

# Openings come from the real bookings: any free time inside each day's working
# window, in blocks of the default window length starting at the earliest free time.
schedule_settings = {
    "start_date": start_date, "end_date": end_date, "active_days": active_days,
    "day_start": start_time_input, "per_day": inspections_per_day, "window_hrs": window_hrs,
    "latest_end": latest_end_input,
    "latest_first": FILL_LATEST_FIRST,
    # How much of each window is usually driving, estimated from the claims themselves
    "typical_drive": typical_drive_minutes(st.session_state.claims_df),
    "hotel": hotel_coords,
}
all_slots = order_openings(compute_openings(
    start_date, end_date, active_days, start_time_input, inspections_per_day, window_hrs,
    st.session_state.claims_df, now=now_local, latest_end=latest_end_input, include_drafts=True
), latest_days_first=FILL_LATEST_FIRST)

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
                was_scheduled = row["status"] == "Scheduled"
                remove_claim(cid)
                finish_review_item()
                st.toast(f"Removed {cid}"
                         + (". Remember to delete it from Outlook if you exported it." if was_scheduled else ""))
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
    # Older saved files may have Ignored/Removed claims: bring them back as Unscheduled,
    # so nothing is silently lost (they can be removed for good from Manage a claim)
    _old = cdf["status"].isin(["Ignored", "Removed"])
    if _old.any():
        cdf.loc[_old, "status"] = "Unscheduled"
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
        ("Total claims", int((df["status"] != "Blocked").sum()), GRAY),
        ("Unscheduled", int((df["status"] == "Unscheduled").sum()), RED),
        ("Scheduled", scheduled_count, SCHEDULED_BLUE),
        ("Drafts", int((df["status"] == "Draft").sum()), DRAFT_BLUE),
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

    # --- LOCATION CHECK (before planning) ---
    if review_mask.any():
        flagged = df[review_mask]
        with st.container(border=True):
            st.markdown(f"### ⚠️ Before planning: {len(flagged)} claim(s) need a location check")
            st.markdown(
                "These pins are only placed at a ZIP code or town center, or weren't found at all. "
                "Until they're checked, drive times and routes involving them can be way off, and "
                "the planner schedules them **last**."
            )
            st.caption(", ".join(f"{r['claim_id']} ({r['geo_quality']})" for _, r in flagged.head(10).iterrows())
                       + (f", and {len(flagged) - 10} more" if len(flagged) > 10 else ""))

            def start_fixing():
                st.session_state["pin_fix_mode"] = True
                st.session_state["main_view"] = "Map"
            fb1, fb2 = st.columns([1.3, 1])
            fb1.button("📍 Fix locations now", type="primary", on_click=start_fixing, use_container_width=True,
                       help="Opens the map below with Fix pin locations turned on, starting with these claims.")
            if fb2.button("Look up again", use_container_width=True,
                          help="Runs the address lookup again for these claims. Helps when the lookup service "
                               "was slow or down during import. Pins you placed or confirmed aren't touched."):
                cdf = st.session_state.claims_df
                redo_idx = cdf.index[cdf["geo_quality"].isin(GEO_NEEDS_REVIEW)].tolist()
                with st.spinner(f"Looking up {len(redo_idx)} address(es) again..."):
                    addrs = [(cdf.at[i, "full_address"], cdf.at[i, "state"] if "state" in cdf.columns else "")
                             for i in redo_idx]
                    results = batch_geocode_addresses(addrs)
                improved = 0
                for i, (lat, lon, quality) in zip(redo_idx, results):
                    if quality not in GEO_NEEDS_REVIEW:
                        improved += 1
                    if lat is not None:
                        cdf.at[i, "lat"], cdf.at[i, "lon"], cdf.at[i, "geo_quality"] = lat, lon, quality
                st.session_state.map_nonce += 1
                st.session_state.editor_version += 1
                st.toast(f"Found better locations for {improved} claim(s)." if improved else
                         "No better matches found. Fix these on the map.")
                st.rerun()

    if st.session_state.get("draft_notice"):
        st.info(st.session_state.pop("draft_notice"))

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

    # Calendar / Map switch. Unlike tabs, the app can change it (e.g. "Fix locations now"
    # opens the Map), and only the view you're looking at loads.
    if st.session_state.get("main_view") not in ("Calendar", "Map"):
        st.session_state["main_view"] = "Calendar"
    try:
        main_view = st.segmented_control("View", ["Calendar", "Map"], key="main_view",
                                         label_visibility="collapsed")
    except AttributeError:   # older Streamlit without segmented_control
        main_view = st.radio("View", ["Calendar", "Map"], key="main_view", horizontal=True,
                             label_visibility="collapsed")
    main_view = main_view or "Calendar"

    # -----------------------------------------------------------------
    # CALENDAR
    # -----------------------------------------------------------------
    if main_view == "Calendar":
        scheduled_claims = df[df["status"].isin(["Scheduled", "Draft", "Blocked"])].copy()
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
                same_day_before = scheduled_claims[
                    (scheduled_claims["status"] == "Scheduled") &
                    (scheduled_claims["_start_dt"].apply(lambda x: x.date()) == nr["_start_dt"].date()) &
                    (scheduled_claims["_start_dt"] < nr["_start_dt"])]
                if same_day_before.empty and hotel_coords and pd.notna(nr["lat"]) and not is_video(nr.get("activity_type")):
                    lb = leave_by(nr["_start_dt"], (float(nr["lat"]), float(nr["lon"])), hotel_coords)
                    if lb:
                        st.markdown(f"**Leave the hotel by {lb.strftime('%I:%M %p').lstrip('0')}** "
                                    f"(includes a {LEAVE_BUFFER_MIN}-minute buffer). Drive times don't include traffic, so check your map app before you leave.")
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

        # Leave-by time for each day's first on-site stop (confirmed or draft)
        leave_note = {}
        if hotel_coords and not scheduled_claims.empty:
            onsite = scheduled_claims[(scheduled_claims["status"].isin(["Scheduled", "Draft"])) &
                                      scheduled_claims["lat"].notna() & scheduled_claims["lon"].notna() &
                                      ~scheduled_claims["activity_type"].apply(is_video)]
            for _day, grp in onsite.groupby(onsite["_start_dt"].apply(lambda x: x.date())):
                f = grp.sort_values("_start_dt").iloc[0]
                lb = leave_by(f["_start_dt"], (float(f["lat"]), float(f["lon"])), hotel_coords)
                if lb:
                    leave_note[str(f["claim_id"])] = lb.strftime("%I:%M %p").lstrip("0")

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
            if row["status"] == "Blocked":
                event.update({
                    "title": f"🚫 Blocked: {row['insured_name']}",
                    "classNames": ["block-event"],
                    "backgroundColor": GRAY_80 if CONSOLE else GRAY_20,
                    "borderColor": GRAY_60 if CONSOLE else GRAY_40,
                    "textColor": "#FFFFFF" if CONSOLE else GRAY,
                })
            elif row["status"] == "Draft":
                nxt_txt = ""
                if cid in drive_next:
                    long_drive = drive_next[cid] > window_hrs * 60 / 3
                    nxt_txt = f" · {'⚠️ ' if long_drive else ''}{drive_next[cid]} min to next"
                event.update({
                    "title": f"Draft · [{cid}] {row['insured_name']}{nxt_txt}",
                    "classNames": ["draft-event"],
                    "backgroundColor": NAVY if CONSOLE else "#FFFFFF",
                    "borderColor": "#FFFFFF" if CONSOLE else NAVY,
                    "textColor": "#FFFFFF" if CONSOLE else NAVY,
                })
            elif row["_end_dt"] <= now_local:
                event.update({
                    "classNames": ["past-event"],
                    "backgroundColor": GRAY_80 if CONSOLE else GRAY_20,
                    "borderColor": GRAY_60 if CONSOLE else GRAY_40,
                    "textColor": "#FFFFFF" if CONSOLE else GRAY,
                })
            elif cid == next_id:
                event.update({
                    "title": f"⏭️ {event['title']}",
                    "classNames": ["next-event"],
                    "backgroundColor": GOLD,
                    "borderColor": GOLD,
                    "textColor": GRAY,
                })
            elif is_video(row.get("activity_type")):
                # Live video: a lighter shade of the inspection blue
                # Live video: a light tint, so it reads as lighter than an on-site inspection
                event.update({"title": f"📹 {event['title']}", "backgroundColor": TEAL_20,
                              "borderColor": TEAL, "textColor": NAVY})
            else:
                event.update({"backgroundColor": TEAL if CONSOLE else NAVY,
                              "borderColor": TEAL if CONSOLE else NAVY, "textColor": "#FFFFFF"})
            if cid in leave_note:
                event["title"] = f"{event['title']} · Leave {leave_note[cid]}"
            calendar_events.append(event)

        # --- VISIBLE HOURS ---
        # Show until 7 PM by default, but extend to fit the inspection windows
        # and any inspection that runs later (or starts earlier) than that.
        def minutes_of_day(dt, base_date):
            if dt.date() > base_date:
                return 24 * 60
            return dt.hour * 60 + dt.minute

        day_start_dt = datetime.combine(start_date, start_time_input)
        day_end_dt = datetime.combine(start_date, latest_end_input)
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
            # Gray shading outside each day's usual hours (days off are all gray). It's a
            # guide only: inspections can be booked or dragged anywhere inside the dates.
            "businessHours": [
                {"daysOfWeek": [js_day[d]], "startTime": start_time_input.strftime("%H:%M"),
                 "endTime": latest_end_input.strftime("%H:%M")}
                for d in active_days
            ],
            # The deployment dates are hard limits: nothing can be booked or dragged outside them
            "validRange": {"start": start_date.isoformat(), "end": (end_date + timedelta(days=1)).isoformat()},
        }

        calendar_css = f"""
            .fc {{
                font-family: {SANS};
                color: {GRAY};
                --fc-border-color: {GRAY_20};
                --fc-button-bg-color: #FFFFFF;
                --fc-button-border-color: {GRAY_40};
                --fc-button-text-color: {GRAY};
                --fc-button-hover-bg-color: {GRAY_5};
                --fc-button-hover-border-color: {GRAY_80};
                --fc-button-active-bg-color: {BRAND_RED};
                --fc-button-active-border-color: {BRAND_RED};
                --fc-today-bg-color: {GRAY_5};
                --fc-now-indicator-color: {BRAND_RED};
                --fc-non-business-color: rgba(181, 182, 184, 0.28);
                --fc-neutral-bg-color: {GRAY_5};
            }}
            .fc .fc-toolbar-title {{ font-size: 1.05rem; font-weight: 700; color: {NAVY}; }}
            .fc .fc-button {{ font-size: 0.82rem; font-weight: 600; border-radius: 6px; box-shadow: none !important; text-transform: capitalize; }}
            .fc .fc-button-primary:not(:disabled).fc-button-active {{ color: #FFFFFF; }}
            .fc .fc-col-header-cell-cushion {{ color: {GRAY_80}; font-weight: 600; font-size: 0.82rem; text-decoration: none; }}
            .fc .fc-timegrid-slot-label-cushion {{ color: {GRAY_80}; font-size: 0.78rem; }}
            .fc .fc-daygrid-day-number {{ color: {GRAY_80}; text-decoration: none; }}
            .fc-event {{ border-radius: 5px; font-size: 0.8rem; }}
            .fc-event.past-event {{
                background-image: repeating-linear-gradient(
                    45deg, rgba(255,255,255,0.55) 0 5px, transparent 5px 10px) !important;
            }}
            .fc-event.past-event .fc-event-title {{ text-decoration: line-through; }}
            .fc-event.next-event {{ font-weight: 700; }}
            .fc-event.draft-event {{ border-style: dashed !important; border-width: 2px !important; font-style: italic; }}
            .fc-event.block-event {{
                background-image: repeating-linear-gradient(135deg, rgba(0,0,0,0.06) 0 6px, transparent 6px 12px) !important;
            }}
        """
        if CONSOLE:
            calendar_css += f"""
            html, body {{ background: {NAVY}; }}
            .fc {{
                color: #FFFFFF;
                background: {NAVY};
                --fc-page-bg-color: {NAVY};
                --fc-neutral-bg-color: {GRAY};
                --fc-border-color: {GRAY_80};
                --fc-button-bg-color: {GRAY};
                --fc-button-border-color: {GRAY_60};
                --fc-button-text-color: #FFFFFF;
                --fc-button-hover-bg-color: {GRAY_80};
                --fc-button-hover-border-color: {GRAY_20};
                --fc-today-bg-color: rgba(255, 255, 255, 0.06);
                --fc-now-indicator-color: #FFFFFF;
                --fc-non-business-color: rgba(0, 0, 0, 0.25);
            }}
            .fc .fc-toolbar-title {{ color: #FFFFFF; }}
            .fc .fc-col-header-cell-cushion, .fc .fc-timegrid-slot-label-cushion,
            .fc .fc-daygrid-day-number {{ color: {GRAY_20}; }}
            .fc-event.past-event {{
                background-image: repeating-linear-gradient(
                    45deg, rgba(255,255,255,0.12) 0 5px, transparent 5px 10px) !important;
            }}
            """

        if leave_note:
            st.caption(f"Each day's first inspection shows when to leave the hotel, with a {LEAVE_BUFFER_MIN}-minute "
                       "buffer. Drive times don't include traffic, so check your map app before you leave.")
        with st.expander("🚫 Block off time"):
            st.caption("For team calls, appointments or time off. Nothing gets suggested or drafted there. "
                       "Tip: you can also drag across empty time on the calendar.")
            _t15 = time_options(15)
            bk1, bk2, bk3 = st.columns(3)
            blk_day = bk1.date_input("Date", value=max(start_date, min(now_local.date(), end_date)),
                                     min_value=start_date, max_value=end_date, key="blk_day")
            blk_start = bk2.selectbox("From", _t15, index=_t15.index(datetime.strptime("12:00", "%H:%M").time()),
                                      format_func=fmt_time12, key="blk_start")
            blk_end = bk3.selectbox("To", _t15, index=_t15.index(datetime.strptime("13:00", "%H:%M").time()),
                                    format_func=fmt_time12, key="blk_end")
            blk_label = st.text_input("Label", placeholder="Team call, lunch, time off...", key="blk_label")
            if st.button("Block this time", type="primary", key="blk_add"):
                err = create_block(datetime.combine(blk_day, blk_start), datetime.combine(blk_day, blk_end), blk_label)
                if err:
                    st.error(err)
                else:
                    st.toast("Time blocked")
                    st.rerun()

        cal_event = calendar(
            events=calendar_events,
            options=calendar_options,
            custom_css=calendar_css,
            # Only click and drag/resize. The default also reports "eventsSet" on every
            # render, which reruns the whole app and keeps rebuilding the map.
            # (plus "select": drag across empty time to block it off)
            callbacks=["eventClick", "eventChange", "select"],
            key="claims_calendar"
        ) or {}

        # --- CLICK A BLOCK: directions + manage ---
        clicked = (cal_event.get("eventClick") or {}).get("event") or {}
        clicked_id = str(clicked.get("id") or "")
        blk_rows = df[(df["claim_id"].astype(str) == clicked_id) & (df["status"] == "Blocked")] if clicked_id else df.iloc[0:0]
        if not blk_rows.empty:
            b = blk_rows.iloc[0]
            b_s, b_e = parse_wallclock(b["start_time"]), parse_wallclock(b["end_time"])
            with st.container(border=True):
                st.markdown(f"**🚫 Blocked: {esc(b['insured_name'])}**  \n"
                            f"{fmt_dt(b_s)} to {b_e.strftime('%I:%M %p').lstrip('0') if b_e else ''}")
                st.caption("Drag it on the calendar to move it, or drag its bottom edge to change the length.")
                if st.button("Remove this block", key=f"rm_{clicked_id}"):
                    remove_block(clicked_id)
                    st.rerun()
            clicked_id = ""

        sel = cal_event.get("select") or {}
        if sel.get("start"):
            sel_sig = (sel.get("start"), sel.get("end"))
            if st.session_state.get("handled_select") != sel_sig:
                s0, s1 = parse_wallclock(sel.get("start")), parse_wallclock(sel.get("end"))
                if sel.get("allDay") and s0:   # month view: block that day's usual hours
                    s0 = datetime.combine(s0.date(), start_time_input)
                    s1 = datetime.combine(s0.date(), latest_end_input)
                if s0 and s1:
                    with st.container(border=True):
                        st.markdown(f"**Block off {fmt_dt(s0)} to {s1.strftime('%I:%M %p').lstrip('0')}?**")
                        sel_label = st.text_input("Label", placeholder="Team call, lunch, time off...", key="sel_blk_label")
                        sb1, sb2 = st.columns(2)
                        if sb1.button("Block this time", type="primary", key="sel_blk_add", use_container_width=True):
                            err = create_block(s0, s1, sel_label)
                            if err:
                                st.error(err)
                            else:
                                st.session_state["handled_select"] = sel_sig
                                st.toast("Time blocked")
                                st.rerun()
                        if sb2.button("Cancel", key="sel_blk_cancel", use_container_width=True):
                            st.session_state["handled_select"] = sel_sig
                            st.rerun()

        if clicked_id:
            c_rows = df[(df["claim_id"].astype(str) == clicked_id) & (df["status"].isin(["Scheduled", "Draft"]))]
            if not c_rows.empty:
                c_row = c_rows.iloc[0]
                # Select it in Manage a claim (once per click, so choosing another claim
                # in the dropdown afterward isn't overridden)
                click_sig = (clicked_id, clicked.get("start"))
                if st.session_state.get("last_cal_click") != click_sig:
                    st.session_state["last_cal_click"] = click_sig
                    st.session_state["selected_claim_id"] = clicked_id
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
                    st.caption("Selected in Manage a claim below.")

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

        valid_coords_df = mdf[(mdf["status"] != "Blocked") & (mdf["lat"].notna()) & (mdf["lon"].notna())]
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
            if row["status"] == "Blocked" or pd.isna(row["lat"]) or pd.isna(row["lon"]):
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
                    f"<br><span style='color:#6B6D71'>Location: {esc(row['geo_quality'])}</span><br>{links_html}",
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

    if main_view == "Map":
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

        show_status = st.multiselect("Show statuses", ["Unscheduled", "Draft", "Scheduled"],
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
                    "Status", options=["Unscheduled", "Draft", "Scheduled"], required=True,
                    help="Schedule a claim from Manage a claim, so it gets a real time. "
                         "Changing a Draft to Scheduled confirms it. To remove a claim, use Manage a claim."),
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
                if new["Status"] == "Unscheduled":
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
        claim_options = df.loc[df["status"] != "Blocked", "display_label"].tolist()

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

                # --- Remove a claim (withdrawn, reassigned, duplicate) ---
                with st.expander("Remove claim", expanded=False):
                    st.caption("Deletes this claim from your pool and schedule, including its contact details "
                               "and notes. This can't be undone. If it's reassigned back to you later, it will "
                               "come in as a new claim on your next updated list.")
                    if current_claim["status"] == "Scheduled":
                        st.warning(f"This cancels the inspection on {fmt_dt(parse_wallclock(current_claim['start_time']))}. "
                                   "If you already exported it to Outlook, delete that appointment in Outlook too.")
                    elif current_claim["status"] == "Draft":
                        st.caption("Its draft time will be cleared.")
                    sure = st.checkbox(f"Yes, remove {selected_claim_id}", key=f"rm_sure_{selected_claim_id}")
                    if st.button("Remove claim", key=f"rm_btn_{selected_claim_id}", disabled=not sure):
                        was_scheduled = current_claim["status"] == "Scheduled"
                        remove_claim(selected_claim_id)
                        st.toast(f"Removed {selected_claim_id}"
                                 + (". Remember to delete it from Outlook if you exported it." if was_scheduled else ""))
                        st.rerun()

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

                elif current_claim["status"] == "Unscheduled":
                    chosen_slot = render_slot_picker(selected_claim_id, st.session_state.claims_df,
                                                     now_local, schedule_settings, default_hrs=claim_length)
                    if chosen_slot:
                        selected_target_date_str = chosen_slot["date_str"]
                        if st.button("Book this slot", type="primary"):
                            book_claim_into_slot(claim_mask, chosen_slot)
                            st.rerun()

    st.markdown("---")
    # --- PLAN MY SCHEDULE (right above Fill an opening) ---
    n_drafts = int((df["status"] == "Draft").sum())
    cap = capacity_report(df, schedule_settings, now_local)
    with st.container(border=True):
        pc1, pc2, pc3 = st.columns([3, 1.1, 0.9], vertical_alignment="center")
        with pc1:
            st.markdown("**Plan my schedule**")
            st.caption("Builds draft appointments for your unscheduled claims: priorities first, then grouped "
                       "by area and ordered as routes. Confirmed appointments and blocked time never move. "
                       "Confirm each draft after the insured agrees. Can take up to a minute for large lists.")
            st.caption("💡 Add any blocked time you already know about (team calls, appointments, time off) "
                       "before planning, so drafts are built around it.")
        plan_clicked = pc2.button("Re-plan drafts" if n_drafts else "Plan my schedule", type="primary",
                                  use_container_width=True, disabled=cap["claims"] == 0)
        clear_clicked = pc3.button("Clear drafts", use_container_width=True, disabled=n_drafts == 0,
                                   help="Removes all unconfirmed drafts. Confirmed appointments stay.")

        if cap["shortfall"]:
            msg = (f"**{cap['claims']} claims to place, but only {cap['openings']} openings fit your settings. "
                   f"{cap['shortfall']} claim(s) won't be scheduled.** To fit everyone, you could:\n")
            msg += "\n".join(f"- {label}" + (f": +{extra} openings" if extra else "") for label, extra in cap["suggestions"])
            msg += "\n\nIf you plan anyway, the highest-priority claims are placed first."
            st.warning(msg)
        elif cap["claims"]:
            st.caption(f"{cap['claims']} claim(s) to place, {cap['openings']} openings available.")

        if plan_clicked:
            bar = st.progress(0.0, text="Starting...")
            drafts, summary = plan_draft_schedule(df, schedule_settings, hotel_coords, now_local,
                                                  latest_first=FILL_LATEST_FIRST,
                                                  progress=lambda f, t: bar.progress(min(max(f, 0.0), 1.0), text=t))
            bar.empty()
            for cid in df.loc[df["status"] == "Draft", "claim_id"].astype(str).tolist():
                set_claim_times(cid, "Unscheduled")
            for dft in drafts:
                set_claim_times(dft["claim_id"], "Draft", {"start": dft["start"], "end": dft["end"],
                                                           "date_str": dft["start"][:10]})
            st.session_state["plan_summary"] = summary
            st.session_state.editor_version += 1
            st.session_state.map_nonce += 1
            st.rerun()
        if clear_clicked:
            for cid in df.loc[df["status"] == "Draft", "claim_id"].astype(str).tolist():
                set_claim_times(cid, "Unscheduled")
            st.session_state.pop("plan_summary", None)
            st.session_state.editor_version += 1
            st.session_state.map_nonce += 1
            st.rerun()

        summ = st.session_state.get("plan_summary")
        if summ:
            line = f"Drafted {summ['placed']} appointment(s) across {summ['days']} day(s)."
            if summ["unplaced"]:
                line += (f" {len(summ['unplaced'])} claim(s) didn't fit and stay Unscheduled: "
                         + ", ".join(summ["unplaced"][:12]) + ("..." if len(summ["unplaced"]) > 12 else "") + ".")
            line += " Confirm each draft after the insured agrees: select it in the calendar or under Manage a claim."
            st.success(line)
            if summ.get("needs_check"):
                st.warning(f"Placed last because their location still needs a check: {', '.join(summ['needs_check'])}. "
                           "Fix their pins, then re-plan for better routes.")
            for lr in summ.get("late_returns", []):
                st.warning(f"{lr['date']}: after {lr['claim']} you'd be back at base around {lr['back']}, past your "
                           f"{lr['limit']} limit. Consider moving it earlier, to another day, or a later limit.")
            for el in summ.get("early_leaves", []):
                st.warning(f"{el['date']}: you'd need to leave the hotel by {el['leave']} for {el['claim']}. "
                           "Consider a later first inspection or a closer first stop.")
            if summ.get("typical_drive"):
                st.caption(f"Assuming about {summ['typical_drive']} minutes of each window is driving, based on "
                           f"how spread out your claims are. Leave times include a {LEAVE_BUFFER_MIN}-minute buffer. "
                           + "Drive times don't include traffic, so check your map app before you leave.")
            for ld in summ.get("long_drives", []):
                st.warning(f"{ld['date']}: {ld['mins']}-minute drive from {ld['from']} to {ld['to']} leaves about "
                           f"{ld['left_min'] // 60} hr {ld['left_min'] % 60} min of your {window_hrs:g}-hour window. "
                           "Consider moving one to another day, or using longer windows.")
            if st.button("Dismiss summary", key="dismiss_plan"):
                st.session_state.pop("plan_summary", None)
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
            mode=REC_MODE,
            back_by=latest_end_input,
            window_hrs=window_hrs,
            typical_drive=schedule_settings["typical_drive"]
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
                        if rec_row.get("back_at_base"):
                            if rec_row.get("late_back"):
                                drive_txt += (f"  \n:orange[Back at base around {rec_row['back_at_base']}, past your "
                                              f"{fmt_time12(latest_end_input)} limit.]")
                            else:
                                drive_txt += f" · back at base around {rec_row['back_at_base']}"
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


# =====================================================================
# SAVE PROGRESS (drawn last into the slot at the top of the sidebar,
# so the file always includes this run's changes)
# =====================================================================
if st.session_state.claims_df is not None:
    save_slot.download_button(
        label="📥 Save progress",
        data=st.session_state.claims_df.to_csv(index=False).encode("utf-8"),
        file_name=f"cat_scheduler_state_{date.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
        help="Downloads everything: claims, schedule, drafts, priorities, contact details and pin fixes."
    )
