import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

# Simple in-memory geocode cache to avoid re-querying Nominatim on every rerun
GEOCODE_CACHE = {}

def geocode_address(address: str) -> tuple[float, float]:
    """
    Geocodes an address string using Nominatim with caching and error handling.
    """
    clean_addr = str(address).strip()
    if not clean_addr or clean_addr.lower() == "nan":
        return 29.4241, -98.4936

    if clean_addr in GEOCODE_CACHE:
        return GEOCODE_CACHE[clean_addr]

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
                lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
                GEOCODE_CACHE[clean_addr] = (lat, lon)
                return lat, lon
    except Exception:
        pass

    # If geocoding fails, return base location without random jitter so user notices
    return 29.4241, -98.4936


def get_osrm_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> tuple[float, float]:
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}"
        resp = requests.get(url, params={"overview": "false"}, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if "routes" in data and len(data["routes"]) > 0:
                meters = data["routes"][0]["distance"]
                seconds = data["routes"][0]["duration"]
                return round(meters / 1609.34, 1), int(round(seconds / 60.0))
    except Exception:
        pass

    # Haversine fallback
    R = 3958.8
    dlat = np.radians(end_lat - start_lat)
    dlon = np.radians(end_lon - start_lon)
    a = np.sin(dlat / 2)**2 + np.cos(np.radians(start_lat)) * np.cos(np.radians(end_lat)) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    miles = round(R * c, 1)
    return miles, int(round(miles * 2.0))


def process_imported_table(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {str(c).strip().lower(): c for c in df.columns}
    
    claim_col = None
    insured_col = None
    addr_cols = []

    for low_c, orig_c in col_map.items():
        if any(k in low_c for k in ["claim", "number", "id"]):
            if not claim_col: claim_col = orig_c
        elif any(k in low_c for k in ["insured", "name", "customer"]):
            if not insured_col: insured_col = orig_c
        elif any(k in low_c for k in ["address", "street", "city", "state", "zip", "loc"]):
            addr_cols.append(orig_c)

    processed_rows = []
    
    for idx, row in df.iterrows():
        claim_num = str(row[claim_col]) if claim_col else f"CLM-{idx + 1001}"
        insured = str(row[insured_col]) if insured_col else f"Policyholder {idx + 1}"
        
        if addr_cols:
            full_address = ", ".join([str(row[ac]).strip() for ac in addr_cols if pd.notna(row[ac]) and str(row[ac]).strip() != ""])
        else:
            full_address = ", ".join([str(v).strip() for v in row.values if pd.notna(v)])

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


def generate_available_slots(start_date: date, end_date: date, active_days: List[str], inspections_per_day: int, start_time_input: Any, window_hrs: float) -> List[Dict[str, Any]]:
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
    if claims_df is None or claims_df.empty:
        return False
    scheduled = claims_df[(claims_df["status"] == "Scheduled") & (claims_df["claim_id"] != str(current_claim_id))]
    slot_start = datetime.fromisoformat(slot["start"])
    slot_end = datetime.fromisoformat(slot["end"])
    
    for _, row in scheduled.iterrows():
        if pd.notna(row["start_time"]) and pd.notna(row["end_time"]) and str(row["start_time"]) != "":
            c_start = datetime.fromisoformat(str(row["start_time"]))
            c_end = datetime.fromisoformat(str(row["end_time"]))
            if max(slot_start, c_start) < min(slot_end, c_end):
                return True
    return False


def get_recommendations_for_day(claims_df: pd.DataFrame, target_date_str: str) -> Optional[pd.DataFrame]:
    if claims_df is None or claims_df.empty:
        return None

    unscheduled = claims_df[claims_df["status"] == "Unscheduled"].copy()
    if unscheduled.empty:
        return None

    scheduled_day = claims_df[(claims_df["status"] == "Scheduled") & (claims_df["scheduled_date"] == target_date_str)]

    if not scheduled_day.empty:
        anchor_lat = scheduled_day.iloc[-1]["lat"]
        anchor_lon = scheduled_day.iloc[-1]["lon"]
        anchor_type = "anchor_claim"
    else:
        anchor_lat = claims_df["lat"].mean()
        anchor_lon = claims_df["lon"].mean()
        anchor_type = "hotel"

    miles_list, mins_list = [], []
    for _, row in unscheduled.iterrows():
        miles, mins = get_osrm_route(anchor_lat, anchor_lon, row["lat"], row["lon"])
        miles_list.append(miles)
        mins_list.append(mins)

    unscheduled["drive_miles"] = miles_list
    unscheduled["drive_time_mins"] = mins_list
    unscheduled["anchor_type"] = anchor_type

    return unscheduled.sort_values(by=["drive_time_mins", "priority"], ascending=[True, True])


def export_claims_to_ics(claims_df: pd.DataFrame) -> str:
    ics_lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CAT Claims Scheduler//EN", "CALSCALE:GREGORIAN"]
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
