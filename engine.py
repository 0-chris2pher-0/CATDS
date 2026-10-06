import pandas as pd
import numpy as np
import requests
import streamlit as st
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

# --- GEOCODING & ROUTING UTILITIES ---

@st.cache_data(show_spinner=False)
def geocode_address(address: str) -> tuple[float, float]:
    """
    Geocodes an address string using Nominatim with caching and error handling.
    """
    clean_addr = str(address).strip()
    if not clean_addr or clean_addr.lower() == "nan":
        return 29.4241, -98.4936  # Default fallback (San Antonio, TX)

    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": clean_addr,
            "format": "json",
            "limit": 1
        }
        headers = {
            "User-Agent": "CATClaimsSchedulerApp/2.0 (contact@example.com)"
        }
        resp = requests.get(url, params=params, headers=headers, timeout=4)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass

    # Standard fallback position if geocoding fails
    return 29.4241, -98.4936


def get_osrm_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> tuple[float, float]:
    """
    Calculates driving distance (miles) and duration (minutes) between two points using OSRM.
    Fallback to Haversine approximation if service is unreachable.
    """
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}"
        params = {"overview": "false"}
        resp = requests.get(url, params=params, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if "routes" in data and len(data["routes"]) > 0:
                meters = data["routes"][0]["distance"]
                seconds = data["routes"][0]["duration"]
                miles = round(meters / 1609.34, 1)
                minutes = int(round(seconds / 60.0))
                return miles, minutes
    except Exception:
        pass

    # Fallback: Haversine distance estimate
    R = 3958.8  # Earth radius in miles
    dlat = np.radians(end_lat - start_lat)
    dlon = np.radians(end_lon - start_lon)
    a = np.sin(dlat / 2)**2 + np.cos(np.radians(start_lat)) * np.cos(np.radians(end_lat)) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    miles = round(R * c, 1)
    minutes = int(round(miles * 2.0))
    return miles, minutes


# --- TABLE INGESTION & PARSING ---

def process_imported_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Processes imported CSV/Excel dataframe by assembling addresses split across
    multiple columns (Street, Town/City, State, Zip) or picking up a full address column.
    """
    col_map = {str(c).strip().lower(): c for c in df.columns}
    
    claim_col = None
    insured_col = None
    street_col = None
    city_col = None
    state_col = None
    zip_col = None
    full_addr_col = None

    # Step 1: Check for explicit single Full Address column first
    for low_c, orig_c in col_map.items():
        if any(k == low_c for k in ["full address", "full_address", "loss address", "property address", "location address", "site address"]):
            full_addr_col = orig_c
            break

    # Step 2: Flexible matching for split address columns (street, town, state, zip)
    for low_c, orig_c in col_map.items():
        # Claim ID
        if not claim_col and any(k in low_c for k in ["claim", "file #", "file_num", "claim_id", "policy_num", "number"]):
            claim_col = orig_c
            
        # Insured Name
        elif not insured_col and any(k in low_c for k in ["insured", "customer", "policyholder", "client", "name"]):
            insured_col = orig_c
            
        # Street / Address Line 1 (excluding state collisions)
        elif not street_col and any(k in low_c for k in ["street", "address 1", "addr1", "address_line_1", "loss_street", "property_street", "location", "site", "street_address"]):
            if "state" not in low_c and low_c != "st":
                street_col = orig_c

        # Generic 'Address' header fallback if no explicit street match yet
        elif not street_col and not full_addr_col and "address" in low_c and "state" not in low_c:
            street_col = orig_c

        # Town / City
        elif not city_col and any(k in low_c for k in ["town", "city", "municipality", "village"]):
            city_col = orig_c

        # State
        elif not state_col and (low_c in ["state", "st", "province"] or "state" in low_c):
            state_col = orig_c

        # Zip Code
        elif not zip_col and any(k in low_c for k in ["zip", "postal", "zipcode", "zip_code", "postcode"]):
            zip_col = orig_c

    processed_rows = []
    
    for idx, row in df.iterrows():
        claim_num = str(row[claim_col]).strip() if claim_col and pd.notna(row[claim_col]) else f"CLM-{idx + 1001}"
        insured = str(row[insured_col]).strip() if insured_col and pd.notna(row[insured_col]) else f"Policyholder {idx + 1}"
        
        # 1. Full Address Column Priority
        if full_addr_col and pd.notna(row[full_addr_col]) and str(row[full_addr_col]).strip() != "":
            full_address = str(row[full_addr_col]).strip()
            
        # 2. Assemble split address parts: "Street, Town, State Zip"
        else:
            street_val = str(row[street_col]).strip() if street_col and pd.notna(row[street_col]) else ""
            city_val = str(row[city_col]).strip() if city_col and pd.notna(row[city_col]) else ""
            state_val = str(row[state_col]).strip() if state_col and pd.notna(row[state_col]) else ""
            zip_val = str(row[zip_col]).strip() if zip_col and pd.notna(row[zip_col]) else ""

            city_state_zip = " ".join(filter(None, [f"{city_val}, {state_val}".strip(", "), zip_val]))
            
            if street_val:
                full_address = f"{street_val}, {city_state_zip}".strip(", ")
            elif city_state_zip:
                full_address = city_state_zip
            else:
                # Absolute fallback: join all non-empty values in the row if headers were unrecognized
                full_address = ", ".join([str(v).strip() for v in row.values if pd.notna(v) and str(v).strip() != ""])

        # Check for pre-existing coordinates in CSV to bypass geocoding entirely
        if "lat" in df.columns and "lon" in df.columns and pd.notna(row["lat"]) and pd.notna(row["lon"]):
            lat, lon = float(row["lat"]), float(row["lon"])
        else:
            lat, lon = geocode_address(full_address)

        processed_rows.append({
            "claim_id": claim_num,
            "insured_name": insured,
            "display_label": f"{claim_num} - {insured}",
            "full_address": full_address,
            "priority": 3,
            "status": "Unscheduled",
            "start_time": None,
            "end_time": None,
            "scheduled_date": "",
            "inspection_time": "",
            "lat": lat,
            "lon": lon
        })

    return pd.DataFrame(processed_rows)


# --- SLOT GENERATION & CONFLICT CHECKING ---

def generate_available_slots(
    start_date: date,
    end_date: date,
    active_days: List[str],
    inspections_per_day: int,
    start_time_input: Any,
    window_hrs: float
) -> List[Dict[str, Any]]:
    """
    Generates available time slots based on rep schedule preferences.
    """
    day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    slots = []
    
    curr = start_date
    while curr <= end_date:
        if day_map[curr.weekday()] in active_days:
            base_start_dt = datetime.combine(curr, start_time_input)
            
            for i in range(inspections_per_day):
                s_dt = base_start_dt + timedelta(hours=i * window_hrs)
                e_dt = s_dt + timedelta(hours=window_hrs)
                
                date_str = curr.strftime("%Y-%m-%d")
                time_label = f"{s_dt.strftime('%I:%M %p')} - {e_dt.strftime('%I:%M %p')}"
                
                slots.append({
                    "slot_label": f"{date_str} ({day_map[curr.weekday()]}) | {time_label}",
                    "date_str": date_str,
                    "start": s_dt.isoformat(),
                    "end": e_dt.isoformat()
                })
        curr += timedelta(days=1)
        
    return slots


def is_slot_conflicting(slot: Dict[str, Any], claims_df: pd.DataFrame, current_claim_id: str) -> bool:
    """
    Checks whether a slot overlaps with an already scheduled claim.
    """
    if claims_df is None or claims_df.empty:
        return False
        
    scheduled = claims_df[(claims_df["status"] == "Scheduled") & (claims_df["claim_id"] != str(current_claim_id))]
    
    slot_start = datetime.fromisoformat(slot["start"])
    slot_end = datetime.fromisoformat(slot["end"])
    
    for _, row in scheduled.iterrows():
        if pd.notna(row["start_time"]) and pd.notna(row["end_time"]) and str(row["start_time"]) != "":
            c_start = datetime.fromisoformat(str(row["start_time"]))
            c_end = datetime.fromisoformat(str(row["end_time"]))
            
            # Check for time range overlap
            if max(slot_start, c_start) < min(slot_end, c_end):
                return True
                
    return False


# --- RECOMMENDATION ENGINE ---

def get_recommendations_for_day(claims_df: pd.DataFrame, target_date_str: str) -> Optional[pd.DataFrame]:
    """
    Calculates geographic proximity and drive times to recommend unscheduled claims 
    for a targeted target date based on existing scheduled anchors.
    """
    if claims_df is None or claims_df.empty:
        return None

    unscheduled = claims_df[claims_df["status"] == "Unscheduled"].copy()
    if unscheduled.empty:
        return None

    scheduled_day = claims_df[(claims_df["status"] == "Scheduled") & (claims_df["scheduled_date"] == target_date_str)]

    # Determine anchor location (use last scheduled claim on target date if present, otherwise average lat/lon)
    if not scheduled_day.empty:
        anchor_lat = scheduled_day.iloc[-1]["lat"]
        anchor_lon = scheduled_day.iloc[-1]["lon"]
        anchor_type = "anchor_claim"
    else:
        anchor_lat = claims_df["lat"].mean()
        anchor_lon = claims_df["lon"].mean()
        anchor_type = "hotel"

    miles_list = []
    mins_list = []

    for _, row in unscheduled.iterrows():
        miles, mins = get_osrm_route(anchor_lat, anchor_lon, row["lat"], row["lon"])
        miles_list.append(miles)
        mins_list.append(mins)

    unscheduled["drive_miles"] = miles_list
    unscheduled["drive_time_mins"] = mins_list
    unscheduled["anchor_type"] = anchor_type

    # Sort primarily by drive time / proximity, secondary by priority tier
    unscheduled = unscheduled.sort_values(by=["drive_time_mins", "priority"], ascending=[True, True])
    
    return unscheduled


# --- ICS CALENDAR EXPORT ---

def export_claims_to_ics(claims_df: pd.DataFrame) -> str:
    """
    Exports scheduled claims to iCalendar (.ics) format for Outlook/Google Calendar.
    """
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CAT Claims Scheduler//EN",
        "CALSCALE:GREGORIAN"
    ]

    scheduled = claims_df[claims_df["status"] == "Scheduled"]

    for _, row in scheduled.iterrows():
        if pd.notna(row["start_time"]) and pd.notna(row["end_time"]) and str(row["start_time"]) != "":
            try:
                s_dt = datetime.fromisoformat(str(row["start_time"]))
                e_dt = datetime.fromisoformat(str(row["end_time"]))

                ics_lines.extend([
                    "BEGIN:VEVENT",
                    f"SUMMARY:CAT Inspection - {row['claim_id']} ({row['insured_name']})",
                    f"DESCRIPTION:Claim ID: {row['claim_id']}\\nInsured: {row['insured_name']}",
                    f"LOCATION:{row['full_address']}",
                    f"DTSTART:{s_dt.strftime('%Y%m%dT%H%M%SZ')}",
                    f"DTEND:{e_dt.strftime('%Y%m%dT%H%M%SZ')}",
                    f"UID:claim-{row['claim_id']}@catscheduler.local",
                    "END:VEVENT"
                ])
            except Exception:
                continue

    ics_lines.append("END:VCALENDAR")
    return "\n".join(ics_lines)
