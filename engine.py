import re
import time
import io
import requests
import pandas as pd
import numpy as np
import streamlit as st
import math
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote
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


# --- NAVIGATION LINKS ---

def build_navigation_links(address: Any, lat: Any = None, lon: Any = None, prefer_coords: bool = False) -> Dict[str, str]:
    """
    Returns turn-by-turn directions links for Google Maps and Apple Maps.
    Uses the street ADDRESS when available so Google/Apple apply their own
    rooftop-accurate geocoding (more reliable than our free geocoded pin).
    Falls back to lat/lon if there's no address.
    On phones these open the Google Maps / Apple Maps apps when installed.
    """
    addr = str(address).strip() if address is not None else ""
    has_coords = False
    try:
        has_coords = lat is not None and lon is not None and pd.notna(lat) and pd.notna(lon)
    except (TypeError, ValueError):
        pass
    if prefer_coords and has_coords:
        # The rep placed this pin by hand, so it beats the street address.
        dest = f"{float(lat)},{float(lon)}"
    elif addr and addr.lower() != "nan":
        dest = addr
    else:
        try:
            if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
                return {}
        except (TypeError, ValueError):
            return {}
        dest = f"{float(lat)},{float(lon)}"

    q = quote(dest)
    return {
        "google": f"https://www.google.com/maps/dir/?api=1&destination={q}",
        "apple": f"https://maps.apple.com/?daddr={q}",
    }


# --- CONTACT, ACTIVITY & EXPORT FIELDS ---

ACTIVITY_ONSITE = "Scheduled On-Site Inspection"
ACTIVITY_VIDEO = "Scheduled Live Video Inspection"
ACTIVITY_OPTIONS = [ACTIVITY_ONSITE, ACTIVITY_VIDEO]
VIDEO_DEFAULT_HRS = 1.0
NOTE_MAX_CHARS = 500

# Exact column headers for the claim platform export, in order
EXPORT_HEADERS = [
    "Claim Number", "Insured Name", "Phone Number", "Email", "Type of Contact",
    "Date Contact Completed", "Time Contact Completed", "Contact AM or PM",
    "Type of Activity", "Date Activity Completed", "Time Activity Completed", "Activity AM or PM",
    "Initial Contact Note",
]


def is_video(activity: Any) -> bool:
    return str(activity or "").strip() == ACTIVITY_VIDEO


def _blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() in ("", "nan", "None", "NaT")


def clean_text(value: Any) -> str:
    return "" if _blank(value) else str(value).strip()


def normalize_phone(value: Any) -> str:
    """Formats 10-digit US numbers as (210) 555-0142; leaves anything else as typed."""
    raw = clean_text(value)
    if raw.endswith(".0"):
        raw = raw[:-2]
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def split_12h(dt: Optional[datetime]) -> Tuple[str, str, str]:
    """datetime -> ('10/07/2026', '2:15', 'PM'); blanks if None."""
    if not dt:
        return "", "", ""
    return dt.strftime("%m/%d/%Y"), dt.strftime("%I:%M").lstrip("0"), dt.strftime("%p")


def parse_date_time_12h(date_str: Any, time_str: Any, ampm: Any) -> Tuple[Optional[datetime], Optional[str]]:
    """
    ('10/07/2026', '2:15', 'PM') -> datetime. Returns (None, None) when all are blank,
    or (None, error message) when something can't be read.
    """
    d, t, ap = clean_text(date_str), clean_text(time_str), clean_text(ampm).upper()
    if not d and not t and not ap:
        return None, None
    try:
        day = datetime.strptime(d, "%m/%d/%Y").date()
    except ValueError:
        return None, f"'{d}' isn't a date like 10/07/2026"
    if not t:
        return datetime.combine(day, datetime.min.time()), None
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", t.upper())
    if not m:
        return None, f"'{t}' isn't a time like 2:15"
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    ap = m.group(3) or ap
    if ap not in ("AM", "PM") or not (1 <= hour <= 12) or minute > 59:
        return None, "Use a time like 2:15 with AM or PM"
    hour = hour % 12 + (12 if ap == "PM" else 0)
    return datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute), None


def build_export_table(claims_df: pd.DataFrame, claim_ids: Optional[List[str]] = None) -> pd.DataFrame:
    """Rows for the claim platform, with the exact EXPORT_HEADERS columns."""
    df = claims_df
    if claim_ids is not None:
        wanted = {str(c) for c in claim_ids}
        df = df[df["claim_id"].astype(str).isin(wanted)]
    rows = []
    for _, r in df.iterrows():
        contact_dt = parse_wallclock(r.get("first_booked_at"))
        activity_dt = parse_wallclock(r.get("start_time")) if r.get("status") == "Scheduled" else None
        c_date, c_time, c_ap = split_12h(contact_dt)
        a_date, a_time, a_ap = split_12h(activity_dt)
        rows.append({
            "Claim Number": str(r["claim_id"]),
            "Insured Name": clean_text(r.get("insured_name")),
            "Phone Number": normalize_phone(r.get("phone")),
            "Email": clean_text(r.get("email")),
            "Type of Contact": "Initial contact" if contact_dt else "",
            "Date Contact Completed": c_date, "Time Contact Completed": c_time, "Contact AM or PM": c_ap,
            "Type of Activity": clean_text(r.get("activity_type")) if activity_dt or clean_text(r.get("activity_type")) else "",
            "Date Activity Completed": a_date, "Time Activity Completed": a_time, "Activity AM or PM": a_ap,
            "Initial Contact Note": clean_text(r.get("contact_note"))[:NOTE_MAX_CHARS],
        })
    return pd.DataFrame(rows, columns=EXPORT_HEADERS)


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


# --- GEOCODING (free sources only) ---
# Lookup chain per address, most to least precise:
#   1. US Census batch (all addresses in one request)
#   2. US Census single-line lookup (does its own address parsing)
#   3. OpenStreetMap / Nominatim structured lookup, then free-text lookup
#   4. ZIP code area, then city area (approximate, flagged for review)
#   5. Not found (no pin; flagged so the rep can place it manually)
# Every claim gets a geo_quality label so the map can show how each pin was placed.

GEO_EXACT = "Exact address"
GEO_CENSUS_APPROX = "Close address match"
GEO_OSM = "OpenStreetMap match"
GEO_ZIP = "ZIP area (approx.)"
GEO_CITY = "City area (approx.)"
GEO_NOT_FOUND = "Not found"
GEO_MANUAL = "Set by rep"
GEO_CONFIRMED = "Confirmed by rep"
GEO_IMPORTED = "From import file"
GEO_UNKNOWN = "Unknown"

# Pins a rep should double-check or place by hand
GEO_NEEDS_REVIEW = {GEO_ZIP, GEO_CITY, GEO_NOT_FOUND}

# Pins a rep has checked: never flagged, never overwritten by a re-check,
# and used for directions instead of the street address.
GEO_REP_VERIFIED = {GEO_MANUAL, GEO_CONFIRMED}

# Nominatim's usage policy asks for a real contact. Set NOMINATIM_CONTACT in
# Streamlit secrets (Manage app > Settings > Secrets), or edit the fallback below.
_NOMINATIM_CONTACT_FALLBACK = "replace-with-your-email@example.com"


def _nominatim_headers() -> Dict[str, str]:
    try:
        contact = st.secrets.get("NOMINATIM_CONTACT", _NOMINATIM_CONTACT_FALLBACK)
    except Exception:
        contact = _NOMINATIM_CONTACT_FALLBACK
    return {"User-Agent": f"CATClaimsSchedulerApp/5.0 ({contact})"}


_last_nominatim_call = [0.0]


def _nominatim_throttle():
    """Nominatim allows at most 1 request per second."""
    wait = 1.05 - (time.time() - _last_nominatim_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_nominatim_call[0] = time.time()


def clean_address_for_geocoding(address: Any) -> str:
    """
    Strips things geocoders choke on: unit numbers (Apt 4, Unit B, #12, Lot 7),
    parenthetical notes ("(rear house)"), and messy spacing/commas.
    The original address is kept for display and directions.
    """
    if address is None:
        return ""
    s = str(address).strip()
    if not s or s.lower() == "nan":
        return ""
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(
        r"\b(?:apt|apartment|unit|suite|bldg|building|trlr|trailer|spc|space|lot|rm|room)\b\.?\s*#?\s*[\w\-]+",
        " ", s, flags=re.IGNORECASE
    )
    s = re.sub(r"#\s*[\w\-]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"(?:,\s*){2,}", ", ", s)
    return s.strip(" ,")


def _normalize_state(value: Any) -> str:
    s = str(value or "").strip().upper()
    if s == "NAN":
        return ""
    return STATE_NAMES.get(s, s)


def parse_us_address(address_str: str, fallback_state: str = "") -> Tuple[str, str, str, str]:
    """
    Parses a raw address into (street, city, state, zip), reading from the END
    of the address, where ZIP and state reliably sit. Handles:
      "123 Oak St, San Antonio, TX 78201"
      "123 Oak St, San Antonio TX 78201"
      "123 Oak St, New Braunfels, Texas"
    """
    clean = clean_address_for_geocoding(address_str)
    fallback_state = _normalize_state(fallback_state)
    if not clean:
        return "", "", fallback_state, ""

    parts = [p.strip() for p in clean.split(",") if p.strip()]
    zip_code, state = "", ""

    # Peel ZIP, then state, off the end (they may be in their own comma parts)
    for _ in range(2):
        if not parts:
            break
        tokens = parts[-1].split()
        if not zip_code and tokens and re.fullmatch(r"\d{5}(?:-\d{4})?", tokens[-1]):
            zip_code = tokens.pop()[:5]
        if not state and tokens:
            two = " ".join(tokens[-2:]).upper() if len(tokens) >= 2 else ""
            if two in STATE_NAMES:
                state = STATE_NAMES[two]
                tokens = tokens[:-2]
            elif tokens[-1].upper() in STATE_TIMEZONES:
                state = tokens.pop().upper()
            elif tokens[-1].upper() in STATE_NAMES:
                state = STATE_NAMES[tokens.pop().upper()]
        if tokens:
            parts[-1] = " ".join(tokens)
        else:
            parts.pop()
        if zip_code and state:
            break

    street = parts[0] if parts else ""
    city = parts[-1] if len(parts) >= 2 else ""
    return street, city, state or fallback_state, zip_code


def census_batch_geocode(parsed_addresses: List[Tuple[int, str, str, str, str]]) -> Dict[int, Tuple[float, float, str]]:
    """
    Sends structured addresses to the US Census Bureau Batch Geocoder in one request.
    Returns row_index -> (lat, lon, quality).
    """
    if not parsed_addresses:
        return {}

    import csv
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer, quoting=csv.QUOTE_ALL)
    for row_id, street, city, state, zip_code in parsed_addresses:
        writer.writerow([row_id, street, city, state, zip_code])

    results = {}
    try:
        response = requests.post(
            "https://geocoding.geo.census.gov/geocoder/locations/addressbatch",
            files={"addressFile": ("addresses.csv", csv_buffer.getvalue(), "text/csv")},
            data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
            timeout=120
        )
        if response.status_code == 200:
            # Columns: id, input address, match status, match type, matched address, "lon,lat", ...
            for fields in csv.reader(io.StringIO(response.text)):
                if len(fields) >= 6 and fields[2] == "Match" and "," in fields[5]:
                    try:
                        lon_str, lat_str = fields[5].split(",")
                        quality = GEO_EXACT if fields[3] == "Exact" else GEO_CENSUS_APPROX
                        results[int(fields[0])] = (float(lat_str), float(lon_str), quality)
                    except ValueError:
                        pass
    except Exception as e:
        st.warning(f"The US Census batch lookup didn't respond ({e}). Trying addresses one at a time.")

    return results


# --- Free Census reference files: ZIP and city center points ---
# Downloaded once per app start from the Census "Gazetteer" files (about 1 MB each)
# and kept in memory, so ZIP/city fallbacks are instant instead of online lookups.

_GAZETTEER_YEARS = [2025, 2024, 2023, 2022, 2021, 2020]


def _normalize_place_name(name: Any) -> str:
    s = str(name or "").lower()
    s = re.sub(r"[.\'’]", "", s)
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bfort\b", "ft", s)
    s = re.sub(r"\bmount\b", "mt", s)
    return re.sub(r"\s+", " ", s).strip()


_PLACE_SUFFIX = re.compile(
    r"\s+(?:city and borough|consolidated government.*|metropolitan government.*|unified government.*|"
    r"urban county|city|town|village|cdp|borough|municipality|comunidad|zona urbana)(?:\s*\(balance\))?$",
    re.IGNORECASE
)


@st.cache_resource(show_spinner=False)
def _load_gazetteer(kind: str) -> Dict[Any, Tuple[float, float]]:
    """kind = 'zcta' (ZIP codes) or 'place' (cities/towns). Raises if unavailable (not cached)."""
    import zipfile
    for year in _GAZETTEER_YEARS:
        url = (f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
               f"{year}_Gazetteer/{year}_Gaz_{kind}_national.zip")
        try:
            resp = requests.get(url, timeout=45)
            if resp.status_code != 200:
                continue
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                txt_name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
                with zf.open(txt_name) as fh:
                    gdf = pd.read_csv(fh, sep="\t", dtype=str, encoding="latin-1")
            gdf.columns = [c.strip() for c in gdf.columns]
            out = {}
            for _, r in gdf.iterrows():
                try:
                    lat, lon = float(r["INTPTLAT"]), float(str(r["INTPTLONG"]).strip())
                except (ValueError, KeyError):
                    continue
                if kind == "zcta":
                    out[str(r["GEOID"]).strip().zfill(5)] = (lat, lon)
                else:
                    key = (str(r["USPS"]).strip().upper(),
                           _normalize_place_name(_PLACE_SUFFIX.sub("", str(r["NAME"]).strip())))
                    out.setdefault(key, (lat, lon))
            if out:
                return out
        except Exception:
            continue
    raise LookupError(f"Census {kind} reference file unavailable")


def _gazetteer(kind: str) -> Dict[Any, Tuple[float, float]]:
    try:
        return _load_gazetteer(kind)
    except Exception:
        return {}


# --- Census single-address lookups (safe to run in parallel) ---

_ONELINE_CACHE: Dict[str, Optional[Tuple[float, float, str]]] = {}

# Rural road names the Census often stores spelled out
_ROAD_EXPANSIONS = [
    (r"\bFM\b", "Farm to Market Road"),
    (r"\bRM\b", "Ranch to Market Road"),
    (r"\bRR\b", "Ranch Road"),
    (r"\bCR\b", "County Road"),
    (r"\bSH\b", "State Highway"),
    (r"\bHWY\b", "Highway"),
]


def _street_variants(street: str) -> List[str]:
    variants = [street]
    expanded = street
    for pattern, replacement in _ROAD_EXPANSIONS:
        expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
    if expanded != street:
        variants.append(expanded)
    return variants


def _census_oneline_raw(address: str) -> Optional[Tuple[float, float, str]]:
    """No Streamlit calls in here, so it can run in worker threads."""
    if address in _ONELINE_CACHE:
        return _ONELINE_CACHE[address]
    resp = requests.get(
        "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
        params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
        timeout=12
    )
    resp.raise_for_status()
    matches = resp.json().get("result", {}).get("addressMatches", [])
    result = None
    if matches:
        c = matches[0]["coordinates"]
        result = (float(c["y"]), float(c["x"]), GEO_CENSUS_APPROX if len(matches) > 1 else GEO_EXACT)
    _ONELINE_CACHE[address] = result
    return result


def _census_retry(address: str, state: str) -> Optional[Tuple[float, float, str]]:
    """Census single-line lookup, also trying spelled-out rural road names."""
    street, city, st_abbr, zip_code = parse_us_address(address, fallback_state=state)
    if not street:
        return None
    tail = ", ".join(p for p in [city, f"{st_abbr} {zip_code}".strip()] if p)
    for variant in _street_variants(street):
        query = f"{variant}, {tail}" if tail else variant
        try:
            hit = _census_oneline_raw(query)
        except Exception:
            hit = None
        if hit:
            return hit
    return None


def _centroid_fallback(address: str, state: str) -> Tuple[Optional[float], Optional[float], str]:
    """Instant ZIP-area, then city-area location from the Census reference files."""
    _, city, st_abbr, zip_code = parse_us_address(address, fallback_state=state)
    if zip_code:
        hit = _gazetteer("zcta").get(zip_code)
        if hit:
            return hit[0], hit[1], GEO_ZIP
    if city and st_abbr:
        hit = _gazetteer("place").get((st_abbr, _normalize_place_name(city)))
        if hit:
            return hit[0], hit[1], GEO_CITY
    return None, None, GEO_NOT_FOUND


def batch_geocode_addresses(address_state_list: List[Tuple[str, Optional[str]]]) -> List[Tuple[Optional[float], Optional[float], str]]:
    """
    Fast geocoding for imports:
      1. Census batch (one request for everything)
      2. Census single-line retries for misses, run in parallel (incl. rural road spellings)
      3. Instant ZIP-area / city-area location from Census reference files (flagged for review)
    Returns (lat, lon, quality) per item; lat/lon are None when nothing was found.
    """
    from concurrent.futures import ThreadPoolExecutor

    total = len(address_state_list)
    if total == 0:
        return []

    progress_bar = st.progress(0.05, text="Looking up addresses with the US Census...")

    items = []
    for item in address_state_list:
        addr, st_val = item if isinstance(item, tuple) else (item, "")
        items.append((str(addr) if addr is not None else "", st_val or ""))

    parsed = [(idx, *parse_us_address(addr, fallback_state=st_val)) for idx, (addr, st_val) in enumerate(items)]
    results: Dict[int, Tuple[Optional[float], Optional[float], str]] = dict(census_batch_geocode(parsed))

    misses = [i for i in range(total) if i not in results]
    if misses:
        progress_bar.progress(0.55, text=f"Retrying {len(misses)} addresses the Census batch couldn't match...")
        with ThreadPoolExecutor(max_workers=6) as pool:
            retry_hits = list(pool.map(lambda i: _census_retry(*items[i]), misses))
        for i, hit in zip(misses, retry_hits):
            if hit:
                results[i] = hit

    still_missing = [i for i in range(total) if i not in results]
    if still_missing:
        progress_bar.progress(0.85, text=f"Placing {len(still_missing)} addresses by ZIP code or city...")
        for i in still_missing:
            results[i] = _centroid_fallback(*items[i])

    progress_bar.empty()
    return [results[i] for i in range(total)]


def parse_coordinates(text: Any) -> Optional[Tuple[float, float]]:
    """
    Pulls a lat/lon pair out of pasted text: "29.4241, -98.4936",
    or a Google Maps link containing "@29.4241,-98.4936" or "q=29.4241,-98.4936".
    """
    if not text:
        return None
    m = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", str(text))
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


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

def parse_claims_table(df: pd.DataFrame) -> List[Dict[str, Any]]:
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
    phone_col = None
    email_col = None

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
        if not email_col and ("email" in low_c or "e-mail" in low_c):
            email_col = orig_c
        elif not phone_col and any(k in low_c for k in ["phone", "mobile", "cell", "telephone", "contact number"]):
            phone_col = orig_c

    for low_c, orig_c in col_map.items():
        if orig_c in (phone_col, email_col):
            continue
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
            "phone": normalize_phone(row[phone_col]) if phone_col else "",
            "email": clean_text(row[email_col]) if email_col else "",
            "activity_type": "",
            "contact_note": "",
            "first_booked_at": "",
            "last_exported": "",
            "pre_lat": pre_lat,
            "pre_lon": pre_lon
        })

    return metadata


def geocode_claim_rows(metadata: List[Dict[str, Any]]) -> pd.DataFrame:
    """Looks up locations for parsed claim rows (skipping rows with imported lat/lon)."""
    addrs_to_geocode = [
        (m["full_address"], m["state"]) for m in metadata if m["pre_lat"] is None
    ]
    geocoded_coords = batch_geocode_addresses(addrs_to_geocode) if addrs_to_geocode else []

    geo_idx = 0
    processed_rows = []
    for m in metadata:
        if m["pre_lat"] is not None:
            lat, lon, quality = m["pre_lat"], m["pre_lon"], GEO_IMPORTED
        else:
            lat, lon, quality = geocoded_coords[geo_idx]
            geo_idx += 1

        row_dict = dict(m)
        del row_dict["pre_lat"]
        del row_dict["pre_lon"]
        row_dict["lat"] = lat
        row_dict["lon"] = lon
        row_dict["geo_quality"] = quality
        processed_rows.append(row_dict)

    return pd.DataFrame(processed_rows)


def process_imported_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Processes an imported CSV/Excel claims list: detects claim IDs, insured names,
    addresses, and priority ranks, then looks up each location.
    """
    return geocode_claim_rows(parse_claims_table(df))


# --- UPDATED CLAIMS LISTS ---

def _address_key(address: Any) -> str:
    """Comparable form of an address: ignores case, punctuation, spacing, and unit numbers."""
    return re.sub(r"[^A-Z0-9]", "", clean_address_for_geocoding(address).upper())


def build_merge_plan(existing_df: pd.DataFrame, new_raw_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compares an updated claims list to the claims already loaded, by claim number.
    Nothing is changed here. Returns:
      new:             parsed rows for claims not loaded yet (to add, with lookups)
      address_changes: [{claim_id, insured_name, old_address, new_address, new_state}]
      missing:         [claim_id, ...] loaded claims that aren't in the new list
      unchanged:       count of claims in both lists with the same address
    """
    parsed = parse_claims_table(new_raw_df)
    incoming: Dict[str, Dict[str, Any]] = {}
    for m in parsed:
        incoming.setdefault(str(m["claim_id"]).strip(), m)   # first row wins on duplicates

    existing = {str(r["claim_id"]).strip(): r for _, r in existing_df.iterrows()
                if r.get("status") != "Blocked"}   # blocked time isn't a claim

    new_rows, changes, unchanged, contact_fills = [], [], 0, []
    for cid, m in incoming.items():
        if cid not in existing:
            new_rows.append(m)
            continue
        # Fill phone/email only where the rep hasn't entered one
        fill = {}
        for field in ("phone", "email"):
            if _blank(existing[cid].get(field)) and m.get(field):
                fill[field] = m[field]
        if fill:
            contact_fills.append({"claim_id": cid, **fill})
        old_addr = existing[cid].get("full_address", "")
        if _address_key(old_addr) != _address_key(m["full_address"]):
            changes.append({
                "claim_id": cid,
                "insured_name": existing[cid].get("insured_name", ""),
                "old_address": old_addr,
                "new_address": m["full_address"],
                "new_state": m.get("state", ""),
            })
        else:
            unchanged += 1

    missing = [cid for cid in existing if cid not in incoming]
    return {"new": new_rows, "address_changes": changes, "missing": missing, "unchanged": unchanged,
            "contact_fills": contact_fills}


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


# --- FLEXIBLE AVAILABILITY ---
# Each inspection day is a working window (day start time + inspections per day x window
# length). Open time is whatever the actual bookings leave free, so shortening or moving
# an inspection immediately opens earlier time. Starts snap to 15-minute steps.

STEP_MINUTES = 15
_DAY_ABBR = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}


def round_up_to_step(dt: datetime, step_min: int = STEP_MINUTES) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    extra = dt.minute % step_min
    return dt + timedelta(minutes=step_min - extra) if extra else dt


def per_day_for(day: date, per_day: Any) -> int:
    """Inspections for this date. per_day is one number for every day, or {"Mon": 3, ..., "Sun": 0}."""
    if isinstance(per_day, dict):
        try:
            return int(per_day.get(_DAY_ABBR[day.weekday()], 0) or 0)
        except (TypeError, ValueError):
            return 0
    return int(per_day or 0)


def active_days_from(per_day: Any) -> List[str]:
    """Days of the week with at least one inspection."""
    if isinstance(per_day, dict):
        return [d for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] if int(per_day.get(d, 0) or 0) > 0]
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] if per_day else []


def day_window(day: date, day_start_time: Any, inspections_per_day: Any, window_hrs: float,
               latest_end: Any = None) -> Tuple[datetime, datetime]:
    """
    The usual working day: start time + inspections per day x window length,
    never later than latest_end (e.g. 7 PM). Suggested openings stay inside it.
    Reps can still book later by hand.
    """
    start = datetime.combine(day, day_start_time)
    end = start + timedelta(hours=per_day_for(day, inspections_per_day) * window_hrs)
    if latest_end is not None:
        end = min(end, datetime.combine(day, latest_end))
    return start, max(start, end)


def get_busy_intervals(claims_df: Optional[pd.DataFrame], exclude_claim_id: Any = None,
                       include_drafts: bool = False) -> List[Dict[str, Any]]:
    """
    Booked inspections as {start, end, claim_id, label, draft}, optionally leaving one
    claim out. Confirmed inspections only, unless include_drafts (unconfirmed drafts
    hold their time for suggestions, but a confirmed booking can replace them).
    """
    busy = []
    if claims_df is None or claims_df.empty or "status" not in claims_df.columns:
        return busy
    # Blocked time (a rep's own non-inspection time) is always busy, like a confirmed inspection
    statuses = ["Scheduled", "Blocked", "Draft"] if include_drafts else ["Scheduled", "Blocked"]
    for _, r in claims_df[claims_df["status"].isin(statuses)].iterrows():
        if exclude_claim_id is not None and str(r["claim_id"]) == str(exclude_claim_id):
            continue
        s, e = parse_wallclock(r.get("start_time")), parse_wallclock(r.get("end_time"))
        if s and e and e > s:
            busy.append({"start": s, "end": e, "claim_id": str(r["claim_id"]),
                         "label": (f"blocked time ({r.get('insured_name', '')})" if r["status"] == "Blocked"
                                   else f"{r['claim_id']} - {r.get('insured_name', '')}"),
                         "draft": r["status"] == "Draft", "block": r["status"] == "Blocked"})
    return busy


def compute_day_gaps(day: date, day_start_time: Any, inspections_per_day: int, window_hrs: float,
                     busy: List[Dict[str, Any]], now: Optional[datetime] = None,
                     latest_end: Any = None) -> List[Tuple[datetime, datetime]]:
    """Free time inside the day's working window, after bookings and (today) the current time."""
    ws, we = day_window(day, day_start_time, inspections_per_day, window_hrs, latest_end)
    cursor = ws
    if now and now > cursor:
        cursor = round_up_to_step(now)
    if cursor >= we:
        return []
    blocks = sorted((max(b["start"], ws), min(b["end"], we)) for b in busy if b["start"] < we and b["end"] > ws)
    gaps = []
    for s, e in blocks:
        if s > cursor:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < we:
        gaps.append((cursor, we))
    out = []
    for g0, g1 in gaps:
        g0 = round_up_to_step(g0)
        if g1 - g0 >= timedelta(minutes=STEP_MINUTES):
            out.append((g0, g1))
    return out


def _slot_dict(s_dt: datetime, e_dt: datetime) -> Dict[str, Any]:
    date_str = s_dt.strftime("%Y-%m-%d")
    time_label = f"{s_dt.strftime('%I:%M %p')} - {e_dt.strftime('%I:%M %p')}"
    return {
        "slot_label": f"{date_str} ({_DAY_ABBR[s_dt.weekday()]}) | {time_label}",
        "date_str": date_str,
        "start": s_dt.isoformat(),
        "end": e_dt.isoformat(),
    }


def compute_openings(start_date: date, end_date: date, active_days: List[str], day_start_time: Any,
                     inspections_per_day: int, window_hrs: float, claims_df: Optional[pd.DataFrame],
                     now: Optional[datetime] = None, exclude_claim_id: Any = None,
                     latest_end: Any = None, duration_hrs: Optional[float] = None,
                     include_drafts: bool = False) -> List[Dict[str, Any]]:
    """
    Suggested openings: inside each free gap, back-to-back blocks of the default window
    length, starting at the earliest free time. Example: day 8:00-3:30, 2.5 h windows,
    an inspection shortened to 8:00-9:30 -> openings at 9:30 and 12:00.
    Same shape as generate_available_slots, so the rest of the app can use either.
    """
    busy = get_busy_intervals(claims_df, exclude_claim_id, include_drafts)
    duration = timedelta(hours=duration_hrs or window_hrs)
    openings = []
    day = start_date
    while day <= end_date:
        if _DAY_ABBR[day.weekday()] in active_days:
            for g0, g1 in compute_day_gaps(day, day_start_time, inspections_per_day, window_hrs, busy, now, latest_end):
                t = g0
                while t + duration <= g1:
                    openings.append(_slot_dict(t, t + duration))
                    t += duration
        day += timedelta(days=1)
    return openings


def order_openings(openings: List[Dict[str, Any]], latest_days_first: bool = False) -> List[Dict[str, Any]]:
    """
    Orders suggested openings. Default: earliest day first. With latest_days_first,
    the last days of the deployment come first, but each day still runs morning to
    afternoon (for reps who fill their calendar from the end of the tour).
    """
    if not latest_days_first:
        return sorted(openings, key=lambda o: o["start"])
    by_day = sorted({o["date_str"] for o in openings}, reverse=True)
    rank = {d: i for i, d in enumerate(by_day)}
    return sorted(openings, key=lambda o: (rank[o["date_str"]], o["start"]))


def make_slot(start_dt: datetime, duration_hrs: float) -> Dict[str, Any]:
    """A custom booking at any start time and length."""
    return _slot_dict(start_dt, start_dt + timedelta(hours=duration_hrs))


def find_overlap(start_dt: datetime, end_dt: datetime, busy: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next((b for b in busy if max(start_dt, b["start"]) < min(end_dt, b["end"])), None)


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


# --- DRAFT SCHEDULE PLANNER ---
# Builds unconfirmed "Draft" appointments for unscheduled claims, around every
# confirmed appointment. Confirmed appointments never move. Running it again
# replaces only drafts.

_WEEKDAY_PLURAL = {"Mon": "Mondays", "Tue": "Tuesdays", "Wed": "Wednesdays", "Thu": "Thursdays",
                   "Fri": "Fridays", "Sat": "Saturdays", "Sun": "Sundays"}


def _miles(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Straight-line distance in miles (fast; used for grouping)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _loc(row: pd.Series) -> Optional[Tuple[float, float]]:
    try:
        if pd.notna(row["lat"]) and pd.notna(row["lon"]):
            return float(row["lat"]), float(row["lon"])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _inspection_days(S: Dict[str, Any], active_days: Optional[List[str]] = None,
                     end_date: Optional[date] = None) -> List[date]:
    days, d = [], S["start_date"]
    end_date = end_date or S["end_date"]
    active = active_days if active_days is not None else S["active_days"]
    while d <= end_date:
        if _DAY_ABBR[d.weekday()] in active:
            days.append(d)
        d += timedelta(days=1)
    return days


def _count_openings(claims_df: pd.DataFrame, S: Dict[str, Any], now: Optional[datetime], **overrides) -> int:
    p = dict(S, **overrides)
    return len(compute_openings(p["start_date"], p["end_date"], p["active_days"], p["day_start"],
                                p["per_day"], p["window_hrs"], claims_df, now=now,
                                latest_end=p.get("latest_end")))


def plan_candidates(claims_df: pd.DataFrame) -> pd.DataFrame:
    """Claims the planner places: unscheduled ones, plus current drafts (they get re-planned)."""
    return claims_df[claims_df["status"].isin(["Unscheduled", "Draft"])]


def capacity_report(claims_df: pd.DataFrame, S: Dict[str, Any], now: Optional[datetime]) -> Dict[str, Any]:
    """
    Compares claims to place with the openings your settings allow (around confirmed
    appointments). When they don't fit, lists specific fixes with the openings each adds.
    """
    n_claims = len(plan_candidates(claims_df))
    base = _count_openings(claims_df, S, now)
    report = {"claims": n_claims, "openings": base, "shortfall": max(0, n_claims - base), "suggestions": []}
    if report["shortfall"] == 0:
        return report
    need = report["shortfall"]
    sugg = []

    counts = S["per_day"] if isinstance(S["per_day"], dict) else {d: S["per_day"] for d in _DAY_ABBR.values()}
    used = [n for n in counts.values() if n]
    typical = max(set(used), key=used.count) if used else 3

    # Add a day of the week that's currently a day off
    for wd in ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]:
        if not counts.get(wd):
            new_counts = dict(counts, **{wd: typical})
            extra = _count_openings(claims_df, S, now, per_day=new_counts,
                                    active_days=active_days_from(new_counts)) - base
            if extra:
                sugg.append((f"Add {_WEEKDAY_PLURAL[wd]} ({typical} per day)", extra))

    # Extend the end date
    for k in range(1, 22):
        new_end = S["end_date"] + timedelta(days=k)
        extra = _count_openings(claims_df, S, now, end_date=new_end) - base
        if extra >= need:
            sugg.append((f"Extend the end date by {k} day{'s' if k > 1 else ''} (to {new_end.strftime('%b %d')})", extra))
            break

    # One more inspection on each inspection day (still within the latest-end limit)
    plus_one = {d: (n + 1 if n else 0) for d, n in counts.items()}
    extra = _count_openings(claims_df, S, now, per_day=plus_one) - base
    if extra > 0:
        sugg.append(("Add 1 inspection on each inspection day", extra))

    # Shorter windows in the same working hours (each day keeps its hours)
    best = None
    w = S["window_hrs"] - 0.25
    while w >= 1.5 - 1e-9:   # shorter than 1.5 hours isn't realistic for an on-site inspection
        shorter = {d: int(math.floor(n * S["window_hrs"] / w + 1e-9)) for d, n in counts.items()}
        if shorter != counts:
            extra = _count_openings(claims_df, S, now, per_day=shorter, window_hrs=w) - base
            if extra > 0 and (best is None or extra > best[1]):
                best = (w, extra)
            if extra >= need:
                best = (w, extra)
                break
        w -= 0.25
    if best:
        sugg.append((f"Shorten windows to {best[0]:g} hours (more per day in the same working hours)", best[1]))

    sugg.append(("Switch some claims to live video, which needs 1 hour each", None))
    report["suggestions"] = sugg
    return report


def plan_draft_schedule(claims_df: pd.DataFrame, S: Dict[str, Any], hotel_coords: Optional[Tuple[float, float]],
                        now: Optional[datetime], latest_first: bool = False, progress=None
                        ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns (drafts, summary). drafts: [{claim_id, start, end}] for claims to mark as Draft.

    1. Openings: free time on each inspection day around CONFIRMED appointments only
       (current drafts are being replaced), in blocks of the window length.
    2. Ranked claims first: priority 1, 2, 3... always go to the earliest days with room
       (whatever the fill direction), spread across the first two days with room when
       they're far apart, and take the earliest times on their day, in rank order.
    3. Unranked on-site claims are grouped by area, one day at a time: each day grows
       around its confirmed stops (or a new seed claim) by adding the nearest claim.
    4. Live video claims, claims without a pin, and claims whose location still needs
       a check fill the remaining openings last (and are listed in the summary).
    5. Each day is ordered as a route: every opening gets the claim with the shortest
       drive from the previous stop (or the hotel), using real drive times.
    """
    def step(frac, text):
        if progress:
            progress(frac, text)

    step(0.05, "Finding open time around your confirmed appointments...")
    confirmed = get_busy_intervals(claims_df)
    days = _inspection_days(S)
    if latest_first:
        days = list(reversed(days))

    window = timedelta(hours=S["window_hrs"])
    day_slots: Dict[date, List[datetime]] = {}
    for d in days:
        slots = []
        for g0, g1 in compute_day_gaps(d, S["day_start"], S["per_day"], S["window_hrs"], confirmed, now, S.get("latest_end")):
            t = g0
            while t + window <= g1:
                slots.append(t)
                t += window
        day_slots[d] = slots

    # Confirmed on-site stops per day, as routing anchors
    anchors: Dict[date, List[Tuple[datetime, datetime, Tuple[float, float]]]] = defaultdict(list)
    for _, r in claims_df[claims_df["status"] == "Scheduled"].iterrows():
        s, e_ = parse_wallclock(r.get("start_time")), parse_wallclock(r.get("end_time"))
        loc = _loc(r)
        if s and e_ and loc and not is_video(r.get("activity_type")):
            anchors[s.date()].append((s, e_, loc))

    step(0.2, "Grouping claims by area...")
    items = []
    for _, r in plan_candidates(claims_df).iterrows():
        rank = normalize_priority(r.get("priority"))
        items.append({"cid": str(r["claim_id"]), "rank": rank if rank is not None else math.inf,
                      "video": is_video(r.get("activity_type")), "loc": _loc(r),
                      "check": str(r.get("geo_quality", "")) in GEO_NEEDS_REVIEW})

    cap = {d: len(day_slots[d]) for d in days}
    members: Dict[date, List[Dict[str, Any]]] = {d: [] for d in days}

    def place(it):
        for d in days:
            if cap[d] > 0:
                members[d].append(it)
                cap[d] -= 1
                return True
        return False

    ranked = sorted([i for i in items if i["rank"] != math.inf], key=lambda i: i["rank"])
    unranked_site = [i for i in items if i["rank"] == math.inf and not i["video"] and i["loc"] and not i["check"]]
    leftovers = ([i for i in items if i["rank"] == math.inf and not i["video"] and i["loc"] and i["check"]] +
                 [i for i in items if i["rank"] == math.inf and (i["video"] or not i["loc"])])

    # Priorities go to the earliest days with room, whatever the fill direction. Among the
    # first two such days, each goes where it sits closest to that day's other stops; a day
    # with no stops yet "costs" SPREAD_MILES, so far-apart priorities spread out while
    # nearby ones share a day.
    SPREAD_MILES = 10.0
    chrono_days = sorted(days)
    unplaced = []
    for it in ranked:
        open_days = [d for d in chrono_days if cap[d] > 0][:2]
        if not open_days:
            unplaced.append(it)
            continue

        def day_cost(d):
            if not it["loc"] or it["video"]:
                return 0.0
            stops = [m["loc"] for m in members[d] if m["loc"] and not m["video"]] + [a[2] for a in anchors[d]]
            return min((_miles(it["loc"], s) for s in stops), default=SPREAD_MILES)
        best_day = min(open_days, key=lambda d: (round(day_cost(d), 1), chrono_days.index(d)))
        members[best_day].append(it)
        cap[best_day] -= 1

    # Area grouping for unranked on-site claims
    pool = list(unranked_site)
    center = hotel_coords
    if not center and pool:
        center = (sum(i["loc"][0] for i in pool) / len(pool), sum(i["loc"][1] for i in pool) / len(pool))
    # Days that already hold a priority claim or a confirmed stop collect their neighbors
    # first; empty days follow in the fill order.
    def has_stops(d):
        return any(m["loc"] and not m["video"] for m in members[d]) or bool(anchors[d])
    cluster_order = [d for d in days if has_stops(d)] + [d for d in days if not has_stops(d)]
    for d in cluster_order:
        while cap[d] > 0 and pool:
            pts = [m["loc"] for m in members[d] if m["loc"] and not m["video"]] + [a[2] for a in anchors[d]]
            if pts:
                c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
                pick = min(pool, key=lambda i: _miles(i["loc"], c))
            else:
                # Start a new area: sweep around the hotel, so each new day picks up where the last left off
                pick = min(pool, key=lambda i: math.atan2(i["loc"][0] - center[0], i["loc"][1] - center[1]))
            members[d].append(pick)
            cap[d] -= 1
            pool.remove(pick)
    unplaced += pool
    unplaced += [i for i in leftovers if not place(i)]

    # Order each day as a route and assign times
    step(0.45, "Ordering each day and checking drive times...")
    drafts = []
    for n, d in enumerate(days, start=1):
        step(0.45 + 0.5 * n / max(len(days), 1), f"Ordering {d.strftime('%a %b %d')}...")
        todo_rank = sorted([m for m in members[d] if m["rank"] != math.inf], key=lambda m: m["rank"])
        todo_site = [m for m in members[d] if m["rank"] == math.inf and m["loc"] and not m["video"] and not m["check"]]
        todo_other = [m for m in members[d] if m["rank"] == math.inf and not (m["loc"] and not m["video"] and not m["check"])]
        for t in day_slots[d]:
            if not todo_rank and not todo_site and not todo_other:
                break
            if todo_rank:
                pick = todo_rank.pop(0)
            elif todo_site:
                prev = None
                past_stops = [a for a in anchors[d] if a[1] <= t]
                past_drafts = [x for x in drafts if x["_date"] == d and x["_end"] <= t and x["_loc"]]
                cands = [(a[1], a[2]) for a in past_stops] + [(x["_end"], x["_loc"]) for x in past_drafts]
                if cands:
                    prev = max(cands, key=lambda c: c[0])[1]
                elif hotel_coords:
                    prev = hotel_coords
                if prev:
                    pick = min(todo_site, key=lambda m: get_osrm_route(prev[0], prev[1], m["loc"][0], m["loc"][1])[1])
                else:
                    pick = todo_site[0]
                todo_site.remove(pick)
            else:
                pick = todo_other.pop(0)
            end_t = t + (timedelta(hours=VIDEO_DEFAULT_HRS) if pick["video"] else window)
            drafts.append({"claim_id": pick["cid"], "start": t.isoformat(), "end": end_t.isoformat(),
                           "_date": d, "_start": t, "_end": end_t, "_loc": None if pick["video"] else pick["loc"],
                           "_check": pick["check"]})

    # Long drives: a drive that uses more than a third of the window leaves less time to
    # inspect (the window includes travel). Flag them, don't block them.
    long_drives = []
    window_min = S["window_hrs"] * 60
    for d in days:
        stops = sorted([(a[0], a[2], None) for a in anchors[d]] +
                       [(x["_start"], x["_loc"], x["claim_id"]) for x in drafts if x["_date"] == d and x["_loc"]],
                       key=lambda s: s[0])
        for (s_a, loc_a, cid_a), (s_b, loc_b, cid_b) in zip(stops, stops[1:]):
            mins = get_osrm_route(loc_a[0], loc_a[1], loc_b[0], loc_b[1])[1]
            if mins > window_min / 3 and (cid_a or cid_b):
                long_drives.append({"date": d.strftime("%a %b %d"), "from": cid_a or "a confirmed stop",
                                    "to": cid_b or "a confirmed stop", "mins": int(mins),
                                    "left_min": int(max(window_min - mins, 0))})

    step(1.0, "Done")
    days_used = len({x["_date"] for x in drafts})
    needs_check = [x["claim_id"] for x in drafts if x["_check"]]
    for x in drafts:
        for k in ("_date", "_start", "_end", "_loc", "_check"):
            x.pop(k, None)
    summary = {"placed": len(drafts), "days": days_used, "unplaced": [i["cid"] for i in unplaced],
               "openings": sum(len(s) for s in day_slots.values()), "claims": len(items),
               "needs_check": needs_check, "long_drives": long_drives}
    return drafts, summary


def best_spot_for_draft(claims_df: pd.DataFrame, claim_id: Any, S: Dict[str, Any],
                        hotel_coords: Optional[Tuple[float, float]], now: Optional[datetime],
                        latest_first: bool = False) -> Optional[Dict[str, Any]]:
    """
    A new home for a draft that a confirmed booking just replaced: the open spot
    (around confirmed appointments and other drafts) closest to that day's other stops.
    """
    row = claims_df[claims_df["claim_id"].astype(str) == str(claim_id)]
    if row.empty:
        return None
    row = row.iloc[0]
    video = is_video(row.get("activity_type"))
    openings = order_openings(
        compute_openings(S["start_date"], S["end_date"], S["active_days"], S["day_start"], S["per_day"],
                         S["window_hrs"], claims_df, now=now, exclude_claim_id=claim_id,
                         latest_end=S.get("latest_end"),
                         duration_hrs=VIDEO_DEFAULT_HRS if video else None, include_drafts=True),
        latest_days_first=latest_first)
    if not openings:
        return None
    loc = _loc(row)
    if video or not loc:
        return openings[0]

    stops_by_day: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for _, r in claims_df[claims_df["status"].isin(["Scheduled", "Draft"])].iterrows():
        if str(r["claim_id"]) == str(claim_id) or is_video(r.get("activity_type")):
            continue
        s, l_ = parse_wallclock(r.get("start_time")), _loc(r)
        if s and l_:
            stops_by_day[s.strftime("%Y-%m-%d")].append(l_)

    def score(pos_o):
        pos, o = pos_o
        stops = stops_by_day.get(o["date_str"]) or ([hotel_coords] if hotel_coords else [])
        dist = min((_miles(loc, s) for s in stops), default=0.0)
        return (round(dist, 1), pos)
    return min(enumerate(openings), key=score)[1]


# --- RECOMMENDATION ENGINE ---

def find_previous_stop(claims_df: pd.DataFrame, slot: Dict[str, Any]) -> Optional[pd.Series]:
    """
    Returns the scheduled claim that ends latest at or before the opening starts,
    on the same day. That's where the rep will be driving from.
    """
    slot_start = parse_wallclock(slot["start"])
    same_day = claims_df[
        (claims_df["status"].isin(["Scheduled", "Draft"])) &
        (claims_df["scheduled_date"].astype(str) == slot["date_str"])
    ]
    if "activity_type" in same_day.columns:   # live video inspections don't move the rep
        same_day = same_day[~same_day["activity_type"].apply(is_video)]
    best_row, best_end = None, None
    for _, row in same_day.iterrows():
        c_end = parse_wallclock(row["end_time"])
        if c_end and c_end <= slot_start and (best_end is None or c_end > best_end):
            best_row, best_end = row, c_end
    return best_row


def find_next_stop(claims_df: pd.DataFrame, slot: Dict[str, Any]) -> Optional[pd.Series]:
    """The scheduled claim that starts soonest at or after the opening ends, on the same day."""
    slot_end = parse_wallclock(slot["end"])
    same_day = claims_df[
        (claims_df["status"].isin(["Scheduled", "Draft"])) &
        (claims_df["scheduled_date"].astype(str) == slot["date_str"])
    ]
    if "activity_type" in same_day.columns:
        same_day = same_day[~same_day["activity_type"].apply(is_video)]
    best_row, best_start = None, None
    for _, row in same_day.iterrows():
        c_start = parse_wallclock(row["start_time"])
        if c_start and c_start >= slot_end and (best_start is None or c_start < best_start):
            best_row, best_start = row, c_start
    return best_row


def get_recommendations_for_slot(
    claims_df: pd.DataFrame,
    slot: Dict[str, Any],
    hotel_coords: Optional[Tuple[float, float]] = None,
    include_statuses: Tuple[str, ...] = ("Unscheduled",),
    now_local: Optional[datetime] = None,
    mode: str = "fast"
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

    mode="fast":   tiebreaker is drive time from the anchor (one route lookup per claim).
    mode="detour": tiebreaker is the extra driving the claim adds between the anchor and
                   where you go next (the next booked inspection that day, else the hotel):
                   anchor->claim + claim->next - anchor->next. Two lookups per claim.
                   Also flags claims that would make you late for the next inspection.

    Sorted FIRST by priority rank (1, 2, 3...; unranked last), SECOND by the tiebreaker.
    Returns (recs_df or None, anchor_info).
    """
    anchor_info = {"type": "claims_center", "label": "center of claims"}
    if claims_df is None or claims_df.empty:
        return None, anchor_info

    prev_stop = find_previous_stop(claims_df, slot)
    if prev_stop is not None and (pd.isna(prev_stop["lat"]) or pd.isna(prev_stop["lon"])):
        prev_stop = None  # previous stop has no pin yet; fall back to the hotel
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

    # Where you go after this opening (detour mode only)
    next_info = None
    if mode == "detour":
        nxt = find_next_stop(claims_df, slot)
        if nxt is not None and pd.notna(nxt["lat"]) and pd.notna(nxt["lon"]):
            next_info = {
                "type": "next_stop", "claim_id": str(nxt["claim_id"]),
                "lat": float(nxt["lat"]), "lon": float(nxt["lon"]),
                "start": parse_wallclock(nxt["start_time"]),
                "label": f"next stop {nxt['claim_id']} ({parse_wallclock(nxt['start_time']).strftime('%I:%M %p').lstrip('0')})",
            }
        elif hotel_coords:
            next_info = {"type": "hotel", "claim_id": None, "lat": hotel_coords[0], "lon": hotel_coords[1],
                         "start": None, "label": "the hotel"}
    anchor_info["next"] = next_info

    candidates = claims_df[claims_df["status"].isin(include_statuses)].copy()
    if anchor_info["type"] == "previous_stop":
        candidates = candidates[candidates["claim_id"].astype(str) != anchor_info["claim_id"]]
    if next_info and next_info["claim_id"]:
        candidates = candidates[candidates["claim_id"].astype(str) != next_info["claim_id"]]

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

    anchor_ok = pd.notna(anchor_lat) and pd.notna(anchor_lon)
    miles_list, mins_list = [], []
    video_flags = [is_video(v) for v in (candidates["activity_type"] if "activity_type" in candidates.columns
                                         else [""] * len(candidates))]
    for (_, row), video in zip(candidates.iterrows(), video_flags):
        if video:
            miles, mins = None, None  # live video: no drive
        elif anchor_ok and pd.notna(row["lat"]) and pd.notna(row["lon"]):
            miles, mins = get_osrm_route(float(anchor_lat), float(anchor_lon), float(row["lat"]), float(row["lon"]))
        else:
            miles, mins = None, None  # no pin yet: listed after claims with drive times
        miles_list.append(miles)
        mins_list.append(mins)

    candidates["drive_miles"] = miles_list
    candidates["drive_time_mins"] = mins_list

    # Detour mode: extra driving this claim adds on the way to the next destination
    detour_list, to_next_list, late_list = [], [], []
    if next_info and anchor_ok:
        _, base_mins = get_osrm_route(float(anchor_lat), float(anchor_lon), next_info["lat"], next_info["lon"])
        slot_end = parse_wallclock(slot["end"])
        gap_mins = ((next_info["start"] - slot_end).total_seconds() / 60) if next_info["start"] else None
        for (_, row), d1 in zip(candidates.iterrows(), mins_list):
            if d1 is None:  # live video or no pin
                detour_list.append(None); to_next_list.append(None); late_list.append(False)
                continue
            _, d2 = get_osrm_route(float(row["lat"]), float(row["lon"]), next_info["lat"], next_info["lon"])
            detour_list.append(max(0, d1 + d2 - base_mins))
            to_next_list.append(d2)
            late_list.append(gap_mins is not None and d2 > gap_mins)
    else:
        detour_list = [None] * len(candidates)
        to_next_list = [None] * len(candidates)
        late_list = [False] * len(candidates)
    candidates["detour_mins"] = detour_list
    candidates["drive_to_next_mins"] = to_next_list
    candidates["late_for_next"] = late_list
    candidates["anchor_type"] = anchor_info["type"]
    candidates["is_video"] = video_flags
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
    if mode == "detour" and next_info and anchor_ok:
        # Claims that would make you late for the next inspection sort after the rest
        candidates["drive_sort_key"] = [
            (float("inf") if d is None else float(d) + (10_000 if late else 0))
            for d, late in zip(detour_list, late_list)
        ]
    else:
        candidates["drive_sort_key"] = [float(m) if m is not None else float("inf") for m in mins_list]
    # Live video claims fit any opening, so they list after on-site claims of the same
    # rank (ahead of claims still missing a pin)
    candidates["drive_sort_key"] = [1e8 if v else k for v, k in zip(video_flags, candidates["drive_sort_key"])]
    # Claims whose location still needs a check list after claims with good locations
    if "geo_quality" in candidates.columns:
        candidates["drive_sort_key"] = [k + 5e7 if (q in GEO_NEEDS_REVIEW and k < 1e8) else k
                                        for q, k in zip(candidates["geo_quality"], candidates["drive_sort_key"])]
    candidates = candidates.sort_values(
        by=["prio_sort_key", "drive_sort_key"], ascending=[True, True], kind="mergesort"
    ).drop(columns=["prio_sort_key", "drive_sort_key"])

    return candidates, anchor_info


# --- ICS CALENDAR EXPORT ---

def _ics_escape(text: Any) -> str:
    """Escapes text per RFC 5545 (backslash, semicolon, comma, newline)."""
    s = str(text) if text is not None else ""
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_body(row: pd.Series) -> str:
    """
    Labeled block for each appointment. Labels always appear (even when blank) in a
    fixed order, so a bot can read them reliably. The note goes last since it can
    run several lines. Email addresses and phone numbers are tappable on phones.
    """
    lines = [
        "CLAIM DATA START",
        f"Phone Number: {normalize_phone(row.get('phone'))}",
        f"Email: {clean_text(row.get('email'))}",
        f"Initial Contact Note: {clean_text(row.get('contact_note'))[:NOTE_MAX_CHARS]}",
        "CLAIM DATA END",
    ]
    return "\n".join(lines)


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
            f"SUMMARY:{_ics_escape(('CAT Live Video Inspection - ' if is_video(row.get('activity_type')) else 'CAT Inspection - ') + str(row['claim_id']) + ' (' + str(row['insured_name']) + ')')}",
            f"DESCRIPTION:{_ics_escape(_ics_body(row))}",
            f"LOCATION:{_ics_escape(('Live video: ' if is_video(row.get('activity_type')) else '') + str(row['full_address']))}",
            f"DTSTART:{fmt(s_dt)}",
            f"DTEND:{fmt(e_dt)}",
            "END:VEVENT"
        ])

    ics_lines.append("END:VCALENDAR")
    return "\r\n".join(ics_lines) + "\r\n"
