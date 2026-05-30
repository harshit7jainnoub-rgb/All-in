from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import json
from datetime import datetime, date
import uvicorn
import random
import string

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
    admin_update_player,
    kick_player_from_live_game,
    add_buyin_request,
    resolve_buyin_request
)
from utils.badges import calculate_club_badges, BADGES_DEFINITION
from utils.club import (
    create_club as init_club_metadata,
    load_club_config,
    verify_host_pin,
    kick_player_from_club,
    is_player_kicked,
    get_club_profiles
)
from utils.profile import (
    create_profile,
    authenticate_profile,
    get_profile_by_token,
    add_club_to_profile,
    add_created_club_to_profile,
    get_profile_by_phone,
    load_profiles,
    is_phone_taken,
    update_profile_pin,
    verify_recovery_details
)


app = FastAPI()

# -----------------------------------
# WEBSOCKET MANAGER
# -----------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, room_key: str, websocket: WebSocket):
        await websocket.accept()
        if room_key not in self.active_connections:
            self.active_connections[room_key] = []
        self.active_connections[room_key].append(websocket)

    def disconnect(self, room_key: str, websocket: WebSocket):
        if room_key in self.active_connections:
            try:
                self.active_connections[room_key].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[room_key]:
                del self.active_connections[room_key]

    async def broadcast(self, room_key: str, message: str):
        if room_key in self.active_connections:
            for connection in list(self.active_connections[room_key]):
                try:
                    await connection.send_text(message)
                except Exception:
                    self.disconnect(room_key, connection)

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
templates = Jinja2Templates(directory="templates")

# -----------------------------------
# GLOBAL CONTEXT & CLUB CONTEXT HELPERS
# -----------------------------------
def get_global_player(request: Request):
    token = request.cookies.get("player_profile_token")
    if not token:
        return None
    return get_profile_by_token(token)

def get_club_context(club_code: str, request: Request):
    club_code_upper = club_code.upper()
    config = load_club_config(club_code_upper)
    if not config:
        return None
        
    # Get global player profile
    player = get_global_player(request)
    if not player:
        return None
        
    # Verify if player is kicked/banned from this club
    if is_player_kicked(club_code_upper, player["name"]):
        return {"banned": True, "club_code": club_code_upper, "club_name": config.get("club_name")}
        
    # Check host admin cookie
    admin_token = request.cookies.get(f"club_{club_code_upper}_admin_token")
    is_admin = (admin_token == config.get("host_pin"))
    
    return {
        "club_code": club_code_upper,
        "club_name": config.get("club_name", "Poker Club"),
        "is_admin": is_admin,
        "logged_in_player": player,
        "banned": False
    }

# -----------------------------------
# GLOBAL PLAYER PROFILE AUTH & OTP
# -----------------------------------
@app.get("/", response_class=HTMLResponse)
async def root_player_onboarding(request: Request, success: str = "", error: str = ""):
    player = get_global_player(request)
    if player:
        return RedirectResponse(url="/hub", status_code=303)
        
    return templates.TemplateResponse(
        request=request,
        name="global_onboarding.html",
        context={
            "success_msg": success,
            "error_msg": error
        }
    )

@app.post("/profile/login")
async def profile_login_action(
    request: Request,
    player_name: str = Form(...),
    player_pin: str = Form(...)
):
    profile = authenticate_profile(player_name, player_pin)
    if profile:
        response = RedirectResponse(url="/hub", status_code=303)
        response.set_cookie(
            key="player_profile_token",
            value=profile["token"],
            max_age=31536000 # 1 year persistence
        )
        return response
    else:
        return templates.TemplateResponse(
            request=request,
            name="global_onboarding.html",
            context={
                "error": "Invalid player name or PIN. Please try again.",
                "active_tab": "login"
            }
        )

@app.post("/profile/register")
async def profile_register_action(
    request: Request,
    player_name: str = Form(...),
    player_phone: str = Form(...),
    player_dob: str = Form(...),
    player_pin: str = Form(...)
):
    # Verify uniqueness of name and phone first
    profiles = load_profiles()
    norm_name = player_name.strip()
    norm_phone = player_phone.strip()
    norm_dob = player_dob.strip()
    
    if norm_name in profiles:
        return templates.TemplateResponse(
            request=request,
            name="global_onboarding.html",
            context={
                "error": f"The player name '{player_name}' is already taken. Please choose another."
            }
        )
    if is_phone_taken(norm_phone):
        return templates.TemplateResponse(
            request=request,
            name="global_onboarding.html",
            context={
                "error": f"The phone number '{player_phone}' is already registered to another profile."
            }
        )
        
    profile = create_profile(norm_name, norm_phone, norm_dob, player_pin)
    if not profile:
        return templates.TemplateResponse(
            request=request,
            name="global_onboarding.html",
            context={
                "error": "Failed to create profile. Please try again."
            }
        )
        
    response = RedirectResponse(url="/hub", status_code=303)
    response.set_cookie(
        key="player_profile_token",
        value=profile["token"],
        max_age=31536000
    )
    return response

@app.post("/profile/recovery")
async def profile_recovery_action(
    request: Request,
    player_phone: str = Form(...),
    player_dob: str = Form(...),
    new_pin: str = Form(...)
):
    norm_phone = player_phone.strip()
    norm_dob = player_dob.strip()
    
    profile = verify_recovery_details(norm_phone, norm_dob)
    if not profile:
        return templates.TemplateResponse(
            request=request,
            name="global_onboarding.html",
            context={
                "error": "Recovery failed: Phone number and Date of Birth do not match.",
                "active_tab": "forgot"
            }
        )
        
    update_profile_pin(profile["name"], new_pin)
    
    # Authenticate profile to get token
    profile = authenticate_profile(profile["name"], new_pin)
    if not profile:
        return templates.TemplateResponse(
            request=request,
            name="global_onboarding.html",
            context={
                "error": "Authentication failed. Please try again.",
                "active_tab": "forgot"
            }
        )
        
    response = RedirectResponse(url="/hub", status_code=303)
    response.set_cookie(
        key="player_profile_token",
        value=profile["token"],
        max_age=31536000
    )
    return response

@app.get("/profile/logout")
async def profile_logout_action():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="player_profile_token")
    return response

# Compatibility fallback routes for cached old browser pages
@app.post("/profile/register-otp")
@app.post("/profile/verify-register")
@app.post("/profile/login-otp")
@app.post("/profile/verify-login")
@app.post("/profile/verify-firebase")
async def compatibility_fallback_redirect():
    return HTMLResponse(
        content="""
        <div style="background:#0a0705;color:#f5f5f4;font-family:sans-serif;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:20px;box-sizing:border-box;">
            <div style="border:1px solid rgba(212,160,23,0.2);padding:40px;border-radius:24px;background:rgba(20,16,12,0.8);max-width:400px;box-shadow:0 20px 40px rgba(0,0,0,0.8);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);">
                <h2 style="color:#d4a017;margin-top:0;font-size:22px;letter-spacing:1px;">🔄 Refresh Required</h2>
                <p style="font-size:14px;color:#a8a29e;line-height:1.6;margin-bottom:16px;">The platform onboarding has been simplified and upgraded to a frictionless Phone & DOB combo!</p>
                <p style="font-size:14px;color:#a8a29e;line-height:1.6;margin-bottom:30px;">Your browser is displaying a cached version of the registration form.</p>
                <a href="/" style="background:linear-gradient(to right, #d4a017, #ffcc33);color:#0a0705;text-decoration:none;font-weight:black;padding:14px 30px;border-radius:12px;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;display:inline-block;box-shadow:0 4px 15px rgba(212,160,23,0.2);font-weight:bold;">
                    Reload Registration
                </a>
            </div>
        </div>
        """,
        status_code=200
    )

# -----------------------------------
# GLOBAL CLUB SELECTOR PORTAL (/HUB)
# -----------------------------------
@app.get("/hub", response_class=HTMLResponse)
async def club_portal(request: Request, success: str = "", error: str = ""):
    player = get_global_player(request)
    if not player:
        return RedirectResponse(url="/", status_code=303)
        
    active_clubs = []
    for code in player.get("clubs", []):
        config = load_club_config(code)
        if config:
            active_clubs.append({
                "code": code.upper(),
                "name": config.get("club_name", "Poker Club")
            })
            
    return templates.TemplateResponse(
        request=request,
        name="club_portal.html",
        context={
            "player": player,
            "active_clubs": active_clubs,
            "success_msg": success,
            "error_msg": error
        }
    )

@app.post("/hub/enter-club")
async def portal_enter_club_action(
    request: Request,
    club_code: str = Form(...)
):
    player = get_global_player(request)
    if not player:
        return RedirectResponse(url="/", status_code=303)
        
    code_upper = club_code.strip().upper()
    config = load_club_config(code_upper)
    if not config:
        # Build active clubs list for reload
        active_clubs = []
        for c in player.get("clubs", []):
            cfg = load_club_config(c)
            if cfg:
                active_clubs.append({"code": c.upper(), "name": cfg.get("club_name")})
                
        return templates.TemplateResponse(
            request=request,
            name="club_portal.html",
            context={
                "player": player,
                "active_clubs": active_clubs,
                "error": f"Club Code '{code_upper}' not found. Please verify with your host."
            }
        )
        
    if "profiles" not in config:
        config["profiles"] = {}
    if player["name"] not in config["profiles"]:
        config["profiles"][player["name"]] = {
            "name": player["name"],
            "pin": player["pin"],
            "token": player["token"],
            "status": "active"
        }
        from utils.club import save_club_config
        save_club_config(code_upper, config)
        
    add_club_to_profile(player["name"], code_upper)
    
    response = RedirectResponse(url=f"/club/{code_upper}/", status_code=303)
    response.set_cookie(key="last_club_code", value=code_upper, max_age=31536000)
    return response

@app.post("/hub/create-club")
async def portal_create_club_action(
    request: Request,
    club_name: str = Form(...),
    club_code: str = Form(""),
    host_pin: str = Form(...)
):
    player = get_global_player(request)
    if not player:
        return RedirectResponse(url="/", status_code=303)
        
    # CLUB LIMITATION AUDIT: A player profile can create a maximum of 3 clubs
    created_count = len(player.get("created_clubs", []))
    if created_count >= 3:
        active_clubs = []
        for c in player.get("clubs", []):
            cfg = load_club_config(c)
            if cfg:
                active_clubs.append({"code": c.upper(), "name": cfg.get("club_name")})
        return templates.TemplateResponse(
            request=request,
            name="club_portal.html",
            context={
                "player": player,
                "active_clubs": active_clubs,
                "error": "Hosted Club Limit Reached: You can create a maximum of 3 clubs. However, you can still join any number of existing clubs!"
            }
        )
        
    if club_code.strip():
        code_upper = club_code.strip().upper()
        if not code_upper.isalnum():
            active_clubs = []
            for c in player.get("clubs", []):
                cfg = load_club_config(c)
                if cfg:
                    active_clubs.append({"code": c.upper(), "name": cfg.get("club_name")})
            return templates.TemplateResponse(
                request=request,
                name="club_portal.html",
                context={
                    "player": player,
                    "active_clubs": active_clubs,
                    "error": "Club code must contain alphanumeric characters only."
                }
            )
        if load_club_config(code_upper):
            active_clubs = []
            for c in player.get("clubs", []):
                cfg = load_club_config(c)
                if cfg:
                    active_clubs.append({"code": c.upper(), "name": cfg.get("club_name")})
            return templates.TemplateResponse(
                request=request,
                name="club_portal.html",
                context={
                    "player": player,
                    "active_clubs": active_clubs,
                    "error": f"Club Code '{code_upper}' is already taken. Please choose another."
                }
            )
    else:
        while True:
            code_upper = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
            if not load_club_config(code_upper):
                break
                
    init_club_metadata(code_upper, club_name, host_pin)
    
    config = load_club_config(code_upper)
    config["profiles"][player["name"]] = {
        "name": player["name"],
        "pin": player["pin"],
        "token": player["token"],
        "status": "active"
    }
    from utils.club import save_club_config
    save_club_config(code_upper, config)
    
    # Save the created club to their profile list (tracks creation limit)
    add_created_club_to_profile(player["name"], code_upper)
    
    response = RedirectResponse(url=f"/club/{code_upper}/", status_code=303)
    response.set_cookie(key="last_club_code", value=code_upper, max_age=31536000)
    response.set_cookie(key=f"club_{code_upper}_admin_token", value=host_pin, max_age=86400)
    return response

# -----------------------------------
# HOST AUTHENTICATION ROUTES
# -----------------------------------
@app.get("/club/{club_code}/verify-host", response_class=HTMLResponse)
async def verify_host_page(request: Request, club_code: str, next: str = ""):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    return templates.TemplateResponse(
        request=request,
        name="host_verify.html",
        context={
            **context,
            "next_url": next
        }
    )

@app.post("/club/{club_code}/verify-host")
async def verify_host_action(
    request: Request,
    club_code: str,
    host_pin: str = Form(...),
    next_url: str = Form("")
):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    if verify_host_pin(club_code, host_pin):
        response = RedirectResponse(
            url=next_url if next_url.strip() else f"/club/{club_code}/",
            status_code=303
        )
        response.set_cookie(
            key=f"club_{club_code.upper()}_admin_token",
            value=host_pin,
            max_age=86400
        )
        return response
    else:
        return templates.TemplateResponse(
            request=request,
            name="host_verify.html",
            context={
                **context,
                "error": "Invalid Host Admin PIN. Please try again.",
                "next_url": next_url
            }
        )

@app.get("/club/{club_code}/logout-host")
async def logout_host_route(club_code: str):
    response = RedirectResponse(url=f"/club/{club_code}/", status_code=303)
    response.delete_cookie(key=f"club_{club_code.upper()}_admin_token")
    return response

# -----------------------------------
# CLUB ROSTER ADMIN CONTROL
# -----------------------------------
@app.get("/club/{club_code}/admin-panel", response_class=HTMLResponse)
async def club_admin_panel(request: Request, club_code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
    if not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host?next=/club/{club_code}/admin-panel", status_code=303)
        
    profiles = get_club_profiles(club_code)
    return templates.TemplateResponse(
        request=request,
        name="admin_panel.html",
        context={
            **context,
            "profiles": profiles
        }
    )

@app.post("/club/{club_code}/kick-player")
async def host_kick_player_action(
    request: Request,
    club_code: str,
    player_name: str = Form(...)
):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
    if not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
        
    kick_player_from_club(club_code, player_name)
    
    live_games = load_live_games(club_code)
    for game in live_games:
        if game.get("status", "active") == "active":
            game_code = game["code"]
            kicked = kick_player_from_live_game(club_code, game_code, player_name)
            if kicked:
                await manager.broadcast(f"{club_code.upper()}_{game_code}", "update")
                
    profiles = get_club_profiles(club_code)
    return templates.TemplateResponse(
        request=request,
        name="admin_panel.html",
        context={
            **context,
            "profiles": profiles,
            "message": f"Successfully kicked '{player_name}' and banned them from all active tables."
        }
    )

# -----------------------------------
# CLUB DASHBOARD
# -----------------------------------
@app.get("/club/{club_code}/", response_class=HTMLResponse)
async def club_home(request: Request, club_code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
    analytics = get_analytics(sessions)
    
    live_games = load_live_games(club_code)
    active_live_games = []
    for g in live_games:
        if g.get("status", "active") == "active":
            active_live_games.append({
                "code": g["code"],
                "name": g["name"],
                "player_count": len(g.get("players", [])),
                "pool": get_total_pool(g)
            })
            
    player_hub_stats = None
    player = context["logged_in_player"]
    if player:
        name = player["name"]
        sessions_played = 0
        total_profit = 0.0
        total_loss = 0.0
        largest_win = 0.0
        largest_loss = 0.0
        history = []
        
        for session in sessions:
            for p in session.get("players", []):
                if p["name"].strip().lower() == name.strip().lower():
                    sessions_played += 1
                    result = float(p["result"])
                    
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
        
        player_hub_stats = {
            "sessions_played": sessions_played,
            "total_profit": round(total_profit, 2),
            "total_loss": round(total_loss, 2),
            "total_net": round(total_net, 2),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "average_result": round(average_result, 2),
            "history": sorted(history, key=lambda x: x["session_date"], reverse=True)[:5]
        }
        
    club_badges = calculate_club_badges(club_code)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **analytics,
            **context,
            "active_page": "dashboard",
            "active_live_games": active_live_games,
            "player_hub_stats": player_hub_stats,
            "club_badges": club_badges,
            "badges_definition": BADGES_DEFINITION
        }
    )

# -----------------------------------
# ADD SESSION PAGE
# -----------------------------------
@app.get("/club/{club_code}/add-session", response_class=HTMLResponse)
async def add_session_page(request: Request, club_code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
    if not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host?next=/club/{club_code}/add-session", status_code=303)
        
    sessions = load_sessions(club_code)
    names = set()
    for session in sessions:
        for player in session.get("players", []):
            name = player.get("name", "").strip()
            if name:
                names.add(name)
                
    return templates.TemplateResponse(
        request=request,
        name="add_session.html",
        context={
            **context,
            "active_page": "add-session",
            "player_names": sorted(list(names))
        }
    )

# -----------------------------------
# SAVE SESSION
# -----------------------------------
@app.post("/club/{club_code}/save-session")
async def save_session_route(
    request: Request,
    club_code: str,
    session_name: str = Form(...),
    session_date: str = Form(...),
    players_json: str = Form(...)
):
    context = get_club_context(club_code, request)
    if not context or not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    players = json.loads(players_json)
    session_data = {
        "session_name": session_name,
        "session_date": session_date,
        "players": players
    }
    
    add_session(club_code, session_data)
    
    return RedirectResponse(
        url=f"/club/{club_code}/history",
        status_code=303
    )

# -----------------------------------
# UPDATE SESSION
# -----------------------------------
@app.post("/club/{club_code}/update-session/{index}")
async def update_session_route_action(
    request: Request,
    club_code: str,
    index: int,
    session_name: str = Form(...),
    session_date: str = Form(...),
    players_json: str = Form(...)
):
    context = get_club_context(club_code, request)
    if not context or not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
    if index >= len(sessions):
        return RedirectResponse(url=f"/club/{club_code}/history", status_code=303)
        
    players = json.loads(players_json)
    updated_session = {
        "session_name": session_name,
        "session_date": session_date,
        "players": players
    }
    
    update_session(club_code, sessions, index, updated_session)
    
    return RedirectResponse(
        url=f"/club/{club_code}/history",
        status_code=303
    )

# -----------------------------------
# DUPLICATE SESSION
# -----------------------------------
@app.post("/club/{club_code}/duplicate-session/{index}")
async def duplicate_session_route_action(
    request: Request,
    club_code: str,
    index: int
):
    context = get_club_context(club_code, request)
    if not context or not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
    if index >= len(sessions):
        return RedirectResponse(url=f"/club/{club_code}/history", status_code=303)
        
    original = sessions[index]
    duplicated_players = []
    for player in original["players"]:
        duplicated_players.append({
            "name": player["name"],
            "buyin": player["buyin"],
            "result": 0
        })
        
    duplicated_session = {
        "session_name": f"{original['session_name']} Copy",
        "session_date": date.today().isoformat(),
        "players": duplicated_players
    }
    
    add_session(club_code, duplicated_session)
    sessions = load_sessions(club_code)
    new_index = len(sessions) - 1
    
    return RedirectResponse(
        url=f"/club/{club_code}/edit-session/{new_index}",
        status_code=303
    )

# -----------------------------------
# HISTORY PAGE
# -----------------------------------
@app.get("/club/{club_code}/history", response_class=HTMLResponse)
async def history_page(request: Request, club_code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            **context,
            "sessions": sessions,
            "active_page": "history"
        }
    )

# -----------------------------------
# EDIT SESSION PAGE
# -----------------------------------
@app.get("/club/{club_code}/edit-session/{index}", response_class=HTMLResponse)
async def edit_session_page(request: Request, club_code: str, index: int):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
    if not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host?next=/club/{club_code}/edit-session/{index}", status_code=303)
        
    sessions = load_sessions(club_code)
    if index >= len(sessions):
        return RedirectResponse(url=f"/club/{club_code}/history", status_code=303)
        
    session = sessions[index]
    names = set()
    for s in sessions:
        for player in s.get("players", []):
            name = player.get("name", "").strip()
            if name:
                names.add(name)
                
    return templates.TemplateResponse(
        request=request,
        name="edit_session.html",
        context={
            **context,
            "session": session,
            "session_index": index,
            "player_names": sorted(list(names)),
            "active_page": "history"
        }
    )

# -----------------------------------
# DELETE SESSION
# -----------------------------------
@app.post("/club/{club_code}/delete-session/{index}")
async def remove_session(request: Request, club_code: str, index: int):
    context = get_club_context(club_code, request)
    if not context or not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
    delete_session(club_code, sessions, index)
    
    return RedirectResponse(
        url=f"/club/{club_code}/history",
        status_code=303
    )

# -----------------------------------
# SETTLEMENT PAGE
# -----------------------------------
@app.get("/club/{club_code}/settlement", response_class=HTMLResponse)
async def settlement_page(request: Request, club_code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
    totals = calculate_totals(sessions)
    settlements = calculate_settlements(totals)
    
    return templates.TemplateResponse(
        request=request,
        name="settlement.html",
        context={
            **context,
            "settlements": settlements,
            "totals": totals,
            "active_page": "settlement"
        }
    )

# -----------------------------------
# TOTALS PAGE
# -----------------------------------
@app.get("/club/{club_code}/totals", response_class=HTMLResponse)
async def totals_page(request: Request, club_code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
    totals = calculate_totals(sessions)
    sorted_totals = sorted(
        totals.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    club_badges = calculate_club_badges(club_code)
    return templates.TemplateResponse(
        request=request,
        name="totals.html",
        context={
            **context,
            "totals": sorted_totals,
            "active_page": "totals",
            "club_badges": club_badges,
            "badges_definition": BADGES_DEFINITION
        }
    )

# -----------------------------------
# PLAYER PROFILE DETAILS
# -----------------------------------
@app.get("/club/{club_code}/player/{name}", response_class=HTMLResponse)
async def player_profile_page(request: Request, club_code: str, name: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
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
    
    club_badges = calculate_club_badges(club_code)
    return templates.TemplateResponse(
        request=request,
        name="player_profile.html",
        context={
            **context,
            "name": name,
            "sessions_played": sessions_played,
            "total_profit": round(total_profit, 2),
            "total_loss": round(total_loss, 2),
            "total_net": round(total_net, 2),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "average_result": round(average_result, 2),
            "history": sorted(history, key=lambda x: x["session_date"], reverse=True),
            "active_page": "totals",
            "club_badges": club_badges,
            "badges_definition": BADGES_DEFINITION
        }
    )

# -----------------------------------
# USAGE ANALYTICS PAGE
# -----------------------------------
@app.get("/club/{club_code}/analytics", response_class=HTMLResponse)
async def usage_analytics_page(request: Request, club_code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    sessions = load_sessions(club_code)
    live_games = load_live_games(club_code)
    
    total_sessions = len(sessions)
    total_live_games = len(live_games)
    
    player_activity = {}
    for session in sessions:
        for player in session.get("players", []):
            name = player.get("name", "").strip()
            if name:
                player_activity[name] = player_activity.get(name, 0) + 1
                
    for game in live_games:
        for player in game.get("players", []):
            name = player.get("name", "").strip()
            if name:
                player_activity[name] = player_activity.get(name, 0) + 1
                
    sorted_active_players = sorted(
        player_activity.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context={
            **context,
            "total_sessions": total_sessions,
            "total_live_games": total_live_games,
            "active_players": sorted_active_players[:10],
            "active_page": "analytics"
        }
    )

# -----------------------------------
# LIVE TABLES LOBBY HUB
# -----------------------------------
@app.get("/club/{club_code}/live", response_class=HTMLResponse)
async def live_page(request: Request, club_code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    return templates.TemplateResponse(
        request=request,
        name="live.html",
        context={
            **context,
            "active_page": "live"
        }
    )

# -----------------------------------
# CREATE LIVE GAME
# -----------------------------------
@app.post("/club/{club_code}/create-live-game")
async def create_live_game_route(
    request: Request,
    club_code: str,
    game_name: str = Form(...)
):
    context = get_club_context(club_code, request)
    if not context or not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    game = create_live_game(club_code, game_name)
    
    return RedirectResponse(
        url=f"/club/{club_code}/live-game/{game['code']}",
        status_code=303
    )

@app.get("/club/{club_code}/live-game/{code}", response_class=HTMLResponse)
async def live_game_page(request: Request, club_code: str, code: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
    if not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host?next=/club/{club_code}/live-game/{code}", status_code=303)
        
    game = get_live_game(club_code, code)
    if not game:
        return HTMLResponse("<h1>Game Not Found</h1>", status_code=404)
        
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
    host_player_name = request.cookies.get(f"host_player_name_{code.upper()}")
    
    club_badges = calculate_club_badges(club_code)
    return templates.TemplateResponse(
        request=request,
        name="live_game.html",
        context={
            **context,
            "game": game,
            "pool": get_total_pool(game),
            "player_results": player_results,
            "settlements": settlements,
            "host_player_name": host_player_name,
            "club_badges": club_badges,
            "badges_definition": BADGES_DEFINITION
        }
    )

@app.get("/club/{club_code}/live-player/{code}/{player_name}", response_class=HTMLResponse)
async def live_player_page(request: Request, club_code: str, code: str, player_name: str):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    player = get_player(club_code, code, player_name)
    if not player:
        return HTMLResponse("<h1>Player Not Found</h1>", status_code=404)
        
    return templates.TemplateResponse(
        request=request,
        name="live_player.html",
        context={
            **context,
            "code": code,
            "player": player,
            "history": get_player_history(club_code, code, player_name)
        }
    )

@app.get("/club/{club_code}/join", response_class=HTMLResponse)
async def join_page(request: Request, club_code: str, code: str = ""):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    club_code_upper = club_code.upper()
    code_upper = code.upper()
    
    game = get_live_game(club_code_upper, code_upper)
    if game and context.get("logged_in_player"):
        player_name = context["logged_in_player"]["name"]
        for p in game.get("players", []):
            if p["name"].strip().lower() == player_name.strip().lower():
                return RedirectResponse(
                    url=f"/club/{club_code}/secure-player/{code_upper}/{p['token']}",
                    status_code=303
                )
                
    return templates.TemplateResponse(
        request=request,
        name="join.html",
        context={
            **context,
            "code": code_upper,
            "hide_sidebar": True,
            "prefill_name": context["logged_in_player"]["name"] if context.get("logged_in_player") else ""
        }
    )

@app.post("/club/{club_code}/join-game")
async def join_game_route(
    request: Request,
    club_code: str,
    player_name: str = Form(...),
    game_code: str = Form(...)
):
    code_upper = game_code.upper()
    club_code_upper = club_code.upper()
    
    # Check if player is kicked/banned first
    if is_player_kicked(club_code_upper, player_name):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    join_live_game(club_code_upper, code_upper, player_name)
    await manager.broadcast(f"{club_code_upper}_{code_upper}", "update")
    
    player = get_player(club_code_upper, code_upper, player_name)
    if player:
        return RedirectResponse(
            url=f"/club/{club_code}/secure-player/{code_upper}/{player['token']}",
            status_code=303
        )
        
    return RedirectResponse(
        url=f"/club/{club_code}/live-game/{code_upper}",
        status_code=303
    )

@app.post("/club/{club_code}/add-buyin")
async def add_buyin_route(
    request: Request,
    club_code: str,
    code: str = Form(...),
    player_name: str = Form(...),
    amount: int = Form(...)
):
    club_code_upper = club_code.upper()
    add_buyin(club_code_upper, code, player_name, amount)
    await manager.broadcast(f"{club_code_upper}_{code}", "update")
    
    # Redirect check: if it's the host, send to host console, otherwise secure player
    is_host = request.cookies.get(f"club_{club_code_upper}_admin_token") is not None
    if is_host:
        return RedirectResponse(url=f"/club/{club_code}/live-game/{code}", status_code=303)
        
    player = get_player(club_code_upper, code, player_name)
    if player:
        return RedirectResponse(url=f"/club/{club_code}/secure-player/{code}/{player['token']}", status_code=303)
        
    return RedirectResponse(url=f"/club/{club_code}/live-game/{code}", status_code=303)

@app.post("/club/{club_code}/request-buyin")
async def request_buyin_route(
    request: Request,
    club_code: str,
    code: str = Form(...),
    player_name: str = Form(...),
    amount: int = Form(...)
):
    club_code_upper = club_code.upper()
    game_code_upper = code.upper()
    
    if is_player_kicked(club_code_upper, player_name):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    add_buyin_request(club_code_upper, game_code_upper, player_name, amount)
    await manager.broadcast(f"{club_code_upper}_{game_code_upper}", "update")
    
    player = get_player(club_code_upper, game_code_upper, player_name)
    if player:
        return RedirectResponse(url=f"/club/{club_code}/secure-player/{game_code_upper}/{player['token']}", status_code=303)
    return RedirectResponse(url=f"/club/{club_code}/live", status_code=303)

@app.post("/club/{club_code}/resolve-buyin-request")
async def resolve_buyin_request_route(
    request: Request,
    club_code: str,
    code: str = Form(...),
    req_id: str = Form(...),
    action: str = Form(...)
):
    context = get_club_context(club_code, request)
    if not context or not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
        
    club_code_upper = club_code.upper()
    game_code_upper = code.upper()
    
    resolve_buyin_request(club_code_upper, game_code_upper, req_id, action)
    await manager.broadcast(f"{club_code_upper}_{game_code_upper}", "update")
    
    return RedirectResponse(url=f"/club/{club_code}/live-game/{game_code_upper}", status_code=303)

@app.get("/club/{club_code}/secure-player/{code}/{token}", response_class=HTMLResponse)
async def secure_player_page(
    request: Request,
    club_code: str,
    code: str,
    token: str
):
    context = get_club_context(club_code, request)
    if not context:
        return RedirectResponse(url="/", status_code=303)
    if context.get("banned"):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    club_code_upper = club_code.upper()
    player = get_player_by_token(club_code_upper, code, token)
    
    if not player:
        return HTMLResponse("<h1>Player Not Found</h1>", status_code=404)
        
    # Check if kicked mid-game
    if is_player_kicked(club_code_upper, player["name"]):
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>You have been kicked/banned from this club.</h1>", status_code=403)
        
    game = get_live_game(club_code_upper, code)
    game_status = game.get("status", "active") if game else "active"
    
    club_badges = calculate_club_badges(club_code)
    return templates.TemplateResponse(
        request=request,
        name="live_player.html",
        context={
            **context,
            "code": code,
            "player": player,
            "game": game,
            "game_status": game_status,
            "hide_sidebar": True,
            "history": player.get("history", []),
            "club_badges": club_badges,
            "badges_definition": BADGES_DEFINITION
        }
    )

@app.post("/club/{club_code}/update-cashout")
async def update_cashout_route(
    request: Request,
    club_code: str,
    code: str = Form(...),
    player_name: str = Form(...),
    amount: int = Form(...)
):
    club_code_upper = club_code.upper()
    update_cashout(club_code_upper, code, player_name, amount)
    await manager.broadcast(f"{club_code_upper}_{code}", "update")
    
    # Check if host
    is_host = request.cookies.get(f"club_{club_code_upper}_admin_token") is not None
    if is_host:
        return RedirectResponse(url=f"/club/{club_code}/live-game/{code}", status_code=303)
        
    player = get_player(club_code_upper, code, player_name)
    if player:
        return RedirectResponse(
            url=f"/club/{club_code}/secure-player/{code}/{player['token']}",
            status_code=303
        )
    return RedirectResponse(
        url=f"/club/{club_code}/live-game/{code}",
        status_code=303
    )

@app.post("/club/{club_code}/host-join")
async def host_join_route(
    request: Request,
    club_code: str,
    code: str = Form(...),
    player_name: str = Form(...)
):
    club_code_upper = club_code.upper()
    code_upper = code.upper()
    
    join_live_game(club_code_upper, code_upper, player_name)
    await manager.broadcast(f"{club_code_upper}_{code_upper}", "update")
    
    response = RedirectResponse(
        url=f"/club/{club_code}/live-game/{code_upper}",
        status_code=303
    )
    response.set_cookie(
        key=f"host_player_name_{code_upper}",
        value=player_name,
        max_age=86400
    )
    return response

@app.post("/club/{club_code}/admin/update-player")
async def admin_update_player_route(
    request: Request,
    club_code: str,
    code: str = Form(...),
    player_name: str = Form(...),
    buyin: int = Form(...),
    cashout: int = Form(...)
):
    context = get_club_context(club_code, request)
    if not context or not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
        
    club_code_upper = club_code.upper()
    admin_update_player(club_code_upper, code, player_name, buyin, cashout)
    await manager.broadcast(f"{club_code_upper}_{code}", "update")
    
    return RedirectResponse(
        url=f"/club/{club_code}/live-game/{code}",
        status_code=303
    )

@app.post("/club/{club_code}/end-game/{code}")
async def end_game_route(
    request: Request,
    club_code: str,
    code: str
):
    context = get_club_context(club_code, request)
    if not context or not context["is_admin"]:
        return RedirectResponse(url=f"/club/{club_code}/verify-host", status_code=303)
        
    club_code_upper = club_code.upper()
    game = get_live_game(club_code_upper, code)
    if not game:
        return RedirectResponse(url=f"/club/{club_code}/live", status_code=303)
        
    total_buyin = sum(p["buyin"] for p in game.get("players", []))
    total_cashout = sum(p.get("cashout", 0) for p in game.get("players", []))
    
    if total_buyin != total_cashout:
        return RedirectResponse(
            url=f"/club/{club_code}/live-game/{code}?error=unbalanced",
            status_code=303
        )
        
    end_live_game(club_code_upper, code)
    await manager.broadcast(f"{club_code_upper}_{code}", "update")
    return RedirectResponse(
        url=f"/club/{club_code}/live-game/{code}",
        status_code=303
    )

# Websocket endpoint scoped by club and game code
@app.websocket("/ws/live-game/{club_code}/{code}")
async def websocket_endpoint(websocket: WebSocket, club_code: str, code: str):
    room_key = f"{club_code.upper()}_{code.upper()}"
    await manager.connect(room_key, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(room_key, websocket)
    except Exception:
        manager.disconnect(room_key, websocket)

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
