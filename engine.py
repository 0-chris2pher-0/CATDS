import re
import time
import io
import requests
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple

# --- OPTION 4: US CENSUS BATCH & STRUCTURED GEOCODING UTILITIES ---

def parse_us_address(address_str: str, fallback_state: str = "") -> Tuple[str, str, str, str]:
    """
    Parses a raw address string into (Street, City, State, Zip) components.
    """
    clean_addr = str(address_str).strip()
    if not clean_addr or clean_addr.lower() == "nan":
        return "", "", fallback_state, ""

    parts = [p.strip() for p in clean_addr.split(",") if p.strip()]
    street, city, state, zip_code = "", "", fallback_state, ""

    if len(parts) >= 3:
        street = parts[0]
        city = parts[1]
        state_zip_part = parts[2].split()
        if len(state_zip_part) >= 1:
            state = state_zip_part[0]
        if len(state_zip_part) >= 2:
            zip_code = state_zip_part[1]
    elif len(parts) == 2:
        street = parts[0]
        city_st = parts[1].split()
        if len(city_st) >= 1:
            city = city_st[0]
        if len(city_st) >= 2:
            state = city_st[1]
    else:
        street = clean_addr

    return street, city, state, zip_code


def census_batch_geocode(parsed_addresses: List[Tuple[int, str, str, str, str]]) -> Dict[int, Tuple[float, float]]:
    """
    Sends structured addresses to the US Census Bureau Batch Geocoder in a single request.
    Returns a mapping of row_index -> (lat, lon).
    """
    if not parsed_addresses:
        return {}

    csv_buffer = io.StringIO()
    for row_id, street, city, state, zip_code in parsed_addresses:
        s_clean = street.replace('"', '')
        c_clean = city.replace('"', '')
        st_clean = state.replace('"', '')
        z_clean = zip_code.replace('"', '')
        csv_buffer.write(f'"{row_id}","{s_clean}","{c_clean}","{st_clean}","{z_clean}"\n')

    csv_buffer.seek(0)

    results = {}
    try:
        url = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
        files = {
            'addressFile': ('addresses.csv', csv_buffer.getvalue(), 'text/csv')
        }
        data = {
            'benchmark': 'Public_AR_Current',
            'vintage': 'Current_Current'
        }
        
        response = requests.post(url, files=files, data=data, timeout=30)
        
        if response.status_code == 200:
            lines = response.text.strip().split("\n")
            for line in lines:
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 6:
                    row_id_str = parts[0].strip('"')
                    match_status = parts[2].strip('"')
                    
                    if match_status == "Match" and len(parts) >= 6:
                        coords_str = parts[5].strip('"')
                        if "," in coords_str:
                            lon_str, lat_str = coords_str.split(",")
                            try:
                                row_id = int(row_id_str)
                                results[row_id] = (float(lat_str), float(lon_str))
                            except ValueError:
                                pass
    except Exception as e:
        st.warning(f"US Census Batch API request failed: {e}")

    return results


@st.cache_data(show_spinner=False)
def geocode_single_address_fallback(address: str, state: str = None) -> Tuple[float, float]:
    """
    Fallback single-address lookup using Nominatim for rows missed by Census batch.
    """
    clean_addr = str(address).strip()
    if not clean_addr or clean_addr.lower() == "nan":
        return 29.4241 + np.random.uniform(-0.02, 0.02), -98.4936 + np.random.uniform(-0.02, 0.02)

    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": clean_addr,
            "format": "json",
            "limit": 1,
            "countrycodes": "us"
        }
        if state and str(state).strip() and str(state).lower() != "nan":
            params["state"] = str(state).strip()

        headers = {"User-Agent": "CATClaimsSchedulerApp/4.0 (contact@example.com)"}
        resp = requests.get(url, params=params, headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass

    return 29.4241 + np.random.uniform(-0.02, 0.02), -98.4936 + np.random.uniform(-0.02, 0.02)


def batch_geocode_addresses(address_state_list: List[Tuple[str, Optional[str]]]) -> List[Tuple[float, float]]:
    """
    Fast, hybrid geocoding: US Census Batch API (instant) with single-address fallbacks.
    """
    total = len(address_state_list)
    if total == 0:
        return []

    progress_bar = st.progress(0, text="Standardizing & geocoding addresses via US Census API...")

    parsed_items = []
    for idx, item in enumerate(address_state_list):
        if isinstance(item, tuple):
            addr, st_val = item
        else:
            addr, st_val = item, ""
        
        street, city, state, zip_code = parse_us_address(addr, fallback_state=st_val or "")
        parsed_items.append((idx, street, city, state, zip_code))

    census_results = census_batch_geocode(parsed_items)
    progress_bar.progress(0.7, text="Processing Census matches & executing fallbacks...")

    final_coords = []
    for idx, item in enumerate(address_state_list):
        if idx in census_results:
            final_coords.append(census_results[idx])
        else:
            addr = item[0] if isinstance(item, tuple) else item
            st_val = item[1] if isinstance(item, tuple) else None
            coords = geocode_single_address_fallback(addr, state=st_val)
            final_coords.append(coords)
            time.sleep(1.0)

    progress_bar.empty()
    return final_coords


def get_osrm_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> Tuple[float, float]:
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

    R = 3958.8
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
    Processes imported CSV/Excel dataframe by detecting formatted claim IDs,
    insured names, and full addresses.
    """
    col_map = {str(c).strip().lower(): c for c in df.columns}
    
    claim_col = None
    insured_col = None
    street_col = None
    city_col = None
    state_col = None
    zip_col = None
    full_addr_col = None
    priority_col = None

    claim_pattern = re.compile(r'^[A-Za-z]{2,5}\d+[\-\_]?\d*$', re.IGNORECASE)
    
    for c in df.columns:
        sample_vals = df[c].dropna().astype(str).str.strip().tolist()[:10]
        if any(claim_pattern.match(val) for val in sample_vals):
            claim_col = c
            break

    if not claim_col:
        for low_c, orig_c in col_map.items():
            if any(k in low_c for k in ["claim", "file", "policy"]):
                claim_col = orig_c
                break

    for low_c, orig_c in col_map.items():
        if any(k == low_c for k in ["full address", "full_address", "loss address", "property address", "location address", "site address", "address"]):
            full_addr_col = orig_c
            break

    for low_c, orig_c in col_map.items():
        if not insured_col and any(k in low_c for k in ["insured", "customer", "policyholder", "client", "name"]):
            insured_col = orig_c
        elif not street_col and any(k in low_c for k in ["street", "address 1", "addr1", "address_line_1", "loss_street", "property_street", "location", "site"]):
            if "state" not in low_c and low_c != "st":
                street_col = orig_c
        elif not city_col and any(k in low_c for k in ["town", "city", "municipality", "village"]):
            city_col = orig_c
        elif not state_col and (low_c in ["state", "st", "province"] or "state" in low_c):
            state_col = orig_c
        elif not zip_col and any(k in low_c for k in ["zip", "postal", "zipcode", "zip_code"]):
            zip_col = orig_c
        elif not priority_col and any(k in low_c for k in ["priority", "rank", "prio"]):
            priority_col = orig_c

    address_list = []
    metadata = []

    for idx, row in df.iterrows():
        if claim_col and pd.notna(row[claim_col]) and str(row[claim_col]).strip() != "":
            raw_claim = str(row[claim_col]).strip()
            claim_num = raw_claim[:-2] if raw_claim.endswith(".0") else raw_claim
        else:
            claim_num = f"CLM-{idx + 1001}"

        insured = str(row[insured_col]).strip() if insured_col and pd.notna(row[insured_col]) else f"Policyholder {idx + 1}"
        state_val = str(row[state_col]).strip() if state_col and pd.notna(row[state_col]) else ""

        # Priority parsing (default to 3 if missing or invalid)
        prio_val = 3
        if priority_col and pd.notna(row[priority_col]):
            try:
                prio_val = int(float(row[priority_col]))
            except ValueError:
                prio_val = 3

        if full_addr_col and pd.notna(row[full_addr_col]) and str(row[full_addr_col]).strip() != "":
            full_address = str(row[full_addr_col]).strip()
        else:
            street_val = str(row[street_col]).strip() if street_col and pd.notna(row[street_col]) else ""
            city_val = str(row[city_col]).strip() if city_col and pd.notna(row[city_col]) else ""
            zip_val = str(row[zip_col]).strip() if zip_col and pd.notna(row[zip_col]) else ""

            city_state_zip = " ".join(filter(None, [f"{city_val}, {state_val}".strip(", "), zip_val]))
            if street_val:
                full_address = f"{street_val}, {city_state_zip}".strip(", ")
            elif city_state_zip:
                full_address = city_state_zip
            else:
                full_address = ", ".join([str(v).strip() for v in row.values if pd.notna(v) and str(v).strip() != ""])

        has_coords = "lat" in df.columns and "lon" in df.columns and pd.notna(row["lat"]) and pd.notna(row["lon"])
        pre_lat = float(row["lat"]) if has_coords else None
        pre_lon = float(row["lon"]) if has_coords else None

        address_list.append(full_address)
        metadata.append({
            "claim_id": claim_num,
            "insured_name": insured,
            "display_label": f"{claim_num} - {insured}",
            "full_address": full_address,
            "state": state_val,
            "priority": prio_val,
            "status": "Unscheduled",
            "start_time": None,
            "end_time": None,
            "scheduled_date": "",
            "inspection_time": "",
            "pre_lat": pre_lat,
            "pre_lon": pre_lon
        })

    addrs_to_geocode = [
        (m["full_address"], m["state"]) for m in metadata if m["pre_lat"] is None
    ]
    geocoded_coords = batch_geocode_addresses(addrs_to_geocode) if addrs_to_geocode else []

    geo_idx = 0
    processed_rows = []
    for m in metadata:
        if m["pre_lat"] is not None:
            lat, lon = m["pre_lat"], m["pre_lon"]
        else:
            lat, lon = geocoded_coords[geo_idx]
            geo_idx += 1

        row_dict = dict(m)
        del row_dict["pre_lat"]
        del row_dict["pre_lon"]
        row_dict["lat"] = lat
        row_dict["lon"] = lon
        processed_rows.append(row_dict)

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


# --- RECOMMENDATION ENGINE ---

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

    miles_list = []
    mins_list = []

    for _, row in unscheduled.iterrows():
        miles, mins = get_osrm_route(anchor_lat, anchor_lon, row["lat"], row["lon"])
        miles_list.append(miles)
        mins_list.append(mins)

    unscheduled["drive_miles"] = miles_list
    unscheduled["drive_time_mins"] = mins_list
    unscheduled["anchor_type"] = anchor_type

    # Ensure priority is numeric (defaulting to 3 if invalid)
    unscheduled["priority"] = pd.to_numeric(unscheduled["priority"], errors="coerce").fillna(3)

    # Sort FIRST by Priority (1 is highest), SECOND by Drive Time (shortest first)
    unscheduled = unscheduled.sort_values(by=["priority", "drive_time_mins"], ascending=[True, True])
    return unscheduled


# --- ICS CALENDAR EXPORT ---

def export_claims_to_ics(claims_df: pd.DataFrame) -> str:
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
