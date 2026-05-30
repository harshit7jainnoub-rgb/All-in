import json
import os

DATA_DIR = os.getenv("DATA_DIR", "data")
DATA_FILE = os.path.join(DATA_DIR, "sessions.json")

# -----------------------------
# LOAD SESSIONS
# -----------------------------

def load_sessions():

    if os.path.exists(DATA_FILE):

        with open(DATA_FILE, "r") as f:

            return json.load(f)

    return []

# -----------------------------
# SAVE SESSIONS
# -----------------------------

def save_sessions(sessions):

    with open(DATA_FILE, "w") as f:

        json.dump(
            sessions,
            f,
            indent=4
        )

# -----------------------------
# ADD SESSION
# -----------------------------

def add_session(session_data):

    sessions = load_sessions()

    sessions.append(session_data)

    save_sessions(sessions)

# -----------------------------
# DELETE SESSION
# -----------------------------

def delete_session(
    sessions,
    index
):

    sessions.pop(index)

    save_sessions(sessions)

    return sessions

# -----------------------------
# UPDATE SESSION
# -----------------------------

def update_session(
    sessions,
    index,
    updated_session
):

    sessions[index] = updated_session

    save_sessions(sessions)

    return sessions