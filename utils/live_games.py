import json
import os
import random
import string
from datetime import datetime

DATA_DIR = os.getenv("DATA_DIR", "data")
FILE_PATH = os.path.join(DATA_DIR, "live_games.json")


def load_live_games():

    if not os.path.exists(FILE_PATH):

        return []

    with open(
        FILE_PATH,
        "r"
    ) as f:

        return json.load(f)


def save_live_games(games):

    with open(
        FILE_PATH,
        "w"
    ) as f:

        json.dump(
            games,
            f,
            indent=4
        )


def generate_code():

    while True:

        code = "".join(

            random.choices(

                string.ascii_uppercase +
                string.digits,

                k=4

            )

        )

        games = load_live_games()

        exists = any(

            g["code"] == code

            for g in games

        )

        if not exists:

            return code

def generate_player_token():

    return "".join(

        random.choices(

            string.ascii_uppercase +
            string.digits,

            k=8

        )

    )


def create_live_game(name):

    games = load_live_games()

    game = {

        "code":
            generate_code(),

        "name":
            name,

        "status":
            "active",

        "players": []

    }

    games.append(game)

    save_live_games(games)

    return game

def get_live_game(code):

    games = load_live_games()

    for game in games:

        if game["code"] == code:

            return game

    return None



def join_live_game(
    code,
    player_name
):

    games = load_live_games()

    for game in games:

        if game["code"] == code:

            exists = any(

                player["name"] == player_name

                for player in game["players"]

            )

            if not exists:

                game["players"].append({

                    "name":
                        player_name,

                    "buyin":
                        0,

                    "cashout":
                        0,

                    "history":
                        [],

                    "token":
                        generate_player_token()

                })

            save_live_games(
                games
            )

            return True

    return False

def add_buyin(
    code,
    player_name,
    amount
):

    games = load_live_games()

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

                    save_live_games(
                        games
                    )

                    return True

    return False

def update_cashout(
    code,
    player_name,
    amount
):

    games = load_live_games()

    for game in games:

        if game["code"] == code:

            for player in game["players"]:

                if player["name"] == player_name:

                    player["buyin"] = player.get("buyin", 0) # ensure it is present
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

                    save_live_games(
                        games
                    )

                    return True

    return False

def get_total_pool(
    game
):

    total = 0

    for player in game["players"]:

        total += player["buyin"]

    return total

def get_player(
    code,
    player_name
):

    game = get_live_game(
        code
    )

    if not game:

        return None

    for player in game["players"]:

        if player["name"] == player_name:

            return player

    return None

def get_player_history(
    code,
    player_name
):

    player = get_player(
        code,
        player_name
    )

    if not player:

        return []

    return player.get(
        "history",
        []
    )

def get_player_by_token(
    code,
    token
):

    game = get_live_game(
        code
    )

    if not game:

        return None

    for player in game["players"]:

        if player.get(
            "token"
        ) == token:

            return player

    return None

def end_live_game(code):
    from datetime import date
    from utils.storage import add_session

    games = load_live_games()

    for game in games:

        if game["code"] == code:

            game["status"] = "ended"

            session_players = []

            for player in game["players"]:

                session_players.append({

                    "name":
                        player["name"],

                    "buyin":
                        str(player["buyin"]),

                    "result":
                        player.get("cashout", 0) - player["buyin"]

                })

            session_data = {

                "session_name":
                    f"{game['name']} Live",

                "session_date":
                    date.today().isoformat(),

                "players":
                    session_players

            }

            add_session(session_data)

            save_live_games(games)

            return True

    return False

def admin_update_player(
    code,
    player_name,
    buyin,
    cashout
):

    games = load_live_games()

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

                    save_live_games(
                        games
                    )

                    return True

    return False