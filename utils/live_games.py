import json
import os
import random
import string
from datetime import datetime

DATA_DIR = os.getenv("DATA_DIR", "data")

def get_live_games_file_path(club_code: str) -> str:
    return os.path.join(DATA_DIR, f"live_games_{club_code.upper()}.json")

def load_live_games(club_code: str):
    file_path = get_live_games_file_path(club_code)
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_live_games(club_code: str, games):
    file_path = get_live_games_file_path(club_code)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(games, f, indent=4)

def generate_code(club_code: str):
    while True:
        code = "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=4
            )
        )
        games = load_live_games(club_code)
        exists = any(
            g["code"] == code
            for g in games
        )
        if not exists:
            return code

def generate_player_token():
    return "".join(
        random.choices(
            string.ascii_uppercase + string.digits,
            k=8
        )
    )

def create_live_game(club_code: str, name: str):
    games = load_live_games(club_code)
    game = {
        "code": generate_code(club_code),
        "name": name,
        "status": "active",
        "players": []
    }
    games.append(game)
    save_live_games(club_code, games)
    return game

def get_live_game(club_code: str, code: str):
    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            return game
    return None

def join_live_game(club_code: str, code: str, player_name: str):
    # Check if the player is kicked from the club first
    from utils.club import is_player_kicked
    if is_player_kicked(club_code, player_name):
        return False

    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            exists = any(
                player["name"] == player_name
                for player in game["players"]
            )
            if not exists:
                game["players"].append({
                    "name": player_name,
                    "buyin": 0,
                    "cashout": 0,
                    "history": [],
                    "token": generate_player_token()
                })
            save_live_games(club_code, games)
            return True
    return False

def add_buyin(club_code: str, code: str, player_name: str, amount: int):
    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            for player in game["players"]:
                if player["name"] == player_name:
                    player["buyin"] += amount
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    player["history"].append({
                        "type": "buyin",
                        "amount": amount,
                        "timestamp": timestamp
                    })
                    save_live_games(club_code, games)
                    return True
    return False

def update_cashout(club_code: str, code: str, player_name: str, amount: int):
    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            for player in game["players"]:
                if player["name"] == player_name:
                    player["buyin"] = player.get("buyin", 0)
                    player["cashout"] = amount
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    found = False
                    if "history" not in player or not isinstance(player["history"], list):
                        player["history"] = []

                    for tx in player["history"]:
                        if isinstance(tx, dict) and tx.get("type") == "cashout":
                            tx["amount"] = amount
                            tx["timestamp"] = timestamp
                            found = True
                            break

                    if not found:
                        player["history"].append({
                            "type": "cashout",
                            "amount": amount,
                            "timestamp": timestamp
                        })
                    save_live_games(club_code, games)
                    return True
    return False

def get_total_pool(game):
    total = 0
    for player in game["players"]:
        total += player["buyin"]
    return total

def get_player(club_code: str, code: str, player_name: str):
    game = get_live_game(club_code, code)
    if not game:
        return None
    for player in game["players"]:
        if player["name"] == player_name:
            return player
    return None

def get_player_history(club_code: str, code: str, player_name: str):
    player = get_player(club_code, code, player_name)
    if not player:
        return []
    return player.get("history", [])

def get_player_by_token(club_code: str, code: str, token: str):
    game = get_live_game(club_code, code)
    if not game:
        return None
    for player in game["players"]:
        if player.get("token") == token:
            return player
    return None

def kick_player_from_live_game(club_code: str, code: str, player_name: str):
    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            original_len = len(game["players"])
            game["players"] = [p for p in game["players"] if p["name"] != player_name]
            if len(game["players"]) != original_len:
                save_live_games(club_code, games)
                return True
    return False

def end_live_game(club_code: str, code: str):
    from datetime import date
    from utils.storage import add_session

    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            game["status"] = "ended"
            session_players = []
            for player in game["players"]:
                session_players.append({
                    "name": player["name"],
                    "buyin": str(player["buyin"]),
                    "result": player.get("cashout", 0) - player["buyin"]
                })
            session_data = {
                "session_name": f"{game['name']} Live",
                "session_date": date.today().isoformat(),
                "players": session_players
            }
            add_session(club_code, session_data)
            save_live_games(club_code, games)
            return True
    return False

def admin_update_player(
    club_code: str,
    code: str,
    player_name: str,
    buyin: int,
    cashout: int
):
    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            for player in game["players"]:
                if player["name"] == player_name:
                    player["buyin"] = buyin
                    player["cashout"] = cashout
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    player["history"] = []
                    if buyin > 0:
                        player["history"].append({
                            "type": "buyin",
                            "amount": buyin,
                            "timestamp": timestamp
                        })
                    if cashout > 0:
                        player["history"].append({
                            "type": "cashout",
                            "amount": cashout,
                            "timestamp": timestamp
                        })
                    save_live_games(club_code, games)
                    return True
    return False

def add_buyin_request(club_code: str, code: str, player_name: str, amount: int) -> dict:
    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            if "buyin_requests" not in game:
                game["buyin_requests"] = []
            req_id = "req_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
            request_item = {
                "id": req_id,
                "player_name": player_name,
                "amount": amount,
                "status": "pending",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            game["buyin_requests"].append(request_item)
            save_live_games(club_code, games)
            return request_item
    return None

def resolve_buyin_request(club_code: str, code: str, req_id: str, action: str) -> bool:
    games = load_live_games(club_code)
    for game in games:
        if game["code"] == code:
            requests = game.get("buyin_requests", [])
            for req in requests:
                if req["id"] == req_id and req["status"] == "pending":
                    if action == "approve":
                        req["status"] = "approved"
                        player_name = req["player_name"]
                        amount = req["amount"]
                        for player in game["players"]:
                            if player["name"] == player_name:
                                player["buyin"] += amount
                                player["history"].append({
                                    "type": "buyin",
                                    "amount": amount,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
                                })
                                break
                    else:
                        req["status"] = "declined"
                    save_live_games(club_code, games)
                    return True
    return False