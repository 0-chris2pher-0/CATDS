import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time, timedelta, date

from engine import (
    process_imported_table,
    generate_available_slots,
    is_slot_conflicting,
    get_recommendations_for_day,
    export_claims_to_ics
)

st.set_page_config(page_title="CAT Claims Field Scheduler", layout="wide")

st.title("📌 CAT Dynamic Scheduler")

# --- INITIALIZE SESSION STATE ---
if "claims_df" not in st.session_state:
    st.session_state["claims_df"] = None

# --- SIDEBAR: DATA IMPORT & CONFIGURATION ---
st.sidebar.header("1. Data Import")
uploaded_file = st.sidebar.file_uploader("Upload Claims CSV or Excel", type=["csv", "xlsx"])

if uploaded_file is not None:
    if st.sidebar.button("Process & Geocode File"):
        try:
            if uploaded_file.name.endswith(".csv"):
                raw_df = pd.read_csv(uploaded_file)
            else:
                raw_df = pd.read_excel(uploaded_file)

            with st.spinner("Parsing file and geocoding addresses..."):
                processed_df = process_imported_table(raw_df)
                st.session_state["claims_df"] = processed_df
                st.success(f"Successfully processed {len(processed_df)} claims!")
        except Exception as e:
            st.error(f"Error processing file: {e}")

st.sidebar.header("2. Scheduling Controls")
start_date = st.sidebar.date_input("Start Date", value=date.today())
end_date = st.sidebar.date_input("End Date", value=date.today() + timedelta(days=5))
active_days = st.sidebar.multiselect("Working Days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], default=["Mon", "Tue", "Wed", "Thu", "Fri"])
inspections_per_day = st.sidebar.number_input("Inspections Per Day", min_value=1, max_value=10, value=4)
start_time_val = st.sidebar.time_input("Day Start Time", value=time(8, 0))
window_hours = st.sidebar.number_input("Slot Window (Hours)", min_value=0.5, max_value=4.0, value=2.0, step=0.5)

# Actions Block
st.sidebar.subheader("Actions")
if st.sidebar.button("🔄 Refresh & Sync Data Edits"):
    st.rerun()

# --- MAIN CONTENT AREA ---
if st.session_state["claims_df"] is not None:
    claims_df = st.session_state["claims_df"]

    # --- TABBED MAIN NAVIGATION ---
    tab_editor, tab_map, tab_recommend, tab_export = st.tabs([
        "📋 Claims Table & Editor",
        "🗺️ Interactive Map & Calendar",
        "💡 Route Recommendations",
        "📅 Export Calendar"
    ])

    # 1. CLAIMS EDITOR TAB
    with tab_editor:
        st.subheader("Interactive Claims Master Table")
        st.caption("You can edit priorities (1 = Highest), update statuses, or adjust coordinates directly below. Click '🔄 Refresh & Sync Data Edits' in the sidebar to sync changes.")
        
        edited_df = st.data_editor(
            claims_df,
            num_rows="dynamic",
            use_container_width=True,
            key="claims_editor"
        )
        # Update session state with edits
        st.session_state["claims_df"] = edited_df

    # 2. MAP & CALENDAR TAB
    with tab_map:
        col_map, col_sched = st.columns([3, 2])

        with col_map:
            st.subheader("Claims Map View")
            if not claims_df.empty:
                avg_lat = claims_df["lat"].mean()
                avg_lon = claims_df["lon"].mean()
                m = folium.Map(location=[avg_lat, avg_lon], zoom_start=11)
                
                marker_cluster = MarkerCluster().add_to(m)

                for _, row in claims_df.iterrows():
                    color = "green" if row["status"] == "Scheduled" else "red"
                    popup_text = f"<b>{row['claim_id']}</b><br>{row['insured_name']}<br>Status: {row['status']}<br>Priority: {row['priority'] or 'Unassigned'}"
                    
                    folium.Marker(
                        location=[row["lat"], row["lon"]],
                        popup=popup_text,
                        tooltip=f"{row['claim_id']} - {row['insured_name']}",
                        icon=folium.Icon(color=color, icon="info-sign")
                    ).add_to(marker_cluster)

                st_folium(m, width=700, height=500)

        with col_sched:
            st.subheader("Manual Slot Scheduling")
            
            available_slots = generate_available_slots(
                start_date, end_date, active_days, inspections_per_day, start_time_val, window_hours
            )

            claim_options = claims_df["claim_id"].tolist()
            selected_claim_id = st.selectbox("Select Claim to Schedule", claim_options)

            if available_slots:
                slot_labels = [s["slot_label"] for s in available_slots]
                selected_slot_label = st.selectbox("Select Inspection Slot", slot_labels)

                selected_slot = next(s for s in available_slots if s["slot_label"] == selected_slot_label)
                
                is_conflict = is_slot_conflicting(selected_slot, claims_df, selected_claim_id)
                if is_conflict:
                    st.warning("⚠️ Conflict Detected! Another claim is scheduled during this time slot.")

                if st.button("Confirm Schedule"):
                    idx = claims_df[claims_df["claim_id"] == selected_claim_id].index[0]
                    claims_df.at[idx, "status"] = "Scheduled"
                    claims_df.at[idx, "scheduled_date"] = selected_slot["date_str"]
                    claims_df.at[idx, "start_time"] = selected_slot["start"]
                    claims_df.at[idx, "end_time"] = selected_slot["end"]
                    claims_df.at[idx, "inspection_time"] = selected_slot_label.split("|")[1].strip()
                    
                    st.session_state["claims_df"] = claims_df
                    st.success(f"Successfully scheduled claim {selected_claim_id}!")
                    st.rerun()

    # 3. RECOMMENDATIONS TAB (Unscheduled & Scheduled Tabs)
    with tab_recommend:
        st.subheader("Route & Priority Recommendations")
        
        target_date_str = st.date_input("Target Date for Route Optimization", value=start_date).strftime("%Y-%m-%d")

        rec_tab_unscheduled, rec_tab_scheduled = st.tabs([
            "📋 Unscheduled Claims", 
            "📅 Scheduled Claims (Rescheduling View)"
        ])

        with rec_tab_unscheduled:
            st.caption("Prioritized unscheduled claims based on Priority Rank (1 = Highest) and Drive Time proximity.")
            rec_unscheduled = get_recommendations_for_day(
                st.session_state["claims_df"], 
                target_date_str=target_date_str, 
                status_filter="Unscheduled"
            )
            if rec_unscheduled is not None and not rec_unscheduled.empty:
                display_cols = ["priority", "claim_id", "insured_name", "drive_miles", "drive_time_mins", "full_address"]
                st.dataframe(rec_unscheduled[display_cols], use_container_width=True)
            else:
                st.info("No unscheduled claims found.")

        with rec_tab_scheduled:
            st.caption("Currently scheduled claims sorted by Priority Rank and Drive Time to help identify candidates for bumping up after cancellations.")
            rec_scheduled = get_recommendations_for_day(
                st.session_state["claims_df"], 
                target_date_str=target_date_str, 
                status_filter="Scheduled"
            )
            if rec_scheduled is not None and not rec_scheduled.empty:
                display_cols = ["priority", "claim_id", "insured_name", "scheduled_date", "inspection_time", "drive_miles", "drive_time_mins", "full_address"]
                st.dataframe(rec_scheduled[display_cols], use_container_width=True)
            else:
                st.info("No scheduled claims found for this date.")

    # 4. EXPORT TAB
    with tab_export:
        st.subheader("Export Calendar Appointments")
        st.write("Export all currently scheduled claims to an iCalendar (.ics) file compatible with Outlook, Google Calendar, and Apple Calendar.")

        scheduled_count = len(claims_df[claims_df["status"] == "Scheduled"])
        st.info(f"Total Scheduled Inspections: {scheduled_count}")

        if scheduled_count > 0:
            ics_data = export_claims_to_ics(claims_df)
            st.download_button(
                label="📥 Download .ics Calendar File",
                data=ics_data,
                file_name="cat_inspections_schedule.ics",
                mime="text/calendar"
            )

else:
    st.info("Please upload and process a claims dataset using the sidebar to get started.")
