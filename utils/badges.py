import os
import json
from utils.storage import load_sessions

BADGES_DEFINITION = {
    "shark": {"name": "The Shark", "emoji": "🦈", "description": "Career net profit is the highest in the club (min 2 sessions)."},
    "whale": {"name": "The Whale", "emoji": "🐳", "description": "Highest single buy-in amount in the club (min 2 sessions)."},
    "fish": {"name": "The Fish", "emoji": "🎣", "description": "Bought in 3+ times in a single session."},
    "wall": {"name": "The Wall", "emoji": "🧱", "description": "100% win rate across at least 5 sessions played (0 losses)."},
    "streak": {"name": "Consistent Earner", "emoji": "📈", "description": "Won 3+ consecutive sessions in the club."},
    "rollercoaster": {"name": "The Rollercoaster", "emoji": "🎢", "description": "Volatile swing style (at least one win > 500 and one loss > 500)."},
    "champion": {"name": "The Champion", "emoji": "🏆", "description": "Most total winning sessions in the club."},
    "high_roller": {"name": "High Roller", "emoji": "💎", "description": "Average buy-in across all sessions is >= 1000."},
    "turtle": {"name": "The Turtle", "emoji": "🐢", "description": "Lowest average buy-in (min 3 sessions)."},
    "survivor": {"name": "The Survivor", "emoji": "💀", "description": "Finished a session with exactly their buy-in or within +/- 5% profit/loss."},
    "scholar": {"name": "The Scholar", "emoji": "🎓", "description": "Played 10+ sessions in the club."},
    "pioneer": {"name": "The Pioneer", "emoji": "🌟", "description": "Played in the very first session of the club."}
}

def get_live_game_fish_players(club_code: str) -> set:
    from utils.live_games import load_live_games
    fish_players = set()
    games = load_live_games(club_code)
    for game in games:
        for p in game.get("players", []):
            buyin_txs = [tx for tx in p.get("history", []) if isinstance(tx, dict) and tx.get("type") == "buyin"]
            if len(buyin_txs) >= 3:
                fish_players.add(p["name"])
    return fish_players

def calculate_club_badges(club_code: str) -> dict:
    """
    Returns a dictionary of {player_name: [badge_keys]} representing all badges awarded in the club.
    """
    sessions = load_sessions(club_code)
    fish_players = get_live_game_fish_players(club_code)
    
    # Initialize dictionary for all players who have either played historical sessions or are active in live games
    all_names = set(fish_players)
    player_stats = {}
    
    # Track chronological sequence of sessions
    for session_idx, session in enumerate(sessions):
        players = session.get("players", [])
        for p in players:
            name = p["name"].strip()
            all_names.add(name)
            buyin = float(p.get("buyin", 0))
            result = float(p.get("result", 0))
            
            if name not in player_stats:
                player_stats[name] = {
                    "results": [],
                    "buyins": [],
                    "session_indices": []
                }
            player_stats[name]["results"].append(result)
            player_stats[name]["buyins"].append(buyin)
            player_stats[name]["session_indices"].append(session_idx)
            
    # Award badges dictionary
    badges = {name: [] for name in all_names}
    
    # Award Fish badge
    for name in fish_players:
        if name in badges:
            badges[name].append("fish")
            
    if not player_stats:
        return badges
        
    # Global career statistics trackers
    highest_career_profit = -999999.0
    highest_career_profit_player = None
    highest_single_buyin = -1.0
    highest_single_buyin_player = None
    most_winning_sessions = 0
    most_winning_sessions_player = None
    lowest_avg_buyin = 999999.0
    lowest_avg_buyin_player = None
    
    # Calculate player career statistics
    for name, stats in player_stats.items():
        results = stats["results"]
        buyins = stats["buyins"]
        
        # Scholar
        if len(results) >= 10:
            badges[name].append("scholar")
            
        # Pioneer
        if 0 in stats["session_indices"]:
            badges[name].append("pioneer")
            
        # Wall (min 5 sessions, 0 net losses)
        if len(results) >= 5 and all(r >= 0 for r in results):
            badges[name].append("wall")
            
        # Streak (won 3+ consecutive sessions)
        current_streak = 0
        max_streak = 0
        for r in results:
            if r > 0:
                current_streak += 1
                if current_streak > max_streak:
                    max_streak = current_streak
            else:
                current_streak = 0
        if max_streak >= 3:
            badges[name].append("streak")
            
        # Rollercoaster
        if any(r >= 500 for r in results) and any(r <= -500 for r in results):
            badges[name].append("rollercoaster")
            
        # Survivor (Cashed out within +/- 5% of buy-in)
        for r, b in zip(results, buyins):
            if b > 0 and (abs(r) / b) <= 0.05:
                badges[name].append("survivor")
                break
                
        # High Roller (Avg buyin >= 1000)
        avg_buyin = sum(buyins) / len(buyins) if buyins else 0
        if avg_buyin >= 1000:
            badges[name].append("high_roller")
            
        # Tracker checks
        total_profit = sum(results)
        if len(results) >= 2 and total_profit > highest_career_profit:
            highest_career_profit = total_profit
            highest_career_profit_player = name
            
        max_buyin = max(buyins) if buyins else 0
        if len(results) >= 2 and max_buyin > highest_single_buyin:
            highest_single_buyin = max_buyin
            highest_single_buyin_player = name
            
        winning_sessions_count = sum(1 for r in results if r > 0)
        if winning_sessions_count > most_winning_sessions:
            most_winning_sessions = winning_sessions_count
            most_winning_sessions_player = name
            
        if len(results) >= 3 and avg_buyin < lowest_avg_buyin:
            lowest_avg_buyin = avg_buyin
            lowest_avg_buyin_player = name

    # Award global career badges
    if highest_career_profit_player and highest_career_profit > 0:
        badges[highest_career_profit_player].append("shark")
    if highest_single_buyin_player and highest_single_buyin > 0:
        badges[highest_single_buyin_player].append("whale")
    if most_winning_sessions_player and most_winning_sessions > 0:
        badges[most_winning_sessions_player].append("champion")
    if lowest_avg_buyin_player and lowest_avg_buyin < 999999.0:
        badges[lowest_avg_buyin_player].append("turtle")
        
    return badges
