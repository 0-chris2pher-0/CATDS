import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_calendar import calendar
from datetime import datetime, date, time

from engine import (
    process_imported_table,
    generate_available_slots,
    is_slot_conflicting,
    get_recommendations_for_day,
    export_claims_to_ics
)

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="CAT Claims Scheduler",
    page_icon="📅",
    layout="wide"
)

st.title("⚡ CAT Claims Inspection Scheduler")

# --- SESSION STATE INITIALIZATION ---
if "claims_df" not in st.session_state:
    st.session_state["claims_df"] = None

# --- MAIN PAGE FILE INGESTION (RESTORED) ---
st.subheader("1. File Ingestion")
uploaded_file = st.file_uploader("Upload Claims File (CSV or Excel)", type=["csv", "xlsx", "xls"])

if uploaded_file is not None:
    if st.button("📥 Process & Geocode File", type="primary"):
        with st.spinner("Processing file & batch geocoding..."):
            try:
                if uploaded_file.name.endswith(".csv"):
                    raw_df = pd.read_csv(uploaded_file)
                else:
                    raw_df = pd.read_excel(uploaded_file)
                
                processed_df = process_imported_table(raw_df)
                st.session_state["claims_df"] = processed_df
                st.success(f"Successfully loaded and geocoded {len(processed_df)} claims!")
            except Exception as e:
                st.error(f"Error processing file: {e}")

st.markdown("---")

if st.session_state["claims_df"] is not None:
    df = st.session_state["claims_df"]

    # --- SIDEBAR: SCHEDULING SETTINGS ONLY ---
    st.sidebar.header("Working Window Settings")
    working_days = st.sidebar.multiselect(
        "Active Work Days",
        ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        default=["Mon", "Tue", "Wed", "Thu", "Fri"]
    )
    inspections_per_day = st.sidebar.number_input("Inspections / Day", min_value=1, max_value=10, value=4)
    start_time_input = st.sidebar.time_input("First Slot Start Time", value=time(8, 0))
    window_hrs = st.sidebar.number_input("Inspection Window (Hours)", min_value=0.5, max_value=8.0, value=2.0, step=0.5)

    if st.sidebar.button("🔄 Refresh Data & Priorities", use_container_width=True):
        st.rerun()

    # --- MAIN PAGE SECTION 2: CLAIMS MASTER TABLE (DATA EDITOR) ---
    st.subheader("2. Claims Master List & Priority Rank")
    st.caption("Edit priority rank (1 = highest priority, leave blank for normal) or status below:")
    
    edited_df = st.data_editor(
        df,
        column_config={
            "priority": st.column_config.NumberColumn(
                "Priority Rank",
                help="1 = Highest priority. Blanks sort after all numerical ranks.",
                min_value=1,
                max_value=100,
                step=1,
                format="%d"
            ),
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=["Unscheduled", "Scheduled", "Completed", "Cancelled"],
                required=True
            ),
            "claim_id": st.column_config.TextColumn("Claim ID", disabled=True),
            "insured_name": st.column_config.TextColumn("Insured Name", disabled=True),
            "full_address": st.column_config.TextColumn("Address", disabled=True),
            "lat": None,
            "lon": None
        },
        hide_index=True,
        use_container_width=True,
        key="main_claims_editor"
    )
    st.session_state["claims_df"] = edited_df

    st.markdown("---")

    # --- MAIN PAGE SECTION 3: MAP & MANUAL SCHEDULER ---
    st.subheader("3. Map & Manual Slot Assignment")
    col_map, col_sched = st.columns([1.2, 1])

    with col_map:
        mean_lat = df["lat"].mean()
        mean_lon = df["lon"].mean()
        m = folium.Map(location=[mean_lat, mean_lon], zoom_start=9)

        for _, row in df.iterrows():
            prio_str = f"P{int(row['priority'])}" if pd.notna(row["priority"]) and str(row["priority"]).strip() not in ["", "nan", "None"] else "No Priority"
            popup_text = f"<b>{row['claim_id']}</b><br>{row['insured_name']}<br>{row['full_address']}<br>Priority: {prio_str}<br>Status: {row['status']}"
            
            icon_color = "green" if row["status"] == "Scheduled" else ("orange" if prio_str != "No Priority" else "blue")

            folium.Marker(
                location=[row["lat"], row["lon"]],
                popup=folium.Popup(popup_text, max_width=250),
                tooltip=f"{row['claim_id']} ({prio_str})",
                icon=folium.Icon(color=icon_color, icon="info-sign")
            ).add_to(m)

        st_folium(m, width=650, height=450)

    with col_sched:
        selected_claim_label = st.selectbox("Select Claim", df["display_label"].tolist())
        selected_claim = df[df["display_label"] == selected_claim_label].iloc[0]
        st.write(f"**Address:** {selected_claim['full_address']}")

        sched_date = st.date_input("Target Date", value=date.today())
        
        avail_slots = generate_available_slots(
            start_date=sched_date,
            end_date=sched_date,
            active_days=working_days,
            inspections_per_day=inspections_per_day,
            start_time_input=start_time_input,
            window_hrs=window_hrs
        )

        if avail_slots:
            slot_labels = [s["slot_label"] for s in avail_slots]
            selected_slot_label = st.selectbox("Select Time Slot", slot_labels)
            chosen_slot = next(s for s in avail_slots if s["slot_label"] == selected_slot_label)

            if is_slot_conflicting(chosen_slot, df, selected_claim["claim_id"]):
                st.error("⚠️ Conflict: Another claim is already scheduled in this slot!")

            if st.button("📌 Schedule Claim", type="primary", use_container_width=True):
                idx = df[df["claim_id"] == selected_claim["claim_id"]].index[0]
                st.session_state["claims_df"].at[idx, "status"] = "Scheduled"
                st.session_state["claims_df"].at[idx, "start_time"] = chosen_slot["start"]
                st.session_state["claims_df"].at[idx, "end_time"] = chosen_slot["end"]
                st.session_state["claims_df"].at[idx, "scheduled_date"] = chosen_slot["date_str"]
                st.session_state["claims_df"].at[idx, "inspection_time"] = chosen_slot["slot_label"].split("|")[1].strip()
                st.success(f"Scheduled {selected_claim['claim_id']}!")
                st.rerun()

    st.markdown("---")

    # --- MAIN PAGE SECTION 4: ROUTE RECOMMENDATIONS ---
    st.subheader("4. Smart Recommendations (Priority Rank + Drive Time)")
    rec_date = st.date_input("Target Date for Route Optimization", value=date.today(), key="rec_date")
    rec_date_str = rec_date.strftime("%Y-%m-%d")

    rec_unscheduled = get_recommendations_for_day(df, target_date_str=rec_date_str, status_filter="Unscheduled")
    if rec_unscheduled is not None and not rec_unscheduled.empty:
        st.dataframe(
            rec_unscheduled[["priority", "claim_id", "insured_name", "drive_miles", "drive_time_mins", "full_address"]],
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("No unscheduled claims found.")

    st.markdown("---")

    # --- MAIN PAGE SECTION 5: INTERACTIVE CALENDAR & EXPORT (RESTORED) ---
    st.subheader("5. Inspection Calendar")
    
    # Build events for streamlit-calendar
    calendar_events = []
    scheduled_claims = df[df["status"] == "Scheduled"]

    for _, row in scheduled_claims.iterrows():
        if pd.notna(row["start_time"]) and pd.notna(row["end_time"]) and str(row["start_time"]) != "":
            calendar_events.append({
                "title": f"{row['claim_id']} - {row['insured_name']}",
                "start": str(row["start_time"]),
                "end": str(row["end_time"]),
                "color": "#28a745"
            })

    calendar_options = {
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,timeGridWeek,timeGridDay"
        },
        "initialView": "timeGridWeek",
        "slotMinTime": "07:00:00",
        "slotMaxTime": "19:00:00"
    }

    calendar(events=calendar_events, options=calendar_options, key="inspection_calendar")

    # Calendar Export
    st.subheader("Export Schedule")
    if not scheduled_claims.empty:
        ics_data = export_claims_to_ics(df)
        st.download_button(
            label="📥 Download .ics Calendar File",
            data=ics_data,
            file_name=f"cat_inspection_schedule_{datetime.now().strftime('%Y%m%d')}.ics",
            mime="text/calendar"
        )
    else:
        st.caption("No scheduled claims to export yet.")
