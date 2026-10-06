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
GEO_IMPORTED = "From import file"
GEO_UNKNOWN = "Unknown"

# Pins a rep should double-check or place by hand
GEO_NEEDS_REVIEW = {GEO_ZIP, GEO_CITY, GEO_NOT_FOUND}

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
    OpenStreetMap is NOT used here; it's slow (1 request/second), so it runs only when
    the rep asks for it (see improve_with_openstreetmap).
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


def improve_with_openstreetmap(address_state_list: List[Tuple[str, Optional[str]]]) -> List[Optional[Tuple[float, float, str]]]:
    """
    Optional slower pass for pins that are approximate or missing. Tries OpenStreetMap
    (structured fields, then the full address). About 1-2 seconds per address because of
    OpenStreetMap's 1-request-per-second limit. Returns a better (lat, lon, quality) or None.
    """
    out = []
    total = len(address_state_list)
    progress_bar = st.progress(0.0, text="Checking OpenStreetMap...")
    for n, (addr, st_val) in enumerate(address_state_list, start=1):
        progress_bar.progress(n / max(total, 1), text=f"Checking OpenStreetMap: {n} of {total}")
        street, city, st_abbr, zip_code = parse_us_address(addr, fallback_state=st_val or "")
        hit = None
        if street and (city or zip_code):
            fields = [("street", street), ("city", city), ("state", st_abbr), ("postalcode", zip_code)]
            hit = _try(_nominatim, tuple((k, v) for k, v in fields if v))
        if not hit and street:
            oneline = ", ".join(p for p in [street, city, f"{st_abbr} {zip_code}".strip()] if p)
            hit = _try(_nominatim, (("q", oneline),))
        out.append((hit[0], hit[1], GEO_OSM) if hit else None)
    progress_bar.empty()
    return out


@st.cache_data(show_spinner=False)
def _nominatim(params_items: Tuple[Tuple[str, str], ...]) -> Optional[Tuple[float, float]]:
    """Nominatim lookup. Free-text (q) and structured fields are never mixed."""
    _nominatim_throttle()
    params = dict(params_items)
    params.update({"format": "json", "limit": "1", "countrycodes": "us"})
    resp = requests.get("https://nominatim.openstreetmap.org/search",
                        params=params, headers=_nominatim_headers(), timeout=8)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def _try(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


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

    anchor_ok = pd.notna(anchor_lat) and pd.notna(anchor_lon)
    miles_list, mins_list = [], []
    for _, row in candidates.iterrows():
        if anchor_ok and pd.notna(row["lat"]) and pd.notna(row["lon"]):
            miles, mins = get_osrm_route(float(anchor_lat), float(anchor_lon), float(row["lat"]), float(row["lon"]))
        else:
            miles, mins = None, None  # no pin yet: listed after claims with drive times
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
    candidates["drive_sort_key"] = [float(m) if m is not None else float("inf") for m in mins_list]
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

