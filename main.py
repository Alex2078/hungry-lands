from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uuid
import asyncio
from game_logic import GameState, COLORS

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

game_state = GameState()

class ConnectionManager:
    def __init__(self):
        self.active_connections = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        dead = set()
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except:
                dead.add(conn)
        for conn in dead:
            self.disconnect(conn)

    async def broadcast_state(self):
        await self.broadcast({"type": "game_state", "state": game_state.get_game_state()})

manager = ConnectionManager()
game_state.set_broadcast_callback(manager.broadcast_state)

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    player_id = None
    nickname = None
    try:
        # Wait for login message with timeout
        data = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if data.get("type") != "login":
            await websocket.close()
            return
        nickname = data.get("nickname", "Anonymous")
        color = data.get("color", COLORS[0])

        async with game_state.lock:
            # Remove any existing player with same nickname and color
            to_remove = [pid for pid, p in game_state.players.items() if p.nickname == nickname and p.color == color]
            for pid in to_remove:
                game_state.remove_player(pid)
                print(f"[CLEANUP] Removed duplicate {nickname} ({color})")

            player_id = str(uuid.uuid4())
            success = game_state.add_player(player_id, nickname, color, websocket)
            if not success:
                await websocket.send_json({"type": "error", "message": "No free spawn area"})
                await websocket.close()
                return

            await websocket.send_json({
                "type": "init",
                "player_id": player_id,
                "state": game_state.get_game_state()
            })
            await manager.broadcast_state()
            print(f"[INIT] {nickname} ({color}) id={player_id}")

        # Main loop: just wait for move messages
        while True:
            msg = await asyncio.wait_for(websocket.receive_json(), timeout=60)
            if msg.get("type") == "move":
                direction = msg.get("direction")
                async with game_state.lock:
                    p = game_state.players.get(player_id)
                    if p:
                        if p.moving:
                            game_state.change_direction(player_id, direction)
                        else:
                            game_state.start_moving(player_id, direction)
                        await manager.broadcast_state()
    except asyncio.TimeoutError:
        print(f"[TIMEOUT] {nickname or player_id}")
    except WebSocketDisconnect:
        print(f"[DISCONNECT] {nickname or player_id}")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        if player_id:
            async with game_state.lock:
                game_state.remove_player(player_id)
                await manager.broadcast_state()
            print(f"[REMOVE] {nickname or player_id}")
        manager.disconnect(websocket)