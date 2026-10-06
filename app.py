import html
import math
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime, date, timedelta
from streamlit_calendar import calendar
from engine import (
    process_imported_table,
    generate_available_slots,
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
    GEO_MANUAL,
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


def book_claim_into_slot(claim_mask, slot):
    """Schedules (or reschedules) the claim(s) in claim_mask into the given slot."""
    st.session_state.claims_df.loc[claim_mask, "status"] = "Scheduled"
    st.session_state.claims_df.loc[claim_mask, "start_time"] = slot["start"]
    st.session_state.claims_df.loc[claim_mask, "end_time"] = slot["end"]
    st.session_state.claims_df.loc[claim_mask, "scheduled_date"] = slot["date_str"]
    st.session_state.claims_df.loc[claim_mask, "inspection_time"] = parse_wallclock(slot["start"]).strftime("%H:%M")
    st.session_state.editor_version += 1


def save_manual_pin(claim_id, lat, lon):
    """Stores a rep-placed pin. Saved with progress, and kept on re-geocode."""
    mask = st.session_state.claims_df["claim_id"].astype(str) == str(claim_id)
    st.session_state.claims_df.loc[mask, "lat"] = float(lat)
    st.session_state.claims_df.loc[mask, "lon"] = float(lon)
    st.session_state.claims_df.loc[mask, "geo_quality"] = GEO_MANUAL
    st.session_state.map_nonce += 1
    st.session_state.editor_version += 1
    st.toast(f"Pin saved for {claim_id}")


def render_nav_buttons(address, lat, lon, geo_quality=None):
    """Shows 'Google Maps' and 'Apple Maps' directions buttons side by side."""
    links = build_navigation_links(address, lat, lon, prefer_coords=(geo_quality == GEO_MANUAL))
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
hotel_address = st.sidebar.text_input("Hotel base location", "1100 San Pedro Ave, San Antonio, TX")
hotel_coords = geocode_hotel_address(hotel_address)
if hotel_address.strip() and hotel_coords is None:
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

inspections_per_day = st.sidebar.slider("Inspections per day", 1, 8, 3)

window_hrs = st.sidebar.number_input(
    "Window length (hours)",
    min_value=0.25,
    max_value=8.00,
    value=2.50,
    step=0.25
)

start_time_input = st.sidebar.time_input("Day start time", value=datetime.strptime("08:00", "%H:%M").time())

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

all_slots = generate_available_slots(
    start_date, end_date, active_days, inspections_per_day, start_time_input, window_hrs
)

# --- MAP TOOLS & SAVED PROGRESS ---
st.sidebar.markdown("---")
st.sidebar.subheader("Map & saved progress")

if st.session_state.claims_df is not None:
    if st.sidebar.button("🔄 Re-check all addresses", type="secondary",
                         help="Looks up every address again. Pins you placed by hand are kept."):
        cdf = st.session_state.claims_df
        if "geo_quality" not in cdf.columns:
            cdf["geo_quality"] = GEO_UNKNOWN
        redo_idx = cdf.index[cdf["geo_quality"] != GEO_MANUAL].tolist()
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
uploaded_file = st.file_uploader("Upload a CSV or Excel claims list", type=["csv", "xlsx"])

if uploaded_file is not None and st.session_state.claims_df is None:
    try:
        with st.spinner("Reading the claims list and looking up addresses..."):
            raw_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)
            st.session_state.claims_df = process_imported_table(raw_df)
            st.rerun()
    except Exception as e:
        st.error(f"Couldn't read that file: {e}")


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
        ("Ignored", int((df["status"] == "Ignored").sum()), IGNORED_GRAY),
    ]
    st.markdown(
        '<div class="cat-stats">' + "".join(
            f'<div class="cat-stat" style="--c:{color}">'
            f'<div class="cat-stat-value">{value}</div><div class="cat-stat-label">{label}</div></div>'
            for label, value, color in stats
        ) + "</div>",
        unsafe_allow_html=True
    )

    if review_mask.any():
        st.warning(f"{int(review_mask.sum())} claim(s) have an approximate or missing location. "
                   "Turn on **Fix pin locations** in the Map tab to place them.")

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
        scheduled_claims = df[df["status"] == "Scheduled"].copy()
        scheduled_claims["_start_dt"] = [parse_wallclock(v) for v in scheduled_claims["start_time"]]
        scheduled_claims["_end_dt"] = [parse_wallclock(v) for v in scheduled_claims["end_time"]]
        scheduled_claims = scheduled_claims[
            [s is not None and e is not None for s, e in zip(scheduled_claims["_start_dt"], scheduled_claims["_end_dt"])]
        ]

        # --- NEXT UP ---
        upcoming = scheduled_claims[[s > now_local for s in scheduled_claims["_start_dt"]]]
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
        calendar_events = []
        for _, row in scheduled_claims.iterrows():
            cid = str(row["claim_id"])
            event = {
                "id": cid,
                "title": f"[{cid}] {row['insured_name']}",
                "start": row["_start_dt"].isoformat(),
                "end": row["_end_dt"].isoformat(),
            }
            if row["_end_dt"] <= now_local:
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
            # Show stored times exactly as entered (deployment-local), regardless
            # of the time zone of the computer viewing the app.
            "timeZone": "UTC",
            # "now" in deployment-local time, so today's highlight and the
            # current-time line are correct for the deployment.
            "now": now_local.isoformat(),
            "nowIndicator": True,
            # Shade inactive inspection days and hours outside the inspection window,
            # and don't allow dragging inspections into the shaded areas.
            "businessHours": {
                "daysOfWeek": [js_day[d] for d in active_days],
                "startTime": start_time_input.strftime("%H:%M"),
                "endTime": "24:00" if window_end_min >= 24 * 60 else day_end_dt.strftime("%H:%M"),
            },
            "eventConstraint": "businessHours",
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
            key="claims_calendar"
        ) or {}

        # --- CLICK A BLOCK: directions + manage ---
        clicked = (cal_event.get("eventClick") or {}).get("event") or {}
        clicked_id = str(clicked.get("id") or "")
        if clicked_id:
            c_rows = df[(df["claim_id"].astype(str) == clicked_id) & (df["status"] == "Scheduled")]
            if not c_rows.empty:
                c_row = c_rows.iloc[0]
                with st.container(border=True):
                    st.markdown(f"""
<div class="cat-card selected">
  <div class="cat-card-kicker">Selected inspection</div>
  <div class="cat-card-title">{esc(c_row['claim_id'])} - {esc(c_row['insured_name'])}</div>
  <div class="cat-card-sub">{fmt_dt(parse_wallclock(c_row['start_time']))}<br>{esc(c_row['full_address'])}</div>
</div>""", unsafe_allow_html=True)
                    render_nav_buttons(c_row["full_address"], c_row["lat"], c_row["lon"], c_row["geo_quality"])
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
    # -----------------------------------------------------------------
    with tab_map:
        fix_mode = st.toggle(
            "Fix pin locations",
            key="pin_fix_mode",
            help="Zoom to a claim on the satellite view, click the right roof, and save. "
                 "Or paste coordinates from Google Maps."
        )

        fix_row = None
        if fix_mode:
            # Claims that need a check come first
            fix_order = df.assign(_ok=~review_mask).sort_values("_ok", kind="mergesort")
            fix_map = {}
            for _, r in fix_order.iterrows():
                flag = "⚠️ " if r["geo_quality"] in GEO_NEEDS_REVIEW else ""
                fix_map[f"{flag}{r['claim_id']} - {r['insured_name']} ({r['geo_quality']})"] = str(r["claim_id"])
            fix_label = st.selectbox("Claim to fix", list(fix_map.keys()), key="pin_fix_claim")
            fix_id = fix_map[fix_label]
            fix_row = df[df["claim_id"].astype(str) == fix_id].iloc[0]
            st.caption(f"{fix_row['full_address']}")

        valid_coords_df = df[(df["status"] != "Ignored") & (df["lat"].notna()) & (df["lon"].notna())]

        if fix_row is not None and pd.notna(fix_row["lat"]) and pd.notna(fix_row["lon"]):
            map_center, map_zoom = [float(fix_row["lat"]), float(fix_row["lon"])], 18
        elif fix_row is not None and hotel_coords:
            map_center, map_zoom = list(hotel_coords), 13
        elif not valid_coords_df.empty:
            map_center, map_zoom = [valid_coords_df["lat"].mean(), valid_coords_df["lon"].mean()], 10
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
        scheduled_dates = sorted([d for d in df[df["status"] == "Scheduled"]["scheduled_date"].unique() if d])
        date_color_map = {d: day_colors[i % len(day_colors)] for i, d in enumerate(scheduled_dates)}

        bounds = []
        for idx, row in df.iterrows():
            if row["status"] == "Ignored" or pd.isna(row["lat"]) or pd.isna(row["lon"]):
                continue

            lat = float(row["lat"])
            lon = float(row["lon"])
            needs_review = row["geo_quality"] in GEO_NEEDS_REVIEW
            is_fix_target = fix_row is not None and str(row["claim_id"]) == str(fix_row["claim_id"])

            nav = build_navigation_links(row["full_address"], lat, lon, prefer_coords=(row["geo_quality"] == GEO_MANUAL))
            if is_fix_target:
                marker_color, icon_type = "orange", "screenshot"
            else:
                marker_color = "red" if row["status"] == "Unscheduled" else date_color_map.get(row.get("scheduled_date"), "blue")
                icon_type = "question-sign" if needs_review else ("exclamation-sign" if row["status"] == "Unscheduled" else "ok-sign")

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
                tooltip=f"{row['claim_id']} - {row['insured_name']}" + (" (location approximate)" if needs_review else ""),
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
            bounds.append(list(hotel_coords))

        if bounds and not fix_mode:
            m.fit_bounds(bounds, padding=(30, 30))

        folium.LayerControl().add_to(m)

        map_key = f"claims_map_{st.session_state.map_nonce}_{fix_row['claim_id'] if fix_row is not None else 'all'}"
        map_state = st_folium(m, width=1100, height=540, key=map_key, returned_objects=["last_clicked"]) or {}

        if fix_mode and fix_row is not None:
            fc1, fc2 = st.columns(2)
            with fc1:
                clicked_pt = map_state.get("last_clicked")
                if clicked_pt:
                    st.markdown(f"Selected spot  \n`{clicked_pt['lat']:.6f}, {clicked_pt['lng']:.6f}`")
                    if st.button(f"Move {fix_row['claim_id']} pin here", type="primary"):
                        save_manual_pin(fix_row["claim_id"], clicked_pt["lat"], clicked_pt["lng"])
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
                        st.rerun()
                    else:
                        st.error("No coordinates found. Paste something like 29.4241, -98.4936 "
                                 "or a Google Maps link that contains them.")

    st.markdown("---")

    # --- MANAGEMENT & CLAIMS POOL ---
    col_left, col_right = st.columns([1.5, 1])

    with col_left:
        st.subheader("Claims pool")
        st.caption("Edit **Priority** (1 = highest, blank = unranked) or set **Status** to Unscheduled or Ignored. "
                   "Changes save automatically and re-sort the recommendations below.")

        if st.session_state.get("editor_notice"):
            st.warning(st.session_state.pop("editor_notice"))

        show_status = st.multiselect("Show statuses", ["Unscheduled", "Scheduled", "Ignored"], default=["Unscheduled", "Scheduled"])
        filtered_df = df[df["status"].isin(show_status)].copy()
        filtered_df["priority"] = filtered_df["priority"].astype("Int64")  # nullable int: shows "2", not "2.0"

        editor_cols = ["claim_id", "insured_name", "full_address", "priority", "status", "scheduled_date", "inspection_time", "geo_quality"]
        editor_key = f"claims_editor_{st.session_state.editor_version}_{'_'.join(sorted(show_status))}"

        edited_df = st.data_editor(
            filtered_df[editor_cols],
            key=editor_key,
            disabled=["claim_id", "insured_name", "full_address", "scheduled_date", "inspection_time", "geo_quality"],
            column_config={
                "claim_id": st.column_config.TextColumn("Claim"),
                "insured_name": st.column_config.TextColumn("Insured"),
                "full_address": st.column_config.TextColumn("Address"),
                "scheduled_date": st.column_config.TextColumn("Date"),
                "inspection_time": st.column_config.TextColumn("Time"),
                "geo_quality": st.column_config.TextColumn("Location", help="How the map pin was placed."),
                "priority": st.column_config.NumberColumn(
                    "Priority",
                    help="1 = highest. Leave blank for unranked claims.",
                    min_value=1,
                    step=1,
                    format="%d"
                ),
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=["Unscheduled", "Scheduled", "Ignored"],
                    required=True,
                    help="Use 'Confirm & Lock Slot' on the right to schedule a claim."
                ),
            },
            hide_index=True,
            use_container_width=True
        )

        # --- SYNC EDITOR CHANGES BACK INTO SESSION STATE ---
        # edited_df keeps the same index as claims_df, so rows map back directly.
        changes_made = False
        blocked_claims = []

        for row_idx in edited_df.index:
            old_row = filtered_df.loc[row_idx]
            new_row = edited_df.loc[row_idx]

            old_prio = normalize_priority(old_row["priority"])
            new_prio = normalize_priority(new_row["priority"])
            if new_prio != old_prio:
                st.session_state.claims_df.at[row_idx, "priority"] = new_prio if new_prio is not None else float("nan")
                changes_made = True

            if new_row["status"] != old_row["status"]:
                if new_row["status"] in ("Unscheduled", "Ignored"):
                    st.session_state.claims_df.at[row_idx, "status"] = new_row["status"]
                    st.session_state.claims_df.at[row_idx, "start_time"] = None
                    st.session_state.claims_df.at[row_idx, "end_time"] = None
                    st.session_state.claims_df.at[row_idx, "scheduled_date"] = ""
                    st.session_state.claims_df.at[row_idx, "inspection_time"] = ""
                    changes_made = True
                elif new_row["status"] == "Scheduled":
                    # Scheduling needs a time slot, so it isn't allowed from the table.
                    blocked_claims.append(str(old_row["claim_id"]))

        if blocked_claims:
            st.session_state["editor_notice"] = (
                f"Claim(s) {', '.join(blocked_claims)} weren't scheduled. Select the claim on the right "
                "and use **Confirm & Lock Slot** to pick a time."
            )

        if changes_made or blocked_claims:
            st.session_state.editor_version += 1
            st.rerun()

    selected_target_date_str = start_date.strftime("%Y-%m-%d")

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
                
                st.markdown("---")

                if current_claim["status"] == "Scheduled":
                    if current_claim["scheduled_date"]:
                        selected_target_date_str = str(current_claim["scheduled_date"])

                    st.write(f"**Currently:** {fmt_dt(parse_wallclock(current_claim['start_time'])) or 'no time set'}")

                    move_slots = [
                        s for s in all_slots
                        if parse_wallclock(s["start"]) > now_local
                        and not is_slot_conflicting(s, st.session_state.claims_df, current_claim_id=selected_claim_id)
                        and s["start"] != str(current_claim["start_time"])
                    ]
                    if move_slots:
                        move_label = st.selectbox("Move to an open slot", [s["slot_label"] for s in move_slots], key="move_slot_select")
                        move_slot = next(s for s in move_slots if s["slot_label"] == move_label)
                        if st.button("🔁 Move to this slot"):
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

                elif current_claim["status"] in ["Unscheduled", "Ignored"]:
                    unbooked_slots = [s for s in all_slots if parse_wallclock(s["start"]) > now_local and not is_slot_conflicting(s, st.session_state.claims_df, current_claim_id=selected_claim_id)]
                    
                    if unbooked_slots:
                        slot_labels = [s["slot_label"] for s in unbooked_slots]
                        selected_slot_label = st.selectbox("Open slot", slot_labels, index=0, key="book_slot_select")
                        chosen_slot = next(s for s in unbooked_slots if s["slot_label"] == selected_slot_label)
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
            now_local=now_local
        )

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
                        else:
                            drive_txt = ":orange[📍 No map pin yet. Set it in the Map tab.]"

                        st.markdown(f"{title}  \n{rec_row['full_address']}  \n{drive_txt}")
                    with col_rec2:
                        action = f"🔁 Move to {opening_time}" if rec_row["rec_type"] == "Reschedule" else f"📌 Book {opening_time}"
                        if st.button(action, key=f"btn_book_{idx}_{rec_row['claim_id']}", use_container_width=True,
                                     type="primary" if idx == 0 else "secondary"):
                            mask = st.session_state.claims_df["claim_id"].astype(str) == str(rec_row["claim_id"])
                            book_claim_into_slot(mask, opening)
                            st.toast(f"Booked {rec_row['claim_id']} for {opening_label}")
                            st.rerun()
                    with col_rec3:
                        if st.button("Manage", key=f"btn_rec_{idx}_{rec_row['claim_id']}", use_container_width=True):
                            st.session_state["selected_claim_id"] = str(rec_row["claim_id"])
                            st.rerun()

