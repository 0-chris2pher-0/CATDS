import re
import time
import io
import requests
import pandas as pd
import numpy as np
import streamlit as st
from collections import Counter
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# --- TIME ZONE SUPPORT ---
# All times stored in the app are "wall-clock" times local to the deployment
# (e.g. a 9:00 AM inspection in Houston is stored as 09:00). The deployment's
# time zone is applied only when exporting, so Outlook gets the true moment.

US_TIMEZONES = {
    "Eastern": "America/New_York",
    "Central": "America/Chicago",
    "Mountain": "America/Denver",
    "Arizona (no DST)": "America/Phoenix",
    "Pacific": "America/Los_Angeles",
    "Alaska": "America/Anchorage",
    "Hawaii": "Pacific/Honolulu",
    "Puerto Rico": "America/Puerto_Rico",
}

_ET, _CT, _MT, _PT = "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"

# Primary zone per state. Split states (TX, FL, KS, NE, ND, SD, ID, OR, KY, TN,
# IN, MI) use the zone covering most of the state; override in the sidebar if needed.
STATE_TIMEZONES = {
    "CT": _ET, "DE": _ET, "DC": _ET, "FL": _ET, "GA": _ET, "IN": _ET, "KY": _ET, "ME": _ET,
    "MD": _ET, "MA": _ET, "MI": _ET, "NH": _ET, "NJ": _ET, "NY": _ET, "NC": _ET, "OH": _ET,
    "PA": _ET, "RI": _ET, "SC": _ET, "VT": _ET, "VA": _ET, "WV": _ET,
    "AL": _CT, "AR": _CT, "IL": _CT, "IA": _CT, "KS": _CT, "LA": _CT, "MN": _CT, "MS": _CT,
    "MO": _CT, "NE": _CT, "ND": _CT, "OK": _CT, "SD": _CT, "TN": _CT, "TX": _CT, "WI": _CT,
    "CO": _MT, "ID": _MT, "MT": _MT, "NM": _MT, "UT": _MT, "WY": _MT,
    "AZ": "America/Phoenix",
    "CA": _PT, "NV": _PT, "OR": _PT, "WA": _PT,
    "AK": "America/Anchorage", "HI": "Pacific/Honolulu", "PR": "America/Puerto_Rico",
}

STATE_NAMES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR",
    "PENNSYLVANIA": "PA", "PUERTO RICO": "PR", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}


def get_zone(tz_name: str) -> ZoneInfo:
    """
    Returns a ZoneInfo. On Windows this needs the 'tzdata' package
    (pip install tzdata); raises ZoneInfoNotFoundError if it's missing.
    """
    return ZoneInfo(tz_name)


def state_to_timezone(state: Any) -> Optional[str]:
    if state is None:
        return None
    s = str(state).strip().upper()
    s = STATE_NAMES.get(s, s)
    return STATE_TIMEZONES.get(s)


def _extract_state_from_address(address: Any) -> Optional[str]:
    """Scans an address from the end for a state abbreviation (zip comes after state)."""
    if address is None:
        return None
    tokens = [t for t in re.split(r"[\s,]+", str(address).upper()) if t]
    for tok in reversed(tokens[-4:]):
        if tok in STATE_TIMEZONES:
            return tok
    return None


def detect_deployment_timezone(claims_df: Optional[pd.DataFrame], hotel_address: str = "",
                               default: str = "America/Chicago") -> Tuple[str, str]:
    """
    Picks the most common time zone among the claims' states.
    Returns (tz_name, source) where source is 'claim addresses', 'hotel address' or 'default'.
    """
    zones = []
    if claims_df is not None and not claims_df.empty:
        for _, row in claims_df.iterrows():
            tz = state_to_timezone(row.get("state", "")) or \
                 state_to_timezone(_extract_state_from_address(row.get("full_address", "")))
            if tz:
                zones.append(tz)
    if zones:
        return Counter(zones).most_common(1)[0][0], "claim addresses"

    tz = state_to_timezone(_extract_state_from_address(hotel_address))
    if tz:
        return tz, "hotel address"
    return default, "default"


def parse_wallclock(value: Any) -> Optional[datetime]:
    """
    Parses stored/calendar times ('2026-10-06T09:00:00', '...Z', '...-05:00', '....000Z')
    into a naive wall-clock datetime. Returns None for blanks/NaN.
    The calendar runs in UTC mode, so a trailing Z/offset carries the same wall-clock value.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = pd.Timestamp(s).to_pydatetime()
        except Exception:
            return None
    return dt.replace(tzinfo=None)


def format_slot_time(dt: Optional[datetime]) -> str:
    """e.g. 'Wed 10/07 08:00 AM'"""
    return dt.strftime("%a %m/%d %I:%M %p") if dt else ""


# --- PRIORITY NORMALIZATION ---

def normalize_priority(val: Any) -> Optional[int]:
    """
    Converts any priority value (int, float, '2', '2.0', NaN, None, '') into
    an int rank, or None if the claim is unranked. Used everywhere priority is
    read so imports, saved-state CSVs, and data_editor edits all agree.
    """
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("nan", "none", "<na>"):
        return None
    try:
        return int(float(val_str))
    except (TypeError, ValueError, OverflowError):
        return None


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


@st.cache_data(show_spinner=False)
def _geocode_hotel_cached(address: str) -> Tuple[float, float]:
    """Raises if not found, so failures aren't cached and are retried next run."""
    try:
        resp = requests.get(
            "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
            params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=8
        )
        if resp.status_code == 200:
            matches = resp.json().get("result", {}).get("addressMatches", [])
            if matches:
                c = matches[0]["coordinates"]
                return float(c["y"]), float(c["x"])
    except Exception:
        pass

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": "CATClaimsSchedulerApp/4.0 (contact@example.com)"},
            timeout=6
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass

    raise LookupError(f"Could not geocode hotel address: {address}")


def geocode_hotel_address(address: str) -> Optional[Tuple[float, float]]:
    """
    Geocodes the hotel/base address. Returns None (instead of a random fallback point)
    when it can't be found, so the app can warn the user.
    """
    clean = str(address or "").strip()
    if not clean:
        return None
    try:
        return _geocode_hotel_cached(clean)
    except Exception:
        return None


# Cached so that the extra reruns triggered by editing priorities don't
# re-query OSRM for every unscheduled claim each time.
@st.cache_data(show_spinner=False)
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
    insured names, full addresses, and priority ranks (leaving blank if unspecified).
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

        # Priority parsing: default to None (blank) if not specified or invalid
        prio_val = normalize_priority(row[priority_col]) if priority_col else None

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
        
    scheduled = claims_df[(claims_df["status"] == "Scheduled") & (claims_df["claim_id"].astype(str) != str(current_claim_id))]
    
    slot_start = parse_wallclock(slot["start"])
    slot_end = parse_wallclock(slot["end"])
    
    for _, row in scheduled.iterrows():
        c_start = parse_wallclock(row["start_time"])
        c_end = parse_wallclock(row["end_time"])
        if c_start and c_end and max(slot_start, c_start) < min(slot_end, c_end):
            return True
                
    return False


# --- RECOMMENDATION ENGINE ---

def find_previous_stop(claims_df: pd.DataFrame, slot: Dict[str, Any]) -> Optional[pd.Series]:
    """
    Returns the scheduled claim that ends latest at or before the opening starts,
    on the same day. That's where the rep will be driving from.
    """
    slot_start = parse_wallclock(slot["start"])
    same_day = claims_df[
        (claims_df["status"] == "Scheduled") &
        (claims_df["scheduled_date"].astype(str) == slot["date_str"])
    ]
    best_row, best_end = None, None
    for _, row in same_day.iterrows():
        c_end = parse_wallclock(row["end_time"])
        if c_end and c_end <= slot_start and (best_end is None or c_end > best_end):
            best_row, best_end = row, c_end
    return best_row


def get_recommendations_for_slot(
    claims_df: pd.DataFrame,
    slot: Dict[str, Any],
    hotel_coords: Optional[Tuple[float, float]] = None,
    include_statuses: Tuple[str, ...] = ("Unscheduled",),
    now_local: Optional[datetime] = None
) -> Tuple[Optional[pd.DataFrame], Dict[str, Any]]:
    """
    Recommends claims to fill an opening (slot).

    Candidates:
      - "Unscheduled" claims  -> rec_type "New"
      - "Scheduled" claims    -> rec_type "Reschedule" (moving it into this opening).
        Skips claims whose inspection has already started (before now_local) and
        the previous stop itself.

    Anchor (drive-from point): previous scheduled stop that day, else the hotel,
    else the center of all claims.

    Sorted FIRST by priority rank (1, 2, 3...; unranked last), SECOND by drive time.
    Returns (recs_df or None, anchor_info).
    """
    anchor_info = {"type": "claims_center", "label": "center of claims"}
    if claims_df is None or claims_df.empty:
        return None, anchor_info

    prev_stop = find_previous_stop(claims_df, slot)
    if prev_stop is not None:
        anchor_lat, anchor_lon = float(prev_stop["lat"]), float(prev_stop["lon"])
        prev_end = parse_wallclock(prev_stop["end_time"])
        anchor_info = {
            "type": "previous_stop",
            "claim_id": str(prev_stop["claim_id"]),
            "label": f"previous stop {prev_stop['claim_id']} (ends {prev_end.strftime('%I:%M %p')})"
        }
    elif hotel_coords:
        anchor_lat, anchor_lon = hotel_coords
        anchor_info = {"type": "hotel", "label": "hotel base"}
    else:
        anchor_lat, anchor_lon = float(claims_df["lat"].mean()), float(claims_df["lon"].mean())

    candidates = claims_df[claims_df["status"].isin(include_statuses)].copy()
    if anchor_info["type"] == "previous_stop":
        candidates = candidates[candidates["claim_id"].astype(str) != anchor_info["claim_id"]]

    if "Scheduled" in include_statuses and not candidates.empty:
        starts = candidates["start_time"].apply(parse_wallclock)
        keep = []
        for status, start in zip(candidates["status"], starts):
            if status != "Scheduled":
                keep.append(True)
            elif start is None:
                keep.append(True)
            else:
                keep.append(now_local is None or start > now_local)
        candidates = candidates[keep]

    if candidates.empty:
        return None, anchor_info

    miles_list, mins_list = [], []
    for _, row in candidates.iterrows():
        miles, mins = get_osrm_route(float(anchor_lat), float(anchor_lon), float(row["lat"]), float(row["lon"]))
        miles_list.append(miles)
        mins_list.append(mins)

    candidates["drive_miles"] = miles_list
    candidates["drive_time_mins"] = mins_list
    candidates["anchor_type"] = anchor_info["type"]
    candidates["rec_type"] = ["Reschedule" if s == "Scheduled" else "New" for s in candidates["status"]]
    candidates["current_slot"] = [
        format_slot_time(parse_wallclock(t)) if s == "Scheduled" else ""
        for s, t in zip(candidates["status"], candidates["start_time"])
    ]

    ranks = [normalize_priority(v) for v in candidates["priority"]]
    candidates["priority_rank"] = pd.Series(ranks, index=candidates.index, dtype="object")
    candidates["is_priority"] = [r is not None for r in ranks]

    # Unranked claims get +inf so ranked priorities always sort first;
    # drive time is the tie-breaker within a rank and among unranked claims.
    candidates["prio_sort_key"] = [float(r) if r is not None else float("inf") for r in ranks]
    candidates = candidates.sort_values(
        by=["prio_sort_key", "drive_time_mins"], ascending=[True, True], kind="mergesort"
    ).drop(columns=["prio_sort_key"])

    return candidates, anchor_info


# --- ICS CALENDAR EXPORT ---

def _ics_escape(text: Any) -> str:
    """Escapes text per RFC 5545 (backslash, semicolon, comma, newline)."""
    s = str(text) if text is not None else ""
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r\n", "\\n").replace("\n", "\\n"))


def export_claims_to_ics(claims_df: pd.DataFrame, tz_name: Optional[str]) -> str:
    """
    Exports scheduled inspections. Stored wall-clock times are interpreted in the
    deployment time zone (tz_name) and written as UTC, so Outlook shows the correct
    moment for any viewer. If tz_name is None (zone data unavailable), times are
    written as "floating" local times instead.
    """
    zone = get_zone(tz_name) if tz_name else None
    now_utc = datetime.now(timezone.utc)
    dtstamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    sequence = int(now_utc.timestamp() // 60)  # increases on each export so updates win

    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CAT Claims Scheduler//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]

    def fmt(dt: datetime) -> str:
        if zone is None:
            return dt.strftime("%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=zone).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    scheduled = claims_df[claims_df["status"] == "Scheduled"]

    for _, row in scheduled.iterrows():
        s_dt = parse_wallclock(row["start_time"])
        e_dt = parse_wallclock(row["end_time"])
        if not s_dt or not e_dt:
            continue
        ics_lines.extend([
            "BEGIN:VEVENT",
            f"UID:claim-{_ics_escape(row['claim_id'])}@catscheduler.local",
            f"DTSTAMP:{dtstamp}",
            f"SEQUENCE:{sequence}",
            f"SUMMARY:{_ics_escape('CAT Inspection - ' + str(row['claim_id']) + ' (' + str(row['insured_name']) + ')')}",
            f"DESCRIPTION:{_ics_escape('Claim ID: ' + str(row['claim_id']) + chr(10) + 'Insured: ' + str(row['insured_name']))}",
            f"LOCATION:{_ics_escape(row['full_address'])}",
            f"DTSTART:{fmt(s_dt)}",
            f"DTEND:{fmt(e_dt)}",
            "END:VEVENT"
        ])

    ics_lines.append("END:VCALENDAR")
    return "\r\n".join(ics_lines) + "\r\n"

