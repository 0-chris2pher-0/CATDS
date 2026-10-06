import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

# --- GEOCODING & ROUTING UTILITIES ---

def geocode_address(address: str) -> tuple[float, float]:
    """
    Geocodes an address string using Nominatim (OpenStreetMap) with fallback mock coordinates.
    """
    if not address or pd.isna(address):
        return 29.4241, -98.4936  # Default fallback (San Antonio, TX)

    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address,
            "format": "json",
            "limit": 1
        }
        headers = {
            "User-Agent": "CATClaimsScheduler/1.0"
        }
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass

    # Jittered fallback around San Antonio area for testing
    return 29.4241 + np.random.uniform(-0.1, 0.1), -98.4936 + np.random.uniform(-0.1, 0.1)


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
    minutes = int(round(miles * 2.0))  # rough estimate assuming ~30 mph average
    return miles, minutes


# --- TABLE INGESTION & PARSING ---

def process_imported_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Processes imported CSV/Excel dataframe, detects address and claim fields,
    geocodes claims, and initializes all required state columns.
    """
    # Normalize column names for flexible matching
    col_map = {str(c).strip().lower(): c for c in df.columns}
    
    # Simple heuristic to identify claim numbers and insured names
    claim_col = None
    insured_col = None
    addr_cols = []

    for low_c, orig_c in col_map.items():
        if "claim" in low_c or "number" in low_c or "id" in low_c:
            if not claim_col:
                claim_col = orig_c
        elif "insured" in low_c or "name" in low_c or "customer" in low_c:
            if not insured_col:
                insured_col = orig_c
        elif any(k in low_c for k in ["address", "street", "city", "state", "zip"]):
            addr_cols.append(orig_c)

    processed_rows = []
    
    for idx, row in df.iterrows():
        claim_num = str(row[claim_col]) if claim_col else f"CLM-{idx + 1001}"
        insured = str(row[insured_col]) if insured_col else f"Policyholder {idx + 1}"
        
        if addr_cols:
            full_address = " ".join([str(row[ac]) for ac in addr_cols if pd.notna(row[ac])])
        else:
            # Fallback to combined row string if no specific address column match
            full_address = " ".join([str(v) for v in row.values if pd.notna(v)])

        lat, lon = geocode_address(full_address)

        # Initialize full schema expected by app.py
        claim_record = {
            "claim_id": claim_num,
            "insured_name": insured,
            "display_label": f"{claim_num} - {insured}",
            "full_address": full_address,
            "priority": 3,
            "status": "Unscheduled",
            "start_time": None,
            "end_time": None,
            "scheduled_date": "",        # Ensures column exists on initial load
            "inspection_time": "",       # Ensures column exists on initial load
            "lat": lat,
