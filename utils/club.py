import json
import os
import random
import string

DATA_DIR = os.getenv("DATA_DIR", "data")

def get_club_config_path(club_code: str) -> str:
    return os.path.join(DATA_DIR, f"club_{club_code.upper()}.json")

def load_club_config(club_code: str) -> dict:
    path = get_club_config_path(club_code)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None

def save_club_config(club_code: str, config: dict) -> None:
    path = get_club_config_path(club_code)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=4)

def create_club(club_code: str, club_name: str, host_pin: str) -> dict:
    config = {
        "club_code": club_code.upper(),
        "club_name": club_name,
        "host_pin": host_pin,
        "profiles": {}
    }
    save_club_config(club_code, config)
    return config

def verify_host_pin(club_code: str, pin: str) -> bool:
    config = load_club_config(club_code)
    if not config:
        return False
    return config.get("host_pin") == pin

def register_player_profile(club_code: str, name: str, pin: str) -> dict:
    config = load_club_config(club_code)
    if not config:
        return None
    
    if "profiles" not in config:
        config["profiles"] = {}
        
    normalized_name = name.strip()
    if normalized_name in config["profiles"]:
        # Profile already exists
        return None
        
    token = "".join(random.choices(string.ascii_uppercase + string.digits, k=16))
    profile = {
        "name": normalized_name,
        "pin": pin,
        "token": token,
        "status": "active"
    }
    config["profiles"][normalized_name] = profile
    save_club_config(club_code, config)
    return profile

def verify_player_profile(club_code: str, name: str, pin: str) -> dict:
    config = load_club_config(club_code)
    if not config:
        return None
    profiles = config.get("profiles", {})
    normalized_name = name.strip()
    if normalized_name not in profiles:
        return None
    profile = profiles[normalized_name]
    if profile.get("pin") == pin and profile.get("status", "active") == "active":
        return profile
    return None

def kick_player_from_club(club_code: str, player_name: str) -> bool:
    config = load_club_config(club_code)
    if not config:
        return False
    profiles = config.get("profiles", {})
    normalized_name = player_name.strip()
    if normalized_name in profiles:
        profiles[normalized_name]["status"] = "kicked"
        save_club_config(club_code, config)
        return True
    return False

def is_player_kicked(club_code: str, player_name: str) -> bool:
    config = load_club_config(club_code)
    if not config:
        return False
    profiles = config.get("profiles", {})
    normalized_name = player_name.strip()
    if normalized_name in profiles:
        return profiles[normalized_name].get("status", "active") == "kicked"
    return False

def get_club_profiles(club_code: str) -> list:
    config = load_club_config(club_code)
    if not config:
        return []
    return list(config.get("profiles", {}).values())
