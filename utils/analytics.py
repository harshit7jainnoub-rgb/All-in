# -----------------------------
# ANALYTICS
# -----------------------------

def get_analytics(sessions):

    total_sessions = len(sessions)

    all_players = set()

    player_totals = {}

    total_money = 0

    recent_session = None

    if sessions:

        recent_session = sessions[-1]

    for session in sessions:

        for player in session["players"]:

            name = player["name"]

            result = float(
                player["result"]
            )

            total_money += abs(result)

            all_players.add(name)

            player_totals[name] = (

                player_totals.get(name, 0)
                + result

            )

    biggest_winner = "N/A"
    biggest_loser = "N/A"

    winner_amount = 0
    loser_amount = 0

    if player_totals:

        biggest_winner = max(
            player_totals,
            key=player_totals.get
        )

        biggest_loser = min(
            player_totals,
            key=player_totals.get
        )

        winner_amount = round(
            player_totals[biggest_winner],
            2
        )

        loser_amount = round(
            player_totals[biggest_loser],
            2
        )

    leaderboard = sorted(

        player_totals.items(),

        key=lambda x: x[1],

        reverse=True

    )

    return {

        "total_sessions":
            total_sessions,

        "total_players":
            len(all_players),

        "biggest_winner":
            biggest_winner,

        "biggest_loser":
            biggest_loser,

        "winner_amount":
            winner_amount,

        "loser_amount":
            loser_amount,

        "total_money":
            round(total_money, 2),

        "recent_session":
            recent_session,

        "leaderboard":
            leaderboard[:5]
    }