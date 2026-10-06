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
    US_TIMEZONES
)

st.set_page_config(page_title="CAT Claims Dynamic Scheduler MVP", layout="wide")

if "claims_df" not in st.session_state:
    st.session_state.claims_df = None

# Bumped whenever claims_df is changed from the editor (or a state file is loaded),
# so the data_editor starts fresh instead of re-applying stale row edits.
if "editor_version" not in st.session_state:
    st.session_state.editor_version = 0



def book_claim_into_slot(claim_mask, slot):
    """Schedules (or reschedules) the claim(s) in claim_mask into the given slot."""
    st.session_state.claims_df.loc[claim_mask, "status"] = "Scheduled"
    st.session_state.claims_df.loc[claim_mask, "start_time"] = slot["start"]
    st.session_state.claims_df.loc[claim_mask, "end_time"] = slot["end"]
    st.session_state.claims_df.loc[claim_mask, "scheduled_date"] = slot["date_str"]
    st.session_state.claims_df.loc[claim_mask, "inspection_time"] = parse_wallclock(slot["start"]).strftime("%H:%M")
    st.session_state.editor_version += 1


st.title("CAT Dynamic Scheduling")

# --- SIDEBAR PREFERENCES ---
st.sidebar.header("🗓️ Rep Schedule Parameters")
hotel_address = st.sidebar.text_input("Hotel Base Location", "1100 San Pedro Ave, San Antonio, TX")
hotel_coords = geocode_hotel_address(hotel_address)
if hotel_address.strip() and hotel_coords is None:
    st.sidebar.warning("Couldn't locate the hotel address. Drive times from the start of the day "
                       "will use the center of your claims instead.")

col_d1, col_d2 = st.sidebar.columns(2)
with col_d1:
    start_date = st.sidebar.date_input("Inspection Start", date.today())
with col_d2:
    end_date = st.sidebar.date_input("Inspection End", date.today() + timedelta(days=5))

active_days = st.sidebar.multiselect(
    "Active Inspection Days",
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    default=["Mon", "Tue", "Wed", "Thu", "Fri"]
)

inspections_per_day = st.sidebar.slider("Inspections / Day", 1, 8, 3)

window_hrs = st.sidebar.number_input(
    "Window Duration (Hours)",
    min_value=0.25,
    max_value=8.00,
    value=2.50,
    step=0.25
)

start_time_input = st.sidebar.time_input("Day Start Time", value=datetime.strptime("08:00", "%H:%M").time())

# --- DEPLOYMENT TIME ZONE ---
# All schedule times are local to the deployment; this zone is used for the
# Outlook export and for knowing which inspections are already in the past.
detected_tz, detected_source = detect_deployment_timezone(st.session_state.claims_df, hotel_address)
detected_label = next((k for k, v in US_TIMEZONES.items() if v == detected_tz), detected_tz)
tz_choices = [f"Auto-detect ({detected_label})"] + list(US_TIMEZONES.keys())
tz_choice = st.sidebar.selectbox(
    "Deployment Time Zone",
    tz_choices,
    index=0,
    help=f"Auto-detected from {detected_source}. Override if the deployment is in a split-zone "
         "area (e.g. El Paso, the Florida panhandle, western Kansas/Nebraska/Dakotas)."
)
deployment_tz = detected_tz if tz_choice.startswith("Auto-detect") else US_TIMEZONES[tz_choice]

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

# --- MANUAL GEOMAP REFRESH & STATE MANAGEMENT ---
st.sidebar.markdown("---")
st.sidebar.subheader("🗺️ Map Tools & State")

if st.session_state.claims_df is not None:
    if st.sidebar.button("🔄 Force Re-Geocode & Map Refresh", type="secondary"):
        with st.spinner("Re-geocoding all claim addresses sequentially..."):
            addrs = list(zip(
                st.session_state.claims_df["full_address"].tolist(),
                st.session_state.claims_df.get("state", pd.Series([""] * len(st.session_state.claims_df))).tolist()
            ))
            new_coords = batch_geocode_addresses(addrs)
            st.session_state.claims_df["lat"] = [c[0] for c in new_coords]
            st.session_state.claims_df["lon"] = [c[1] for c in new_coords]
            st.sidebar.success("Map re-geocoded successfully!")
            st.rerun()

    st.sidebar.markdown(" ")
    csv_bytes = st.session_state.claims_df.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(
        label="📥 Save Progress (Download State)",
        data=csv_bytes,
        file_name=f"cat_scheduler_state_{date.today().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

saved_file = st.sidebar.file_uploader("📂 Load Saved State CSV", type=["csv"], key="load_state_csv")
if saved_file is not None:
    # Only load a given file once. Without this check the saved CSV would be
    # re-read on every rerun and overwrite any priority/status edits.
    file_sig = (saved_file.name, saved_file.size)
    if st.session_state.get("loaded_state_sig") != file_sig:
        try:
            loaded_df = pd.read_csv(saved_file)
            st.session_state.claims_df = loaded_df
            st.session_state.loaded_state_sig = file_sig
            st.session_state.editor_version += 1
            st.sidebar.success("Progress restored!")
        except Exception as e:
            st.sidebar.error(f"Error loading state: {e}")

# --- INGESTION ---
st.subheader("1. Ingest Claims List")
uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file is not None and st.session_state.claims_df is None:
    try:
        with st.spinner("Parsing table and batch-geocoding addresses..."):
            raw_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)
            st.session_state.claims_df = process_imported_table(raw_df)
            st.success(f"Successfully imported and mapped {len(st.session_state.claims_df)} claims!")
            st.rerun()
    except Exception as e:
        st.error(f"Error parsing table: {e}")

# --- DASHBOARD ---
if st.session_state.claims_df is not None:
    for required_col in ["scheduled_date", "inspection_time", "start_time", "end_time"]:
        if required_col not in st.session_state.claims_df.columns:
            st.session_state.claims_df[required_col] = ""
    for text_col in ["scheduled_date", "inspection_time"]:
        st.session_state.claims_df[text_col] = st.session_state.claims_df[text_col].fillna("").astype(str)
    if "priority" not in st.session_state.claims_df.columns:
        st.session_state.claims_df["priority"] = None

    # Keep priority as a float column (NaN = unranked) so it accepts both
    # integer ranks and blanks from the editor without dtype errors.
    st.session_state.claims_df["priority"] = pd.to_numeric(
        st.session_state.claims_df["priority"].apply(normalize_priority), errors="coerce"
    ).astype(float)

    df = st.session_state.claims_df

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Claims", len(df))
    c2.metric("Unscheduled", len(df[df["status"] == "Unscheduled"]))
    scheduled_count = len(df[df["status"] == "Scheduled"])
    c3.metric("Scheduled / Confirmed", scheduled_count)
    c4.metric("Ignored / Archived", len(df[df["status"] == "Ignored"]))

    st.markdown("---")

    if scheduled_count > 0:
        ics_data = export_claims_to_ics(df, ics_tz)
        st.download_button(
            label=f"📅 Export {scheduled_count} Scheduled Inspection(s) to Outlook (.ics) · {detected_label if tz_choice.startswith('Auto') else tz_choice} time",
            data=ics_data,
            file_name="cat_inspection_schedule.ics",
            mime="text/calendar"
        )
        st.markdown(" ")

    tab_cal, tab_map = st.tabs(["📅 CALENDAR VIEW", "🛰 SATELLITE MAP VIEW"])

    with tab_cal:
        calendar_events = []
        scheduled_claims = df[df["status"] == "Scheduled"]
        
        for idx, row in scheduled_claims.iterrows():
            if pd.notna(row["start_time"]) and pd.notna(row["end_time"]) and str(row["start_time"]) != "":
                calendar_events.append({
                    "id": str(row["claim_id"]),
                    "title": f"[{row['claim_id']}] {row['insured_name']}",
                    "start": str(row["start_time"]),
                    "end": str(row["end_time"]),
                    "backgroundColor": "#2563EB",
                    "borderColor": "#1D4ED8"
                })

        calendar_options = {
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": "timeGridWeek,timeGridDay,dayGridMonth"},
            "initialView": "timeGridWeek",
            "initialDate": start_date.strftime("%Y-%m-%d"),
            "slotMinTime": start_time_input.strftime("%H:%M:%S"),
            "slotMaxTime": "21:00:00",
            "editable": True,
            "selectable": True,
            "slotEventOverlap": True,
            # Show stored times exactly as entered (deployment-local), regardless
            # of the time zone of the computer viewing the app.
            "timeZone": "UTC"
        }

        cal_event = calendar(events=calendar_events, options=calendar_options, key="claims_calendar")
        
        if cal_event.get("eventChange"):
            changed_event = cal_event["eventChange"]["event"]
            cid = str(changed_event["id"])
            new_start = parse_wallclock(changed_event["start"])
            new_end = parse_wallclock(changed_event.get("end")) or (new_start + timedelta(hours=window_hrs))
            
            c_mask = st.session_state.claims_df["claim_id"].astype(str) == cid
            st.session_state.claims_df.loc[c_mask, "start_time"] = new_start.isoformat()
            st.session_state.claims_df.loc[c_mask, "end_time"] = new_end.isoformat()
            st.session_state.claims_df.loc[c_mask, "scheduled_date"] = new_start.strftime("%Y-%m-%d")
            st.session_state.claims_df.loc[c_mask, "inspection_time"] = new_start.strftime("%H:%M")
            st.session_state.editor_version += 1
            st.toast(f"Updated time for claim {cid}!")
            st.rerun()

    with tab_map:
        valid_coords_df = df[(df["status"] != "Ignored") & (df["lat"].notna()) & (df["lon"].notna())]

        if not valid_coords_df.empty:
            avg_lat = valid_coords_df["lat"].mean()
            avg_lon = valid_coords_df["lon"].mean()
        else:
            avg_lat, avg_lon = 29.4241, -98.4936

        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=10, tiles="OpenStreetMap")
        
        esri_satellite_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        folium.TileLayer(
            tiles=esri_satellite_url,
            attr="Esri World Imagery",
            name="ESRI Satellite"
        ).add_to(m)

        day_colors = ["blue", "green", "purple", "orange", "darkred", "cadetblue", "darkgreen", "pink"]
        scheduled_dates = sorted([d for d in df[df["status"] == "Scheduled"]["scheduled_date"].unique() if d])
        date_color_map = {d: day_colors[i % len(day_colors)] for i, d in enumerate(scheduled_dates)}

        bounds = []
        for idx, row in df.iterrows():
            if row["status"] == "Ignored" or pd.isna(row["lat"]) or pd.isna(row["lon"]):
                continue

            lat = float(row["lat"])
            lon = float(row["lon"])

            marker_color = "red" if row["status"] == "Unscheduled" else date_color_map.get(row.get("scheduled_date"), "blue")
            icon_type = "exclamation-sign" if row["status"] == "Unscheduled" else "ok-sign"

            folium.Marker(
                location=[lat, lon],
                popup=f"<b>{row['claim_id']}</b><br>{row['insured_name']}<br>{row['full_address']}",
                tooltip=f"{row['claim_id']} - {row['insured_name']}",
                icon=folium.Icon(color=marker_color, icon=icon_type)
            ).add_to(m)

            bounds.append([lat, lon])

        if hotel_coords:
            folium.Marker(
                location=list(hotel_coords),
                popup=f"<b>Hotel Base</b><br>{hotel_address}",
                tooltip="Hotel Base",
                icon=folium.Icon(color="black", icon="home")
            ).add_to(m)
            bounds.append(list(hotel_coords))

        if bounds:
            m.fit_bounds(bounds, padding=(30, 30))

        folium.LayerControl().add_to(m)
        st_folium(m, width=1100, height=520, key="claims_map")

    st.markdown("---")

    # --- MANAGEMENT & CLAIMS POOL ---
    col_left, col_right = st.columns([1.5, 1])

    with col_left:
        st.subheader("📋 Active Claims Pool")
        st.caption("Edit **Priority** (1 = highest, blank = unranked) or set **Status** to Unscheduled/Ignored. "
                   "Changes save automatically and re-sort the recommendations below.")

        if st.session_state.get("editor_notice"):
            st.warning(st.session_state.pop("editor_notice"))

        show_status = st.multiselect("Filter Status View", ["Unscheduled", "Scheduled", "Ignored"], default=["Unscheduled", "Scheduled"])
        filtered_df = df[df["status"].isin(show_status)].copy()
        filtered_df["priority"] = filtered_df["priority"].astype("Int64")  # nullable int: shows "2", not "2.0"

        editor_cols = ["claim_id", "insured_name", "full_address", "priority", "status", "scheduled_date", "inspection_time"]
        editor_key = f"claims_editor_{st.session_state.editor_version}_{'_'.join(sorted(show_status))}"

        edited_df = st.data_editor(
            filtered_df[editor_cols],
            key=editor_key,
            disabled=["claim_id", "insured_name", "full_address", "scheduled_date", "inspection_time"],
            column_config={
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
        st.subheader("🎯 Select Claim to Manage")
        claim_options = df["display_label"].tolist()

        if "managed_claim_select" not in st.session_state or st.session_state["managed_claim_select"] not in claim_options:
            st.session_state["managed_claim_select"] = claim_options[0]

        if "selected_claim_id" in st.session_state and st.session_state["selected_claim_id"]:
            matching = [opt for opt in claim_options if opt.startswith(str(st.session_state["selected_claim_id"]) + " -")]
            if matching:
                st.session_state["managed_claim_select"] = matching[0]
            del st.session_state["selected_claim_id"]

        selected_label = st.selectbox(
            "Select Claim to Manage",
            claim_options,
            key="managed_claim_select"
        )

        if selected_label:
            selected_claim_id = selected_label.split(" - ")[0].strip()
            claim_mask = st.session_state.claims_df["claim_id"].astype(str) == selected_claim_id
            
            if claim_mask.any():
                current_claim = st.session_state.claims_df[claim_mask].iloc[0]
                
                st.write(f"**Claim Number:** `{current_claim['claim_id']}`")
                st.write(f"**Insured Name:** {current_claim['insured_name']}")
                st.write(f"**Address:** {current_claim['full_address']}")
                st.write(f"**Current Status:** `{current_claim['status']}`")
                
                st.markdown("---")

                if current_claim["status"] == "Scheduled":
                    if current_claim["scheduled_date"]:
                        selected_target_date_str = str(current_claim["scheduled_date"])

                    st.write(f"**Currently:** {parse_wallclock(current_claim['start_time']).strftime('%a %m/%d %I:%M %p') if parse_wallclock(current_claim['start_time']) else '—'}")

                    move_slots = [
                        s for s in all_slots
                        if parse_wallclock(s["start"]) > now_local
                        and not is_slot_conflicting(s, st.session_state.claims_df, current_claim_id=selected_claim_id)
                        and s["start"] != str(current_claim["start_time"])
                    ]
                    if move_slots:
                        move_label = st.selectbox("Move to Open Slot", [s["slot_label"] for s in move_slots], key="move_slot_select")
                        move_slot = next(s for s in move_slots if s["slot_label"] == move_label)
                        if st.button("🔁 Move to This Slot"):
                            book_claim_into_slot(claim_mask, move_slot)
                            st.rerun()

                    if st.button("Remove from Schedule", type="primary"):
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
                        selected_slot_label = st.selectbox("Choose Open Slot", slot_labels, index=0, key="book_slot_select")
                        chosen_slot = next(s for s in unbooked_slots if s["slot_label"] == selected_slot_label)
                        selected_target_date_str = chosen_slot["date_str"]
                        
                        if st.button("Confirm & Lock Slot", type="primary"):
                            book_claim_into_slot(claim_mask, chosen_slot)
                            st.rerun()

    # --- RECOMMENDATIONS ---
    st.markdown("---")
    st.subheader("💡 Recommended Claims for an Opening")

    open_slots = [
        s for s in all_slots
        if parse_wallclock(s["start"]) > now_local
        and not is_slot_conflicting(s, st.session_state.claims_df, current_claim_id="")
    ]

    if not open_slots:
        st.info("No open slots left in the current date range. Widen the dates or add inspections per day in the sidebar.")
    else:
        rc1, rc2 = st.columns([1.3, 1])
        with rc1:
            # Default to the first opening on the date in context (selected claim / chosen slot)
            default_idx = next((i for i, s in enumerate(open_slots) if s["date_str"] == selected_target_date_str), 0)
            opening_label = st.selectbox("Opening to Fill", [s["slot_label"] for s in open_slots], index=default_idx)
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

        st.caption(f"Drive times from **{anchor_info['label']}**. Ranked claims (❗) are listed first by priority; "
                   "drive time breaks ties and orders unranked claims.")

        if recs is None or recs.empty:
            st.info("No matching claims for this opening.")
        else:
            for idx, rec_row in recs.head(5).reset_index(drop=True).iterrows():
                col_rec1, col_rec2, col_rec3 = st.columns([3, 0.8, 0.8])
                with col_rec1:
                    claim_label = f"{rec_row['claim_id']} - {rec_row['insured_name']}"
                    rank = normalize_priority(rec_row.get("priority_rank"))

                    # Ranked claim: bold red ❗ badge; unranked: no badge, proximity only
                    title = f":red[**❗ P{rank}**] **{claim_label}**" if rank is not None else f"**{claim_label}**"
                    if rec_row["rec_type"] == "Reschedule":
                        title += f" :blue[🔁 currently {rec_row['current_slot']}]"

                    st.markdown(
                        f"{title} — *{rec_row['full_address']}* "
                        f"(⏱️ `{rec_row['drive_time_mins']} mins` · {rec_row['drive_miles']} mi)"
                    )
                with col_rec2:
                    action = "🔁 Move Here" if rec_row["rec_type"] == "Reschedule" else "📌 Book Here"
                    if st.button(action, key=f"btn_book_{idx}_{rec_row['claim_id']}"):
                        mask = st.session_state.claims_df["claim_id"].astype(str) == str(rec_row["claim_id"])
                        book_claim_into_slot(mask, opening)
                        st.toast(f"{rec_row['claim_id']} booked for {opening_label}")
                        st.rerun()
                with col_rec3:
                    if st.button("Manage", key=f"btn_rec_{idx}_{rec_row['claim_id']}"):
                        st.session_state["selected_claim_id"] = str(rec_row["claim_id"])
                        st.rerun()

