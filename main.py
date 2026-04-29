from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uuid, asyncio
from game_logic import GameState, COLORS

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
game_state = GameState()

class ConnectionManager:
    def __init__(self): self.active_connections = set()
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.add(ws)
    def disconnect(self, ws: WebSocket): self.active_connections.discard(ws)
    async def broadcast(self, msg: dict):
        dead = set()
        for conn in self.active_connections:
            try: await conn.send_json(msg)
            except: dead.add(conn)
        for conn in dead: self.disconnect(conn)
    async def broadcast_state(self):
        await self.broadcast({"type": "game_state", "state": game_state.get_game_state()})

manager = ConnectionManager()
game_state.set_broadcast_callback(manager.broadcast_state)

@app.get("/favicon.ico")
async def favicon(): return Response(status_code=204)

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    player_id = None
    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if data.get("type") != "login": await websocket.close(); return

        nickname = data.get("nickname", "Anon")[:15]
        color = data.get("color", COLORS[0])

        async with game_state.lock:
            for pid in [k for k, v in game_state.players.items() if v.nickname == nickname and v.color == color]:
                game_state.remove_player(pid)
            
            player_id = str(uuid.uuid4())
            game_state.add_player(player_id, nickname, color, websocket)
            await websocket.send_json({"type": "init", "player_id": player_id, "state": game_state.get_game_state()})
            await manager.broadcast_state()

        while True:
            msg = await asyncio.wait_for(websocket.receive_json(), timeout=60)
            if msg.get("type") == "move":
                async with game_state.lock:
                    p = game_state.players.get(player_id)
                    if p:
                        if p.moving: game_state.change_direction(player_id, msg["direction"])
                        else: game_state.start_moving(player_id, msg["direction"])
                await manager.broadcast_state()
    except Exception: pass
    finally:
        if player_id:
            async with game_state.lock:
                game_state.remove_player(player_id)
                await manager.broadcast_state()
        manager.disconnect(websocket)