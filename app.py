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

st.markdown("""
    <style>
        .stTabs [data-baseweb="tab-list"] {
            gap: 12px;
            background-color: #F1F5F9;
            padding: 8px 12px;
            border-radius: 12px;
            border: 2px solid #CBD5E1;
            margin-bottom: 20px;
        }

        .stTabs [data-baseweb="tab"] {
            height: 48px;
            font-weight: 700;
            font-size: 1.05rem;
            color: #334155;
            border-radius: 8px;
            padding: 0px 20px;
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
        }

        .stTabs [aria-selected="true"] {
            color: #FFFFFF !important;
            background-color: #2563EB !important;
            border-color: #1D4ED8 !important;
            box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);
        }
    </style>
""", unsafe_allow_html=True)

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
    step=0.25,
    help="Adjustable by 15-minute increments (e.g. 1.25 = 1 hr 15 min, 2.50 = 2 hr 30 min)"
)

start_time_input = st.sidebar.time_input("Day Start Time", value=datetime.strptime("08:00", "%H:%M").time())

all_slots = generate_available_slots(
    start_date, end_date, active_days, inspections_per_day, start_time_input, window_hrs
)

st.sidebar.markdown("---")

# --- INGESTION ---
st.subheader("1. Ingest Claims List")
uploaded_file = st.file_uploader("Upload CSV or Excel file (Header names auto-detected)", type=["csv", "xlsx"])

if uploaded_file is not None and st.session_state.claims_df is None:
    try:
        if uploaded_file.name.endswith(".csv"):
            raw_df = pd.read_csv(uploaded_file)
        else:
            raw_df = pd.read_excel(uploaded_file)
            
        st.session_state.claims_df = process_imported_table(raw_df)
        st.success(f"Successfully imported {len(st.session_state.claims_df)} claims!")
    except Exception as e:
        st.error(f"Error parsing table: {e}")

# --- DASHBOARD ---
if st.session_state.claims_df is not None:
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
            mime="text/calendar",
            type="secondary"
        )
        st.markdown(" ")

    tab_cal, tab_map = st.tabs(["📅 CALENDAR VIEW", "🛰️ SATELLITE MAP VIEW"])

    with tab_cal:
        st.caption("Click any scheduled claim event to select it for management below.")
        
        calendar_events = []
        scheduled_claims = df[df["status"] == "Scheduled"]
        
        for idx, row in scheduled_claims.iterrows():
            calendar_events.append({
                "id": str(row["claim_id"]),
                "title": f"[{row['claim_id']}] {row['insured_name']}",
                "start": str(row["start_time"]),
                "end": str(row["end_time"]),
                "backgroundColor": "#2563EB",
                "borderColor": "#1D4ED8"
            })

        calendar_options = {
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "timeGridWeek,timeGridDay,dayGridMonth"
            },
            "initialView": "timeGridWeek",
            "initialDate": start_date.strftime("%Y-%m-%d"),
            "slotMinTime": start_time_input.strftime("%H:%M:%S"),
            "slotMaxTime": "20:00:00",
            "editable": True,
        }

        cal_event = calendar(events=calendar_events, options=calendar_options, key="claims_calendar")
        
        if cal_event.get("eventClick"):
            clicked_id = cal_event["eventClick"]["event"]["id"]
            st.info(f"Selected claim from calendar: **{clicked_id}**")
            st.session_state["selected_claim_id"] = clicked_id

    with tab_map:
        st.caption("🔴 Red markers = Unscheduled Claims | 🎨 Colored markers = Scheduled on same date")
        
        esri_satellite_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        
        m = folium.Map(
            location=[29.4241, -98.4936],
            zoom_start=11,
            tiles=esri_satellite_url,
            attr="Esri, Maxar, Earthstar Geographics"
        )
        
        folium.TileLayer('OpenStreetMap', name='Street View').add_to(m)
        
        day_colors = ["blue", "green", "purple", "orange", "darkred", "cadetblue", "darkgreen", "pink"]
        scheduled_dates = sorted(df[df["status"] == "Scheduled"]["scheduled_date"].dropna().unique())
        date_color_map = {d: day_colors[i % len(day_colors)] for i, d in enumerate(scheduled_dates)}
        
        for idx, row in df.iterrows():
            if row["status"] == "Ignored":
                continue
                
            if row["status"] == "Unscheduled":
                marker_color = "red"
                popup_text = f"<b>Unscheduled</b><br>ID: {row['claim_id']}<br>{row['insured_name']}<br>{row['full_address']}"
                icon_type = "exclamation-sign"
            else:
                scheduled_date = row.get("scheduled_date", "Scheduled")
                marker_color = date_color_map.get(scheduled_date, "blue")
                popup_text = f"<b>Scheduled ({scheduled_date})</b><br>ID: {row['claim_id']}<br>{row['insured_name']}<br>{row['full_address']}"
                icon_type = "ok-sign"

            folium.Marker(
                location=[row["lat"], row["lon"]],
                popup=popup_text,
                tooltip=f"{row['claim_id']} - {row['insured_name']}",
                icon=folium.Icon(color=marker_color, icon=icon_type)
            ).add_to(m)

        folium.LayerControl().add_to(m)
        st_folium(m, width=1100, height=520)

    st.markdown("---")

    # --- MANAGEMENT & CLAIMS POOL ---
    col_left, col_right = st.columns([1.5, 1])

    with col_left:
        st.subheader("📋 Active Claims Pool")
        
        show_status = st.multiselect("Filter Status View", ["Unscheduled", "Scheduled", "Ignored"], default=["Unscheduled", "Scheduled"])
        filtered_df = df[df["status"].isin(show_status)]
        
        st.caption("Double-click the 'priority' column (1=Urgent, 5=Low) to adjust precedence directly.")
        
        edited_df = st.data_editor(
            filtered_df[["claim_id", "insured_name", "full_address", "priority", "status"]],
            key="claims_editor",
            disabled=["claim_id", "insured_name", "full_address", "status"],
            use_container_width=True
        )
        
        priority_changed = False
        for idx, row in edited_df.iterrows():
            cid = row["claim_id"]
            current_val = st.session_state.claims_df.loc[st.session_state.claims_df["claim_id"] == cid, "priority"].values[0]
            if current_val != row["priority"]:
                st.session_state.claims_df.loc[st.session_state.claims_df["claim_id"] == cid, "priority"] = row["priority"]
                priority_changed = True

        if priority_changed:
            st.toast("Priorities updated!")
            st.rerun()

    selected_target_date_str = start_date.strftime("%Y-%m-%d")

    with col_right:
        st.subheader("🎯 Select Claim to Manage")
        
        claim_options = df["display_label"].tolist()
        
        default_index = 0
        if "selected_claim_id" in st.session_state:
            matching = [i for i, label in enumerate(claim_options) if label.startswith(str(st.session_state["selected_claim_id"]))]
            if matching:
                default_index = matching[0]

        selected_label = st.selectbox("Select Claim to Manage (Claim ID - Insured Name)", claim_options, index=default_index)

        if selected_label:
            selected_claim_id = selected_label.split(" - ")[0]
            claim_mask = st.session_state.claims_df["claim_id"] == selected_claim_id
            current_claim = st.session_state.claims_df[claim_mask].iloc[0]
            
            st.write(f"**Claim Number:** `{current_claim['claim_id']}`")
            st.write(f"**Insured Name:** {current_claim['insured_name']}")
            st.write(f"**Address:** {current_claim['full_address']}")
            st.write(f"**Priority Tier:** `{current_claim['priority']}`")
            st.write(f"**Current Status:** `{current_claim['status']}`")
            
            st.markdown("---")

            if current_claim["status"] == "Scheduled":
                st.warning("⚠️ Claim assigned to slot. Unassign before deleting or archiving.")
                
                if current_claim["scheduled_date"]:
                    selected_target_date_str = current_claim["scheduled_date"]

                if st.button("Remove from Schedule", type="primary"):
                    st.session_state.claims_df.loc[claim_mask, "status"] = "Unscheduled"
                    st.session_state.claims_df.loc[claim_mask, "start_time"] = None
                    st.session_state.claims_df.loc[claim_mask, "end_time"] = None
                    st.session_state.claims_df.loc[claim_mask, "scheduled_date"] = None
                    st.success("Claim removed from slot!")
                    st.rerun()

            elif current_claim["status"] in ["Unscheduled", "Ignored"]:
                st.markdown("#### Assign to Calendar Slot Window")
                
                unbooked_slots = [s for s in all_slots if not is_slot_conflicting(s, st.session_state.claims_df, current_claim_id=selected_claim_id)]
                
                if unbooked_slots:
                    slot_labels = [s["slot_label"] for s in unbooked_slots]
                    selected_slot_label = st.selectbox("Choose Open Inspection Slot", slot_labels)
                    
                    chosen_slot = next(s for s in unbooked_slots if s["slot_label"] == selected_slot_label)
                    selected_target_date_str = chosen_slot["date_str"]
                    
                    if st.button("Confirm & Lock Slot", type="primary"):
                        st.session_state.claims_df.loc[claim_mask, "status"] = "Scheduled"
                        st.session_state.claims_df.loc[claim_mask, "start_time"] = chosen_slot["start"]
                        st.session_state.claims_df.loc[claim_mask, "end_time"] = chosen_slot["end"]
                        st.session_state.claims_df.loc[claim_mask, "scheduled_date"] = chosen_slot["date_str"]
                        st.success(f"Locked {selected_claim_id} into {selected_slot_label}")
                        st.rerun()
                else:
                    st.warning("No open slots available.")

                st.markdown("---")
                st.markdown("#### Other Actions")
                c_act1, c_act2 = st.columns(2)
                
                with c_act1:
                    if st.button("Ignore / Archive"):
                        st.session_state.claims_df.loc[claim_mask, "status"] = "Ignored"
                        st.rerun()
                
                with c_act2:
                    if st.button("Delete Claim"):
                        st.session_state.claims_df = st.session_state.claims_df[~claim_mask].reset_index(drop=True)
                        st.success("Claim permanently removed.")
                        st.rerun()

    # --- DAY-ANCHORED RECOMMENDATIONS SECTION ---
    st.markdown("---")
    st.subheader(f"💡 Recommended Next Claims for {selected_target_date_str}")
    
    with st.spinner("Calculating drive times via road network..."):
        recs = get_recommendations_for_day(st.session_state.claims_df, target_date_str=selected_target_date_str)
    
    if recs is not None and not recs.empty:
        top_recs = recs.head(5)
        for idx, rec_row in top_recs.iterrows():
            col_rec1, col_rec2 = st.columns([3, 1])
            with col_rec1:
                anchor_type = rec_row.get("anchor_type", "hotel")
                anchor_label = "anchor claim" if anchor_type == "anchor_claim" else "hotel base"
                
                drive_info = f" (⏱️ `{rec_row['drive_time_mins']} mins` drive | `{rec_row['drive_miles']} mi` from {anchor_label})"
                
                st.markdown(
                    f"**[{rec_row['claim_id']}] {rec_row['insured_name']}** — *{rec_row['full_address']}* | Priority Tier: `{rec_row['priority']}`{drive_info}"
                )
            with col_rec2:
                if st.button("Select to Manage", key=f"btn_rec_{rec_row['claim_id']}"):
                    st.session_state["selected_claim_id"] = str(rec_row["claim_id"])
                    st.rerun()
    else:
        st.info("All claims are scheduled or archived.")