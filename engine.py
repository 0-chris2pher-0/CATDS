import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from ics import Calendar, Event
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

HEADER_ALIASES = {
    "claim_num": ["claim claimant", "claim number", "claim #", "claim_id", "claimno", "file #"],
    "insured_name": ["nol insured name", "insured name", "insured", "claimant name", "customer name"],
    "street": ["accident location - street", "street address", "address", "loss address", "street"],
    "city": ["accident location - city", "city", "town"],
    "state": ["acc loc st", "state", "st"],
    "zip": ["accident location postal code", "zip", "zip code", "postal code"],
    "loss_type": ["accident description", "loss type", "cause of loss", "peril"]
}

geolocator = Nominatim(user_agent="cat_claims_scheduler")
geocode_with_delay = RateLimiter(geolocator.geocode, min_delay_seconds=1)

def map_headers(df_columns):
    mapped_keys = {}
    normalized_cols = {str(col).strip().lower(): col for col in df_columns}
    
    for standard_key, aliases in HEADER_ALIASES.items():
        found = False
        for alias in aliases:
            for norm_col, raw_col in normalized_cols.items():
                if alias in norm_col:
                    mapped_keys[standard_key] = raw_col
                    found = True
                    break
            if found:
                break
    return mapped_keys

def geocode_address(full_address):
    """Real address geocoding via Nominatim with fallback to San Antonio center."""
    try:
        location = geocode_with_delay(full_address)
        if location:
            return location.latitude, location.longitude
    except Exception:
        pass
    return 29.4241, -98.4936  # Default fallback coordinates

def process_imported_table(df):
    mapping = map_headers(df.columns)
    
    required = ["claim_num", "street", "city"]
    missing = [req for req in required if req not in mapping]
    if missing:
        raise ValueError(f"Could not automatically detect columns for: {', '.join(missing)}. Please check table headers.")

    processed_claims = []

    for idx, row in df.iterrows():
        full_address = f"{row.get(mapping.get('street', ''), '')}, {row.get(mapping.get('city', ''), '')}, {row.get(mapping.get('state', ''), '')} {row.get(mapping.get('zip', ''), '')}".strip()
        
        claim_num = str(row.get(mapping.get("claim_num"), f"CLM-{idx+1}"))
        insured = str(row.get(mapping.get("insured_name"), "Unknown Insured"))
        
        lat, lon = geocode_address(full_address)

        claim_record = {
            "claim_id": claim_num,
            "insured_name": insured,
            "display_label": f"{claim_num} - {insured}",
            "full_address": full_address,
            "loss_type": str(row.get(mapping.get("loss_type"), "Inspection")),
            "priority": 3,
            "status": "Unscheduled",
            "start_time": None,
            "end_time": None,
            "scheduled_date": None,
            "inspection_time": "",
            "lat": lat,
            "lon": lon
        }
        processed_claims.append(claim_record)
        
    return pd.DataFrame(processed_claims)

def generate_available_slots(start_date, end_date, active_days, inspections_per_day, start_time_obj, window_hrs):
    slots = []
    current_date = start_date
    day_name_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    window_minutes = int(window_hrs * 60)

    while current_date <= end_date:
        if day_name_map[current_date.weekday()] in active_days:
            for i in range(inspections_per_day):
                slot_start = datetime.combine(current_date, start_time_obj) + timedelta(minutes=i * window_minutes)
                slot_end = slot_start + timedelta(minutes=window_minutes)
                slots.append({
                    "slot_label": f"{slot_start.strftime('%a %b %d')}: {slot_start.strftime('%I:%M %p')} - {slot_end.strftime('%I:%M %p')}",
                    "date_str": current_date.strftime("%Y-%m-%d"),
                    "start": slot_start.isoformat(),
                    "end": slot_end.isoformat()
                })
        current_date += timedelta(days=1)
    return slots

def is_slot_conflicting(slot, claims_df, current_claim_id=None):
    if claims_df is None or claims_df.empty:
        return False
        
    scheduled_claims = claims_df[claims_df["status"] == "Scheduled"]
    if current_claim_id:
        scheduled_claims = scheduled_claims[scheduled_claims["claim_id"] != str(current_claim_id)]

    slot_start = datetime.fromisoformat(slot["start"])
    slot_end = datetime.fromisoformat(slot["end"])

    for _, row in scheduled_claims.iterrows():
        if pd.isna(row["start_time"]) or pd.isna(row["end_time"]) or not row["start_time"]:
            continue
        c_start = datetime.fromisoformat(str(row["start_time"]))
        c_end = datetime.fromisoformat(str(row["end_time"]))

        if max(slot_start, c_start) < min(slot_end, c_end):
            return True
    return False

def calculate_distance(lat1, lon1, lat2, lon2):
    return np.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2)

def get_drive_time_and_distance(lat1, lon1, lat2, lon2):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "Ok" and len(data.get("routes", [])) > 0:
                route = data["routes"][0]
                duration_mins = round(route["duration"] / 60.0, 1)
                distance_miles = round(route["distance"] / 1609.34, 1)
                return duration_mins, distance_miles
    except Exception:
        pass
    
    approx_deg = calculate_distance(lat1, lon1, lat2, lon2)
    approx_miles = round(approx_deg * 69.0, 1)
    approx_mins = round(approx_miles * 2.0, 1)
    return approx_mins, approx_miles

def get_recommendations_for_day(claims_df, target_date_str, hotel_coords=(29.4241, -98.4936)):
    if claims_df is None or claims_df.empty:
        return pd.DataFrame()

    unscheduled = claims_df[claims_df["status"] == "Unscheduled"].copy()
    if unscheduled.empty:
        return unscheduled

    day_scheduled = claims_df[
        (claims_df["status"] == "Scheduled") & 
        (claims_df["scheduled_date"] == target_date_str)
    ]

    drive_times = []
    drive_distances = []

    if not day_scheduled.empty:
        anchor = day_scheduled.iloc[-1]
        anchor_lat, anchor_lon = anchor["lat"], anchor["lon"]
        
        for _, r in unscheduled.iterrows():
            mins, miles = get_drive_time_and_distance(anchor_lat, anchor_lon, r["lat"], r["lon"])
            drive_times.append(mins)
            drive_distances.append(miles)
            
        unscheduled["drive_time_mins"] = drive_times
        unscheduled["drive_miles"] = drive_distances
        unscheduled["anchor_type"] = "anchor_claim"
        
        return unscheduled.sort_values(by=["drive_time_mins", "priority"], ascending=[True, True])
    else:
        hotel_lat, hotel_lon = hotel_coords
        
        for _, r in unscheduled.iterrows():
            mins, miles = get_drive_time_and_distance(hotel_lat, hotel_lon, r["lat"], r["lon"])
            drive_times.append(mins)
            drive_distances.append(miles)
            
        unscheduled["drive_time_mins"] = drive_times
        unscheduled["drive_miles"] = drive_distances
        unscheduled["anchor_type"] = "hotel"
        
        return unscheduled.sort_values(by=["priority", "drive_time_mins"], ascending=[True, True])

def export_claims_to_ics(claims_df):
    cal = Calendar()
    scheduled_claims = claims_df[claims_df["status"] == "Scheduled"]
    
    for _, row in scheduled_claims.iterrows():
        event = Event()
        event.name = f"CAT Inspection: [{row['claim_id']}] {row['insured_name']}"
        event.begin = row["start_time"]
        event.end = row["end_time"]
        event.location = row["full_address"]
        event.description = (
            f"Claim ID: {row['claim_id']}\n"
            f"Insured Name: {row['insured_name']}\n"
            f"Loss Description: {row['loss_type']}\n"
            f"Priority Level: {row['priority']}"
        )
        cal.events.add(event)
        
    return str(cal)
