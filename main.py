from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect

from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

from fastapi.staticfiles import StaticFiles

from fastapi.templating import Jinja2Templates

import os

# Auto-create dynamic database storage folder
os.makedirs(os.getenv("DATA_DIR", "data"), exist_ok=True)

from utils.storage import (
    add_session,
    load_sessions,
    delete_session,
    update_session
)

from utils.analytics import get_analytics

from utils.settlement import (
    calculate_totals,
    calculate_settlements
)
from utils.live_games import (
    create_live_game,
    get_live_game,
    join_live_game,
    add_buyin,
    update_cashout,
    end_live_game,
    get_total_pool,
    get_player,
    get_player_history,
    get_player_by_token,
    load_live_games,
    admin_update_player
)
import uvicorn
import json

app = FastAPI()

# -----------------------------------
# WEBSOCKET MANAGER
# -----------------------------------

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, code: str, websocket: WebSocket):
        await websocket.accept()
        if code not in self.active_connections:
            self.active_connections[code] = []
        self.active_connections[code].append(websocket)

    def disconnect(self, code: str, websocket: WebSocket):
        if code in self.active_connections:
            try:
                self.active_connections[code].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[code]:
                del self.active_connections[code]

    async def broadcast(self, code: str, message: str):
        if code in self.active_connections:
            for connection in list(self.active_connections[code]):
                try:
                    await connection.send_text(message)
                except Exception:
                    # Connection might be closed, clean it up
                    self.disconnect(code, connection)

manager = ConnectionManager()

# -----------------------------------
# STATIC FILES
# -----------------------------------

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)

# -----------------------------------
# PROGRESSIVE WEB APP (PWA) ROUTINGS
# -----------------------------------

@app.get("/manifest.json")
async def manifest_route():
    return FileResponse("static/manifest.json")

@app.get("/sw.js")
async def service_worker_route():
    return FileResponse("static/sw.js", media_type="application/javascript")

# -----------------------------------
# TEMPLATES
# -----------------------------------

templates = Jinja2Templates(
    directory="templates"
)

# -----------------------------------
# DASHBOARD
# -----------------------------------

@app.get(
    "/",
    response_class=HTMLResponse
)

async def home(request: Request):

    sessions = load_sessions()

    analytics = get_analytics(
        sessions
    )

    # Load active live games
    live_games = load_live_games()
    active_live_games = []
    for g in live_games:
        if g.get("status", "active") == "active":
            active_live_games.append({
                "code": g["code"],
                "name": g["name"],
                "player_count": len(g.get("players", [])),
                "pool": get_total_pool(g)
            })

    return templates.TemplateResponse(

        request=request,

        name="index.html",

        context={

            **analytics,

            "active_page":
                "dashboard",

            "active_live_games":
                active_live_games

        }

    )

# -----------------------------------
# ADD SESSION PAGE
# -----------------------------------

@app.get(
    "/add-session",
    response_class=HTMLResponse
)
async def add_session_page(request: Request):

    sessions = load_sessions()

    names = set()

    for session in sessions:

        for player in session.get(
            "players",
            []
        ):

            name = player.get(
                "name",
                ""
            ).strip()

            if name:
                names.add(name)

    return templates.TemplateResponse(

        request=request,

        name="add_session.html",

        context={

            "active_page":
                "add-session",

            "player_names":
                sorted(list(names))

        }

    )

    return templates.TemplateResponse(

        request=request,

        name="add_session.html",

        context={

            "active_page":
                "add-session"

        }

    )

# -----------------------------------
# SAVE SESSION
# -----------------------------------

@app.post("/save-session")

async def save_session(

    session_name: str = Form(...),
    session_date: str = Form(...),
    players_json: str = Form(...)

):

    players = json.loads(
        players_json
    )

    session_data = {

        "session_name":
            session_name,

        "session_date":
            session_date,

        "players":
            players

    }

    add_session(
        session_data
    )

    return RedirectResponse(

        url="/history",

        status_code=303

    )
# -----------------------------------
# UPDATE SESSION
# -----------------------------------

@app.post(
    "/update-session/{index}"
)

async def update_session_route(

    index: int,

    session_name: str = Form(...),
    session_date: str = Form(...),
    players_json: str = Form(...)

):

    sessions = load_sessions()

    if index >= len(sessions):

        return RedirectResponse(
            url="/history",
            status_code=303
        )

    players = json.loads(
        players_json
    )

    updated_session = {

        "session_name":
            session_name,

        "session_date":
            session_date,

        "players":
            players

    }

    update_session(

        sessions,

        index,

        updated_session

    )

    return RedirectResponse(

        url="/history",

        status_code=303

    )
# -----------------------------------
# DUPLICATE SESSION
# -----------------------------------

@app.post(
    "/duplicate-session/{index}"
)

async def duplicate_session_route(
    index: int
):

    sessions = load_sessions()

    if index >= len(sessions):

        return RedirectResponse(

            url="/history",

            status_code=303

        )

    original = sessions[index]

    duplicated_players = []

    for player in original["players"]:

        duplicated_players.append({

            "name":
                player["name"],

            "buyin":
                player["buyin"],

            "result":
                0

        })

    from datetime import date

    duplicated_session = {

        "session_name":
            f"{original['session_name']} Copy",

        "session_date":
            date.today().isoformat(),

        "players":
            duplicated_players

    }

    add_session(
    duplicated_session
)

    sessions = load_sessions()

    new_index = len(sessions) - 1

    return RedirectResponse(

        url=f"/edit-session/{new_index}",

     status_code=303

)
# -----------------------------------
# HISTORY PAGE
# -----------------------------------

@app.get(
    "/history",
    response_class=HTMLResponse
)

async def history_page(request: Request):

    sessions = load_sessions()

    return templates.TemplateResponse(

        request=request,

        name="history.html",

        context={

            "sessions":
                sessions,

            "active_page":
                "history"

        }

    )
# -----------------------------------
# EDIT SESSION PAGE
# -----------------------------------

@app.get(
    "/edit-session/{index}",
    response_class=HTMLResponse
)

async def edit_session_page(
    request: Request,
    index: int
):

    sessions = load_sessions()

    if index >= len(sessions):

        return RedirectResponse(
            url="/history",
            status_code=303
        )

    session = sessions[index]

    names = set()

    for s in sessions:

        for player in s.get(
            "players",
            []
        ):

            name = player.get(
                "name",
                ""
            ).strip()

            if name:

                names.add(name)

    return templates.TemplateResponse(

        request=request,

        name="edit_session.html",

        context={

            "session":
                session,

            "session_index":
                index,

            "player_names":
                sorted(list(names)),

            "active_page":
                "history"

        }

    )
# -----------------------------------
# DELETE SESSION
# -----------------------------------

@app.post("/delete-session/{index}")

async def remove_session(index: int):

    sessions = load_sessions()

    delete_session(
        sessions,
        index
    )

    return RedirectResponse(

        url="/history",

        status_code=303

    )

# -----------------------------------
# SETTLEMENT PAGE
# -----------------------------------

@app.get(
    "/settlement",
    response_class=HTMLResponse
)

async def settlement_page(request: Request):

    sessions = load_sessions()

    totals = calculate_totals(
        sessions
    )

    settlements = calculate_settlements(
        totals
    )

    return templates.TemplateResponse(

        request=request,

        name="settlement.html",

        context={

            "settlements":
                settlements,

            "totals":
                totals,

            "active_page":
                "settlement"

        }

    )

# -----------------------------------
# TOTALS PAGE
# -----------------------------------

@app.get(
    "/totals",
    response_class=HTMLResponse
)

async def totals_page(request: Request):

    sessions = load_sessions()

    totals = calculate_totals(
        sessions
    )

    sorted_totals = sorted(

        totals.items(),

        key=lambda x: x[1],

        reverse=True

    )

    return templates.TemplateResponse(

        request=request,

        name="totals.html",

        context={

            "totals":
                sorted_totals,

            "active_page":
                "totals"

        }

    )


# -----------------------------------
# PLAYER PROFILE PAGE
# -----------------------------------

@app.get(
    "/player/{name}",
    response_class=HTMLResponse
)
async def player_profile_page(request: Request, name: str):
    sessions = load_sessions()
    
    sessions_played = 0
    total_profit = 0.0
    total_loss = 0.0
    largest_win = 0.0
    largest_loss = 0.0
    
    history = []
    
    for session in sessions:
        for player in session.get("players", []):
            if player["name"].strip().lower() == name.strip().lower():
                sessions_played += 1
                result = float(player["result"])
                
                if result > 0:
                    total_profit += result
                    if result > largest_win:
                        largest_win = result
                elif result < 0:
                    total_loss += abs(result)
                    if abs(result) > largest_loss:
                        largest_loss = abs(result)
                
                history.append({
                    "session_name": session["session_name"],
                    "session_date": session["session_date"],
                    "result": result
                })
                break
                
    total_net = total_profit - total_loss
    average_result = (total_net / sessions_played) if sessions_played > 0 else 0.0
    
    return templates.TemplateResponse(
        request=request,
        name="player_profile.html",
        context={
            "name": name,
            "sessions_played": sessions_played,
            "total_profit": round(total_profit, 2),
            "total_loss": round(total_loss, 2),
            "total_net": round(total_net, 2),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "average_result": round(average_result, 2),
            "history": sorted(history, key=lambda x: x["session_date"], reverse=True),
            "active_page": "totals"
        }
    )


# -----------------------------------
# USAGE ANALYTICS PAGE
# -----------------------------------

@app.get(
    "/analytics",
    response_class=HTMLResponse
)
async def usage_analytics_page(request: Request):
    sessions = load_sessions()
    live_games = load_live_games()
    
    total_sessions = len(sessions)
    total_live_games = len(live_games)
    
    player_activity = {}
    
    # 1. Tally from archived manual sessions
    for session in sessions:
        for player in session.get("players", []):
            name = player.get("name", "").strip()
            if name:
                player_activity[name] = player_activity.get(name, 0) + 1
                
    # 2. Tally from active/ended live sessions
    for game in live_games:
        for player in game.get("players", []):
            name = player.get("name", "").strip()
            if name:
                player_activity[name] = player_activity.get(name, 0) + 1
                
    # Rank players by total games played
    sorted_active_players = sorted(
        player_activity.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context={
            "total_sessions": total_sessions,
            "total_live_games": total_live_games,
            "active_players": sorted_active_players[:10],
            "active_page": "analytics"
        }
    )




# -----------------------------------
# LIVE SESSION PAGE
# -----------------------------------

@app.get(
    "/live",
    response_class=HTMLResponse
)

async def live_page(
    request: Request
):

    return templates.TemplateResponse(

        request=request,

        name="live.html",

        context={

            "active_page":
                "live"

        }

    )

# -----------------------------------
# CREATE LIVE GAME
# -----------------------------------

@app.post(
    "/create-live-game"
)

async def create_live_game_route(

    game_name: str = Form(...)

):

    game = create_live_game(
        game_name
    )

    return RedirectResponse(

        url=f"/live-game/{game['code']}",

        status_code=303

    )

@app.get(
    "/live-game/{code}",
    response_class=HTMLResponse
)
async def live_game_page(

    request: Request,

    code: str

):

    game = get_live_game(
        code
    )

    if not game:

        return HTMLResponse(

            "<h1>Game Not Found</h1>",

            status_code=404

        )

    # Compute player profits for settlement
    player_results = []
    totals = {}
    for p in game.get("players", []):
        net = float(p.get("cashout", 0) - p["buyin"])
        totals[p["name"]] = net
        player_results.append({
            "name": p["name"],
            "buyin": p["buyin"],
            "cashout": p.get("cashout", 0),
            "result": net
        })

    settlements = calculate_settlements(totals)

    host_player_name = request.cookies.get(f"host_player_name_{code}")

    return templates.TemplateResponse(

        request=request,

        name="live_game.html",

        context={

            "game": game,

            "pool":
                get_total_pool(
                    game
                ),

            "player_results": player_results,

            "settlements": settlements,

            "host_player_name": host_player_name

        }

    )

@app.get(
    "/live-player/{code}/{player_name}",
    response_class=HTMLResponse
)
async def live_player_page(

    request: Request,

    code: str,

    player_name: str

):

    player = get_player(

        code,

        player_name

    )

    if not player:

        return HTMLResponse(

            "<h1>Player Not Found</h1>",

            status_code=404

        )

    return templates.TemplateResponse(

        request=request,

        name="live_player.html",

        context={

            "code": code,

            "player": player,

            "history":
                get_player_history(
                        code,
                        player_name
                )

        }

    )

@app.get(
    "/join",
    response_class=HTMLResponse
)
async def join_page(
    request: Request,
    code: str = ""
):

    return templates.TemplateResponse(

        request=request,

        name="join.html",

        context={
            "code": code.upper(),
            "hide_sidebar": True
        }

    )


@app.post(
    "/join-game"
)
async def join_game_route(

    player_name: str = Form(...),

    game_code: str = Form(...)

):

    code_upper = game_code.upper()

    join_live_game(

        code_upper,

        player_name

    )

    await manager.broadcast(code_upper, "update")

    player = get_player(code_upper, player_name)

    if player:

        return RedirectResponse(

            url=f"/secure-player/{code_upper}/{player['token']}",

            status_code=303

        )

    return RedirectResponse(

        url=f"/live-game/{code_upper}",

        status_code=303

    )

@app.post(
    "/add-buyin"
)
async def add_buyin_route(

    code: str = Form(...),

    player_name: str = Form(...),

    amount: int = Form(...)

):

    add_buyin(

        code,

        player_name,

        amount

    )

    await manager.broadcast(code, "update")

    return RedirectResponse(

        url=f"/live-game/{code}",

        status_code=303

    )

@app.get(
    "/secure-player/{code}/{token}",
    response_class=HTMLResponse
)
async def secure_player_page(

    request: Request,

    code: str,

    token: str

):

    player = get_player_by_token(

        code,

        token

    )

    if not player:

        return HTMLResponse(

            "<h1>Player Not Found</h1>",

            status_code=404

        )

    game = get_live_game(code)
    game_status = game.get("status", "active") if game else "active"

    return templates.TemplateResponse(

        request=request,

        name="live_player.html",

        context={

            "code": code,

            "player": player,

            "game": game,

            "game_status": game_status,

            "hide_sidebar": True,

            "history":
                player.get(
                    "history",
                    []
                )

        }

    )

# -----------------------------------
# LIVE GAME ENDPOINTS
# -----------------------------------

@app.post(
    "/update-cashout"
)
async def update_cashout_route(
    code: str = Form(...),
    player_name: str = Form(...),
    amount: int = Form(...)
):
    update_cashout(
        code,
        player_name,
        amount
    )
    await manager.broadcast(code, "update")
    
    player = get_player(code, player_name)
    if player:
        return RedirectResponse(
            url=f"/secure-player/{code}/{player['token']}",
            status_code=303
        )
    return RedirectResponse(
        url=f"/live-game/{code}",
        status_code=303
    )

@app.post(
    "/host-join"
)
async def host_join_route(
    code: str = Form(...),
    player_name: str = Form(...)
):
    code_upper = code.upper()
    join_live_game(code_upper, player_name)
    await manager.broadcast(code_upper, "update")
    
    response = RedirectResponse(
        url=f"/live-game/{code_upper}",
        status_code=303
    )
    response.set_cookie(
        key=f"host_player_name_{code_upper}",
        value=player_name,
        max_age=86400
    )
    return response

@app.post(
    "/admin/update-player"
)
async def admin_update_player_route(
    code: str = Form(...),
    player_name: str = Form(...),
    buyin: int = Form(...),
    cashout: int = Form(...)
):
    admin_update_player(code, player_name, buyin, cashout)
    await manager.broadcast(code, "update")
    return RedirectResponse(
        url=f"/live-game/{code}",
        status_code=303
    )

@app.post(
    "/end-game/{code}"
)
async def end_game_route(
    code: str
):
    game = get_live_game(code)
    if not game:
        return RedirectResponse(url="/live", status_code=303)

    total_buyin = sum(p["buyin"] for p in game.get("players", []))
    total_cashout = sum(p.get("cashout", 0) for p in game.get("players", []))

    if total_buyin != total_cashout:
        return RedirectResponse(
            url=f"/live-game/{code}?error=unbalanced",
            status_code=303
        )

    end_live_game(code)
    await manager.broadcast(code, "update")
    return RedirectResponse(
        url=f"/live-game/{code}",
        status_code=303
    )

@app.websocket("/ws/live-game/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str):
    await manager.connect(code, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(code, websocket)
    except Exception:
        manager.disconnect(code, websocket)

# -----------------------------------
# RUN SERVER
# -----------------------------------

if __name__ == "__main__":

    uvicorn.run(

        "main:app",

        host="0.0.0.0",

        port=8000,

        reload=True

    )
