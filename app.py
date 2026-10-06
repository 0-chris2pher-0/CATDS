import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime, date, timedelta
from streamlit_calendar import calendar
from engine import (
    process_imported_table,
    generate_available_slots,
    get_recommendations_for_day,
    export_claims_to_ics,
    is_slot_conflicting
)

st.set_page_config(page_title="CAT Claims Dynamic Scheduler MVP", layout="wide")

if "claims_df" not in st.session_state:
    st.session_state.claims_df = None

st.title("⚡ CAT Claims Dynamic Scheduling & Map Tool")

# --- SIDEBAR PREFERENCES ---
st.sidebar.header("🗓️ Rep Schedule Preferences")
hotel_address = st.sidebar.text_input("Hotel Base Location", "1100 San Pedro Ave, San Antonio, TX")

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

all_slots = generate_available_slots(
    start_date, end_date, active_days, inspections_per_day, start_time_input, window_hrs
)

# --- SESSION SAVE / LOAD PROGRESS ---
st.sidebar.markdown("---")
st.sidebar.subheader("💾 Save / Resume Progress")
if st.session_state.claims_df is not None:
    csv_bytes = st.session_state.claims_df.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(
        label="📥 Save Progress (Download State)",
        data=csv_bytes,
        file_name=f"cat_scheduler_state_{date.today().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

saved_file = st.sidebar.file_uploader("📂 Load Saved State CSV", type=["csv"], key="load_state_csv")
if saved_file is not None:
    try:
        loaded_df = pd.read_csv(saved_file)
        st.session_state.claims_df = loaded_df
        st.sidebar.success("Progress restored!")
    except Exception as e:
        st.sidebar.error(f"Error loading state: {e}")

# --- INGESTION ---
st.subheader("1. Ingest Claims List")
uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file is not None and st.session_state.claims_df is None:
    try:
        raw_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)
        st.session_state.claims_df = process_imported_table(raw_df)
        st.success(f"Successfully imported {len(st.session_state.claims_df)} claims!")
    except Exception as e:
        st.error(f"Error parsing table: {e}")

# --- DASHBOARD ---
if st.session_state.claims_df is not None:
    for required_col in ["scheduled_date", "inspection_time", "start_time", "end_time"]:
        if required_col not in st.session_state.claims_df.columns:
            st.session_state.claims_df[required_col] = ""

    df = st.session_state.claims_df

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Claims", len(df))
    c2.metric("Unscheduled", len(df[df["status"] == "Unscheduled"]))
    scheduled_count = len(df[df["status"] == "Scheduled"])
    c3.metric("Scheduled / Confirmed", scheduled_count)
    c4.metric("Ignored / Archived", len(df[df["status"] == "Ignored"]))

    st.markdown("---")

    if scheduled_count > 0:
        ics_data = export_claims_to_ics(df)
        st.download_button(
            label=f"📅 Export {scheduled_count} Scheduled Inspection(s) to Outlook (.ics)",
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
            "slotEventOverlap": True
        }

        cal_event = calendar(events=calendar_events, options=calendar_options, key="claims_calendar")
        
        if cal_event.get("eventChange"):
            changed_event = cal_event["eventChange"]["event"]
            cid = str(changed_event["id"])
            new_start = changed_event["start"]
            new_end = changed_event["end"]
            
            c_mask = st.session_state.claims_df["claim_id"] == cid
            st.session_state.claims_df.loc[c_mask, "start_time"] = new_start
            st.session_state.claims_df.loc[c_mask, "end_time"] = new_end
            st.session_state.claims_df.loc[c_mask, "scheduled_date"] = new_start.split("T")[0]
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

            marker_color = "red" if row["status"] == "Unscheduled" else date_color_map.get(row.get("scheduled_date"), "blue")
            icon_type = "exclamation-sign" if row["status"] == "Unscheduled" else "ok-sign"

            folium.Marker(
                location=[float(row["lat"]), float(row["lon"])],
                popup=f"<b>{row['claim_id']}</b><br>{row['insured_name']}<br>{row['full_address']}",
                tooltip=f"{row['claim_id']} - {row['insured_name']}",
                icon=folium.Icon(color=marker_color, icon=icon_type)
            ).add_to(m)

            bounds.append([float(row["lat"]), float(row["lon"])])

        if bounds:
            m.fit_bounds(bounds, padding=(30, 30))

        folium.LayerControl().add_to(m)
        st_folium(m, width=1100, height=520, key="claims_map")

    st.markdown("---")

    # --- MANAGEMENT & CLAIMS POOL ---
    col_left, col_right = st.columns([1.5, 1])

    with col_left:
        st.subheader("📋 Active Claims Pool")
        show_status = st.multiselect("Filter Status View", ["Unscheduled", "Scheduled", "Ignored"], default=["Unscheduled", "Scheduled"])
        filtered_df = df[df["status"].isin(show_status)].copy()
        
        edited_df = st.data_editor(
            filtered_df[["claim_id", "insured_name", "full_address", "priority", "status", "scheduled_date", "inspection_time"]],
            key="claims_editor",
            disabled=["claim_id", "insured_name", "full_address"],
            use_container_width=True
        )

    selected_target_date_str = start_date.strftime("%Y-%m-%d")

    with col_right:
        st.subheader("🎯 Select Claim to Manage")
        claim_options = df["display_label"].tolist()
        
        default_index = 0
        if "selected_claim_id" in st.session_state:
            matching = [i for i, label in enumerate(claim_options) if label.startswith(str(st.session_state["selected_claim_id"]))]
            if matching: default_index = matching[0]

        selected_label = st.selectbox("Select Claim to Manage", claim_options, index=default_index)

        if selected_label:
            selected_claim_id = selected_label.split(" - ")[0]
            claim_mask = st.session_state.claims_df["claim_id"] == selected_claim_id
            current_claim = st.session_state.claims_df[claim_mask].iloc[0]
            
            st.write(f"**Claim Number:** `{current_claim['claim_id']}`")
            st.write(f"**Insured Name:** {current_claim['insured_name']}")
            st.write(f"**Address:** {current_claim['full_address']}")
            st.write(f"**Current Status:** `{current_claim['status']}`")
            
            st.markdown("---")

            if current_claim["status"] == "Scheduled":
                if current_claim["scheduled_date"]:
                    selected_target_date_str = str(current_claim["scheduled_date"])

                if st.button("Remove from Schedule", type="primary"):
                    st.session_state.claims_df.loc[claim_mask, "status"] = "Unscheduled"
                    st.session_state.claims_df.loc[claim_mask, "start_time"] = None
                    st.session_state.claims_df.loc[claim_mask, "end_time"] = None
                    st.session_state.claims_df.loc[claim_mask, "scheduled_date"] = ""
                    st.session_state.claims_df.loc[claim_mask, "inspection_time"] = ""
                    st.rerun()

            elif current_claim["status"] in ["Unscheduled", "Ignored"]:
                unbooked_slots = [s for s in all_slots if not is_slot_conflicting(s, st.session_state.claims_df, current_claim_id=selected_claim_id)]
                
                if unbooked_slots:
                    slot_labels = [s["slot_label"] for s in unbooked_slots]
                    selected_slot_label = st.selectbox("Choose Open Slot", slot_labels, index=0)
                    chosen_slot = next(s for s in unbooked_slots if s["slot_label"] == selected_slot_label)
                    selected_target_date_str = chosen_slot["date_str"]
                    
                    if st.button("Confirm & Lock Slot", type="primary"):
                        st.session_state.claims_df.loc[claim_mask, "status"] = "Scheduled"
                        st.session_state.claims_df.loc[claim_mask, "start_time"] = chosen_slot["start"]
                        st.session_state.claims_df.loc[claim_mask, "end_time"] = chosen_slot["end"]
                        st.session_state.claims_df.loc[claim_mask, "scheduled_date"] = chosen_slot["date_str"]
                        
                        start_dt = datetime.fromisoformat(chosen_slot["start"])
                        st.session_state.claims_df.loc[claim_mask, "inspection_time"] = start_dt.strftime("%H:%M")
                        st.rerun()

    # --- RECOMMENDATIONS ---
    st.markdown("---")
    st.subheader(f"💡 Recommended Next Claims for {selected_target_date_str}")
    
    recs = get_recommendations_for_day(st.session_state.claims_df, target_date_str=selected_target_date_str)
    
    if recs is not None and not recs.empty:
        for idx, rec_row in recs.head(5).iterrows():
            col_rec1, col_rec2 = st.columns([3, 1])
            with col_rec1:
                anchor_label = "anchor claim" if rec_row.get("anchor_type") == "anchor_claim" else "hotel base"
                st.markdown(f"**[{rec_row['claim_id']}] {rec_row['insured_name']}** — *{rec_row['full_address']}* (⏱️ `{rec_row['drive_time_mins']} mins` from {anchor_label})")
            with col_rec2:
                if st.button("Select to Manage", key=f"btn_rec_{rec_row['claim_id']}"):
                    st.session_state["selected_claim_id"] = str(rec_row["claim_id"])
                    st.rerun()
