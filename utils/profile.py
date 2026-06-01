import json
import os
import random
import string

def _resolve_data_dir() -> str:
    env_dir = os.getenv("DATA_DIR")
    if env_dir:
        return env_dir
    for path in ["/data", "/app/data"]:
        if os.path.exists(path) and os.access(path, os.W_OK):
            return path
    return "data"

DATA_DIR = _resolve_data_dir()
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")

def load_profiles() -> dict:
    if not os.path.exists(PROFILES_FILE):
        return {}
    try:
        with open(PROFILES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_profiles(profiles: dict) -> None:
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=4)

def is_phone_taken(phone: str) -> bool:
    profiles = load_profiles()
    norm_phone = phone.strip()
    return any(p.get("phone") == norm_phone for p in profiles.values())

def create_profile(name: str, phone: str, dob: str, pin: str) -> dict:
    profiles = load_profiles()
    normalized_name = name.strip()
    normalized_phone = phone.strip()
    normalized_dob = dob.strip()
    
    if normalized_name in profiles:
        return None
    if is_phone_taken(normalized_phone):
        return None
        
    token = "GP_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=16))
    profile = {
        "name": normalized_name,
        "phone": normalized_phone,
        "dob": normalized_dob,
        "pin": pin,
        "token": token,
        "clubs": [],
        "created_clubs": []
    }
    profiles[normalized_name] = profile
    save_profiles(profiles)
    return profile

def authenticate_profile(name: str, pin: str) -> dict:
    profiles = load_profiles()
    normalized_name = name.strip()
    if normalized_name not in profiles:
        return None
    profile = profiles[normalized_name]
    if profile.get("pin") == pin:
        return profile
    return None

def get_profile_by_token(token: str) -> dict:
    profiles = load_profiles()
    for profile in profiles.values():
        if profile.get("token") == token:
            return profile
    return None

def get_profile_by_phone(phone: str) -> dict:
    profiles = load_profiles()
    norm_phone = phone.strip()
    for profile in profiles.values():
        if profile.get("phone") == norm_phone:
            return profile
    return None

def add_club_to_profile(profile_name: str, club_code: str) -> None:
    profiles = load_profiles()
    normalized_name = profile_name.strip()
    club_upper = club_code.upper()
    if normalized_name in profiles:
        profile = profiles[normalized_name]
        if "clubs" not in profile:
            profile["clubs"] = []
        if club_upper not in profile["clubs"]:
            profile["clubs"].append(club_upper)
            save_profiles(profiles)

def add_created_club_to_profile(profile_name: str, club_code: str) -> None:
    profiles = load_profiles()
    normalized_name = profile_name.strip()
    club_upper = club_code.upper()
    if normalized_name in profiles:
        profile = profiles[normalized_name]
        if "created_clubs" not in profile:
            profile["created_clubs"] = []
        if club_upper not in profile["created_clubs"]:
            profile["created_clubs"].append(club_upper)
        if "clubs" not in profile:
            profile["clubs"] = []
        if club_upper not in profile["clubs"]:
            profile["clubs"].append(club_upper)
        save_profiles(profiles)

def update_profile_pin(profile_name: str, new_pin: str) -> bool:
    profiles = load_profiles()
    normalized_name = profile_name.strip()
    if normalized_name in profiles:
        profiles[normalized_name]["pin"] = new_pin
        save_profiles(profiles)
        return True
    return False

def verify_recovery_details(phone: str, dob: str) -> dict:
    profile = get_profile_by_phone(phone)
    if profile and profile.get("dob") == dob.strip():
        return profile
    return None
