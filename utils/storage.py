import json
import os

DATA_DIR = os.getenv("DATA_DIR", "data")

def get_sessions_file_path(club_code: str) -> str:
    return os.path.join(DATA_DIR, f"sessions_{club_code.upper()}.json")

# -----------------------------
# LOAD SESSIONS
# -----------------------------
def load_sessions(club_code: str):
    file_path = get_sessions_file_path(club_code)
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

# -----------------------------
# SAVE SESSIONS
# -----------------------------
def save_sessions(club_code: str, sessions):
    file_path = get_sessions_file_path(club_code)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(
            sessions,
            f,
            indent=4
        )

# -----------------------------
# ADD SESSION
# -----------------------------
def add_session(club_code: str, session_data):
    sessions = load_sessions(club_code)
    sessions.append(session_data)
    save_sessions(club_code, sessions)

# -----------------------------
# DELETE SESSION
# -----------------------------
def delete_session(
    club_code: str,
    sessions,
    index
):
    sessions.pop(index)
    save_sessions(club_code, sessions)
    return sessions

# -----------------------------
# UPDATE SESSION
# -----------------------------
def update_session(
    club_code: str,
    sessions,
    index,
    updated_session
):
    sessions[index] = updated_session
    save_sessions(club_code, sessions)
    return sessions