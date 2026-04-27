from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
import json
import uuid
import random
from typing import List, Tuple, Optional, Dict

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Game constants
GRID_SIZE = 16
COLORS = ["red", "blue", "yellow", "green", "purple", "orange", "pink", "cyan"]
INITIAL_COLOR = "gray"

# Direction vectors
DIRECTIONS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0)
}

class GameState:
    def __init__(self):
        self.grid = [[INITIAL_COLOR for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        self.players: Dict[str, dict] = {}  # player_id -> {nickname, color, pos, score, ws}
        self.active_colors = set()
        self.lock = asyncio.Lock()
    
    def get_available_colors(self) -> List[str]:
        return [c for c in COLORS if c not in self.active_colors]
    
    def find_spawn_position(self) -> Optional[Tuple[int, int]]:
        gray_cells = [(x, y) for x in range(GRID_SIZE) for y in range(GRID_SIZE) 
                     if self.grid[x][y] == INITIAL_COLOR]
        occupied_positions = [p["pos"] for p in self.players.values()]
        available = [cell for cell in gray_cells if cell not in occupied_positions]
        if available:
            return random.choice(available)
        return None
    
    def add_player(self, player_id: str, nickname: str, color: str, ws: WebSocket) -> bool:
        if color in self.active_colors:
            return False
        spawn = self.find_spawn_position()
        if not spawn:
            return False
        self.active_colors.add(color)
        self.players[player_id] = {
            "nickname": nickname,
            "color": color,
            "pos": spawn,
            "score": 1,
            "ws": ws
        }
        x, y = spawn
        self.grid[x][y] = color
        return True
    
    def remove_player(self, player_id: str):
        if player_id not in self.players:
            return
        player = self.players[player_id]
        color = player["color"]
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                if self.grid[x][y] == color:
                    self.grid[x][y] = INITIAL_COLOR
        self.active_colors.discard(color)
        del self.players[player_id]
        self.recalculate_all_scores()
    
    def recalculate_all_scores(self):
        for player in self.players.values():
            player["score"] = 0
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                cell_color = self.grid[x][y]
                if cell_color != INITIAL_COLOR:
                    for player in self.players.values():
                        if player["color"] == cell_color:
                            player["score"] += 1
                            break
    
    def get_cells_enclosed_by_player(self, player_color: str) -> List[Tuple[int, int]]:
        reachable = [[False for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        queue = []
        for x in range(GRID_SIZE):
            for y in [0, GRID_SIZE-1]:
                if self.grid[x][y] != player_color and not reachable[x][y]:
                    reachable[x][y] = True
                    queue.append((x, y))
        for y in range(GRID_SIZE):
            for x in [0, GRID_SIZE-1]:
                if self.grid[x][y] != player_color and not reachable[x][y]:
                    reachable[x][y] = True
                    queue.append((x, y))
        while queue:
            x, y = queue.pop(0)
            for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < GRID_SIZE and 0 <= ny < GRID_SIZE:
                    if not reachable[nx][ny] and self.grid[nx][ny] != player_color:
                        reachable[nx][ny] = True
                        queue.append((nx, ny))
        enclosed = []
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                if not reachable[x][y] and self.grid[x][y] != player_color:
                    enclosed.append((x, y))
        return enclosed
    
    def capture_enclosed_regions(self, player_id: str) -> int:
        player = self.players[player_id]
        player_color = player["color"]
        enclosed_cells = self.get_cells_enclosed_by_player(player_color)
        if not enclosed_cells:
            return 0
        points_gained = 0
        for x, y in enclosed_cells:
            old_color = self.grid[x][y]
            if old_color != player_color:
                if old_color != INITIAL_COLOR:
                    for p in self.players.values():
                        if p["color"] == old_color:
                            p["score"] -= 1
                            break
                points_gained += 1
                self.grid[x][y] = player_color
        player["score"] += points_gained
        return points_gained
    
    def move_player(self, player_id: str, direction: str) -> Tuple[bool, int]:
        if player_id not in self.players:
            return False, 0
        player = self.players[player_id]
        old_x, old_y = player["pos"]
        dx, dy = DIRECTIONS.get(direction, (0, 0))
        new_x, new_y = old_x + dx, old_y + dy
        if not (0 <= new_x < GRID_SIZE and 0 <= new_y < GRID_SIZE):
            return False, 0
        for pid, p in self.players.items():
            if pid != player_id and p["pos"] == (new_x, new_y):
                return False, 0
        target_color = self.grid[new_x][new_y]
        if target_color != INITIAL_COLOR and target_color != player["color"]:
            return False, 0
        player["pos"] = (new_x, new_y)
        if self.grid[new_x][new_y] != player["color"]:
            self.grid[new_x][new_y] = player["color"]
            player["score"] += 1
        points_gained = self.capture_enclosed_regions(player_id)
        return True, points_gained
    
    def get_game_state(self) -> dict:
        players_info = []
        for pid, player in self.players.items():
            players_info.append({
                "id": pid,
                "nickname": player["nickname"],
                "color": player["color"],
                "position": player["pos"],
                "score": player["score"]
            })
        return {
            "grid": self.grid,
            "players": players_info,
            "grid_size": GRID_SIZE
        }

game_state = GameState()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    player_id = None
    
    try:
        data = await websocket.receive_json()
        if data.get("type") == "login":
            nickname = data.get("nickname", "Anonymous")
            color = data.get("color", COLORS[0])
            
            async with game_state.lock:
                success = game_state.add_player(player_id := str(uuid.uuid4()), nickname, color, websocket)
                if not success:
                    await websocket.send_json({"type": "error", "message": "Color taken or no spawn position available"})
                    await websocket.close()
                    return
                await websocket.send_json({
                    "type": "init",
                    "player_id": player_id,
                    "state": game_state.get_game_state()
                })
                await manager.broadcast({
                    "type": "game_state",
                    "state": game_state.get_game_state()
                })
            
            while True:
                msg = await websocket.receive_json()
                if msg.get("type") == "move":
                    direction = msg.get("direction")
                    async with game_state.lock:
                        success, _ = game_state.move_player(player_id, direction)
                        if success:
                            await manager.broadcast({
                                "type": "game_state",
                                "state": game_state.get_game_state()
                            })
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Invalid move"
                            })
    
    except WebSocketDisconnect:
        if player_id:
            async with game_state.lock:
                game_state.remove_player(player_id)
                await manager.broadcast({
                    "type": "game_state",
                    "state": game_state.get_game_state()
                })
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)