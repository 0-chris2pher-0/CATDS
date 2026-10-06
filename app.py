import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
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

# --- INITIALIZE SESSION STATE ---
if "claims_df" not in st.session_state:
    st.session_state["claims_df"] = None

if "scheduled_slots" not in st.session_state:
    st.session_state["scheduled_slots"] = []

# --- SIDEBAR: DATA IMPORT & CONFIGURATION ---
st.sidebar.header("1. Data Ingestion")
uploaded_file = st.sidebar.file_uploader("Upload Claims File (CSV/Excel)", type=["csv", "xlsx", "xls"])

if uploaded_file is not None:
    if st.sidebar.button("📥 Process & Geocode File", type="primary"):
        with st.spinner("Processing file & batch geocoding..."):
            try:
                if uploaded_file.name.endswith(".csv"):
                    raw_df = pd.read_csv(uploaded_file)
                else:
                    raw_df = pd.read_excel(uploaded_file)
                
                processed_df = process_imported_table(raw_df)
                st.session_state["claims_df"] = processed_df
                st.sidebar.success(f"Successfully processed {len(processed_df)} claims!")
            except Exception as e:
                st.sidebar.error(f"Error processing file: {e}")

st.sidebar.markdown("---")
st.sidebar.header("2. Working Window Settings")

working_days = st.sidebar.multiselect(
    "Active Work Days",
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    default=["Mon", "Tue", "Wed", "Thu", "Fri"]
)

inspections_per_day = st.sidebar.number_input("Inspections / Day", min_value=1, max_value=10, value=4)
start_time_input = st.sidebar.time_input("First Slot Start Time", value=time(8, 0))
window_hrs = st.sidebar.number_input("Inspection Window (Hours)", min_value=0.5, max_value=8.0, value=2.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("3. App Sync")
if st.sidebar.button("🔄 Refresh Recommendations & Sync Priority", use_container_width=True):
    st.rerun()

# --- MAIN APP LAYOUT ---
if st.session_state["claims_df"] is None:
    st.info("👆 Please upload and process a claims CSV or Excel file in the sidebar to get started.")
else:
    # --- TOP ROW: METRICS SUMMARY ---
    df = st.session_state["claims_df"]
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("Total Claims", len(df))
    col_m2.metric("Unscheduled Claims", len(df[df["status"] == "Unscheduled"]))
    col_m3.metric("Scheduled Claims", len(df[df["status"] == "Scheduled"]))
    
    # Priority count (claims with an assigned numerical priority)
    prio_count = df["priority"].dropna().count() if "priority" in df.columns else 0
    col_m4.metric("Prioritized Claims", prio_count)

    st.markdown("---")

    # --- TABBED MAIN NAVIGATION ---
    tab_editor, tab_map_scheduler, tab_recommendations, tab_export = st.tabs([
        "📋 Claims Master Editor",
        "🗺️ Map & Manual Scheduler",
        "💡 Smart Recommendations",
        "📅 Calendar Export"
    ])

    # ---------------------------------------------------------
    # TAB 1: CLAIMS MASTER EDITOR (Data Editor)
    # ---------------------------------------------------------
    with tab_editor:
        st.subheader("Edit Priorities & Claim Statuses")
        st.caption("Double-click any cell to edit **Priority** (1 = Highest Priority, leave blank for normal) or change status. Priority syncs immediately upon clicking Refresh.")

        edited_df = st.data_editor(
            st.session_state["claims_df"],
            column_config={
                "priority": st.column_config.NumberColumn(
                    "Priority Rank",
                    help="Enter priority (1 = highest rank). Leave blank for default.",
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
                "lat": None,  # Hide raw coordinates from editor UI
                "lon": None
            },
            hide_index=True,
            use_container_width=True,
            key="master_editor"
        )

        # Sync changes back to session state
        st.session_state["claims_df"] = edited_df

    # ---------------------------------------------------------
    # TAB 2: MAP & MANUAL SCHEDULER
    # ---------------------------------------------------------
    with tab_map_scheduler:
        col_left, col_right = st.columns([1.2, 1])

        with col_left:
            st.subheader("Interactive Claims Map")
            
            # Center map around average coordinates
            mean_lat = df["lat"].mean()
            mean_lon = df["lon"].mean()
            m = folium.Map(location=[mean_lat, mean_lon], zoom_start=9)

            for _, row in df.iterrows():
                prio_str = f"P{int(row['priority'])}" if pd.notna(row["priority"]) and str(row["priority"]).strip() not in ["", "nan", "None"] else "No Priority"
                popup_text = f"<b>{row['claim_id']}</b><br>{row['insured_name']}<br>{row['full_address']}<br>Priority: {prio_str}<br>Status: {row['status']}"
                
                icon_color = "green" if row["status"] == "Scheduled" else "blue"
                if prio_str != "No Priority" and row["status"] == "Unscheduled":
                    icon_color = "orange"

                folium.Marker(
                    location=[row["lat"], row["lon"]],
                    popup=folium.Popup(popup_text, max_width=250),
                    tooltip=f"{row['claim_id']} ({prio_str})",
                    icon=folium.Icon(color=icon_color, icon="info-sign")
                ).add_to(m)

            st_folium(m, width=700, height=500)

        with col_right:
            st.subheader("Assign Inspection Slot")
            
            # Select Claim
            claim_options = df["display_label"].tolist()
            selected_claim_label = st.selectbox("Select Claim to Schedule", claim_options)
            
            selected_claim = df[df["display_label"] == selected_claim_label].iloc[0]
            st.info(f"**Selected Address:** {selected_claim['full_address']}")

            # Date Range for Available Slots
            sched_date = st.date_input("Target Date", value=date.today())
            
            # Generate available time windows for selected day
            avail_slots = generate_available_slots(
                start_date=sched_date,
                end_date=sched_date,
                active_days=working_days,
                inspections_per_day=inspections_per_day,
                start_time_input=start_time_input,
                window_hrs=window_hrs
            )

            if not avail_slots:
                st.warning("No slots generated for selected date. Check active working days in sidebar.")
            else:
                slot_labels = [s["slot_label"] for s in avail_slots]
                selected_slot_label = st.selectbox("Select Time Slot", slot_labels)
                
                chosen_slot = next(s for s in avail_slots if s["slot_label"] == selected_slot_label)
                
                # Check slot conflicts
                has_conflict = is_slot_conflicting(chosen_slot, df, selected_claim["claim_id"])
                if has_conflict:
                    st.error("⚠️ Conflict Warning: Another claim is already scheduled in this overlapping slot!")

                if st.button("📌 Confirm Booking", type="primary", use_container_width=True):
                    idx = df[df["claim_id"] == selected_claim["claim_id"]].index[0]
                    st.session_state["claims_df"].at[idx, "status"] = "Scheduled"
                    st.session_state["claims_df"].at[idx, "start_time"] = chosen_slot["start"]
                    st.session_state["claims_df"].at[idx, "end_time"] = chosen_slot["end"]
                    st.session_state["claims_df"].at[idx, "scheduled_date"] = chosen_slot["date_str"]
                    st.session_state["claims_df"].at[idx, "inspection_time"] = chosen_slot["slot_label"].split("|")[1].strip()
                    
                    st.success(f"Successfully scheduled claim {selected_claim['claim_id']} for {chosen_slot['slot_label']}!")
                    st.rerun()

    # ---------------------------------------------------------
    # TAB 3: SMART RECOMMENDATIONS
    # ---------------------------------------------------------
    with tab_recommendations:
        st.subheader("Optimized Route Recommendations")
        rec_target_date = st.date_input("Select Target Date for Route Proximity Calculation", value=date.today())
        rec_target_date_str = rec_target_date.strftime("%Y-%m-%d")

        tab_rec_unscheduled, tab_rec_scheduled = st.tabs([
            "📋 Unscheduled Recommendations", 
            "📅 Scheduled (Rescheduling Candidates)"
        ])

        with tab_rec_unscheduled:
            st.caption("Prioritizes claims by **Priority Rank (1 = Highest)** first, then by shortest driving time from scheduled anchors or center cluster.")
            
            rec_un_df = get_recommendations_for_day(
                st.session_state["claims_df"],
                target_date_str=rec_target_date_str,
                status_filter="Unscheduled"
            )

            if rec_un_df is not None and not rec_un_df.empty:
                st.dataframe(
                    rec_un_df[["priority", "claim_id", "insured_name", "drive_miles", "drive_time_mins", "full_address"]],
                    column_config={
                        "priority": st.column_config.NumberColumn("Priority Rank", format="%d"),
                        "claim_id": "Claim ID",
                        "insured_name": "Insured",
                        "drive_miles": st.column_config.NumberColumn("Est. Distance (mi)", format="%.1f"),
                        "drive_time_mins": st.column_config.NumberColumn("Est. Drive (mins)", format="%d"),
                        "full_address": "Address"
                    },
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.info("No unscheduled claims available for recommendation.")

        with tab_rec_scheduled:
            st.caption("View currently scheduled claims sorted by priority rank and driving time. Useful for finding fast rescheduling candidates when cancellations occur.")
            
            rec_sch_df = get_recommendations_for_day(
                st.session_state["claims_df"],
                target_date_str=rec_target_date_str,
                status_filter="Scheduled"
            )

            if rec_sch_df is not None and not rec_sch_df.empty:
                st.dataframe(
                    rec_sch_df[["priority", "claim_id", "insured_name", "scheduled_date", "inspection_time", "drive_miles", "drive_time_mins", "full_address"]],
                    column_config={
                        "priority": st.column_config.NumberColumn("Priority Rank", format="%d"),
                        "claim_id": "Claim ID",
                        "insured_name": "Insured",
                        "scheduled_date": "Scheduled Date",
                        "inspection_time": "Time Window",
                        "drive_miles": st.column_config.NumberColumn("Est. Distance (mi)", format="%.1f"),
                        "drive_time_mins": st.column_config.NumberColumn("Est. Drive (mins)", format="%d"),
                        "full_address": "Address"
                    },
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.info("No scheduled claims found.")

    # ---------------------------------------------------------
    # TAB 4: CALENDAR EXPORT (.ICS)
    # ---------------------------------------------------------
    with tab_export:
        st.subheader("Export Scheduled Calendar")
        st.write("Download an `.ics` file containing all currently scheduled inspections to sync with Outlook, Google Calendar, or Apple Calendar.")

        scheduled_claims = df[df["status"] == "Scheduled"]

        if scheduled_claims.empty:
            st.warning("No claims have been scheduled yet. Schedule claims in the 'Map & Manual Scheduler' tab first.")
        else:
            st.write(f"**Total Scheduled Inspections:** {len(scheduled_claims)}")
            
            st.dataframe(
                scheduled_claims[["claim_id", "insured_name", "scheduled_date", "inspection_time", "full_address"]],
                hide_index=True,
                use_container_width=True
            )

            ics_data = export_claims_to_ics(df)

            st.download_button(
                label="📥 Download .ics Calendar File",
                data=ics_data,
                file_name=f"cat_inspection_schedule_{datetime.now().strftime('%Y%m%d')}.ics",
                mime="text/calendar",
                type="primary"
            )
