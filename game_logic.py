import asyncio
import random
from typing import Dict, Set, Tuple, Optional, List, Callable, Awaitable

GRID_SIZE = 1000
NEUTRAL = "gray"
COLORS = ["red", "blue", "yellow", "green", "purple", "orange", "pink", "cyan"]
MOVE_INTERVAL = 0.2
DIR_VECT = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}

class Player:
    def __init__(self, pid: str, nickname: str, color: str, ws):
        self.id = pid
        self.nickname = nickname
        self.color = color
        self.ws = ws
        self.land: Set[Tuple[int, int]] = set()
        self.path: List[Tuple[int, int]] = []
        self.pos = (0, 0)
        self.moving = False
        self.dir: Optional[str] = None
        self.score = 0
        self.task: Optional[asyncio.Task] = None
        self.stop_event = asyncio.Event()

    def init_land(self, cx: int, cy: int):
        self.land.clear()
        self.path.clear()
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                x = (cx + dx) % GRID_SIZE
                y = (cy + dy) % GRID_SIZE
                self.land.add((x, y))
        self.score = len(self.land)
        self.pos = (cx, cy)

class GameState:
    def __init__(self):
        self.players: Dict[str, Player] = {}
        self.lock = asyncio.Lock()
        self.broadcast_callback: Optional[Callable[[], Awaitable[None]]] = None

    def set_broadcast_callback(self, callback):
        self.broadcast_callback = callback

    def get_cell_owner(self, x: int, y: int) -> Optional[str]:
        for p in self.players.values():
            if (x, y) in p.land:
                return p.color
        return None

    def is_free_5x5(self, cx: int, cy: int) -> bool:
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                x = (cx + dx) % GRID_SIZE
                y = (cy + dy) % GRID_SIZE
                if self.get_cell_owner(x, y) is not None:
                    return False
        return True

    def find_spawn_center(self) -> Tuple[int, int]:
        for _ in range(5000):
            cx = random.randint(0, GRID_SIZE-1)
            cy = random.randint(0, GRID_SIZE-1)
            if self.is_free_5x5(cx, cy):
                return (cx, cy)
        for _ in range(10000):
            cx = random.randint(0, GRID_SIZE-1)
            cy = random.randint(0, GRID_SIZE-1)
            if self.get_cell_owner(cx, cy) is None: 
                return (cx, cy)
        return (0, 0)

    def add_player(self, pid: str, nickname: str, color: str, ws) -> bool:
        spawn = self.find_spawn_center()
        p = Player(pid, nickname, color, ws)
        p.init_land(spawn[0], spawn[1])
        self.players[pid] = p
        print(f"[ADD] {nickname} ({color}) at {p.pos}, land size {len(p.land)}")
        return True

    def remove_player(self, pid: str):
        if pid not in self.players:
            return
        p = self.players[pid]
        if p.task and not p.task.done():
            p.task.cancel()
        del self.players[pid]
        print(f"[REMOVE] {pid}")

    def is_on_border(self, p: Player) -> bool:
        x, y = p.pos
        for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
            nx, ny = (x+dx) % GRID_SIZE, (y+dy) % GRID_SIZE
            if (nx, ny) not in p.land:
                return True
        return False

    def start_moving(self, pid: str, direction: str) -> bool:
        p = self.players.get(pid)
        if not p or p.moving:
            return False
        if p.pos not in p.land:
            return False
        dx, dy = DIR_VECT[direction]
        x, y = p.pos
        nx, ny = (x+dx) % GRID_SIZE, (y+dy) % GRID_SIZE

        if (nx, ny) in p.land:
            p.moving = True
            p.dir = direction
            p.path.clear()
            p.stop_event.clear()
            p.task = asyncio.create_task(self._move_loop(p))
            return True

        if self.is_on_border(p):
            p.moving = True
            p.dir = direction
            p.path.clear()
            p.stop_event.clear()
            p.task = asyncio.create_task(self._move_loop(p))
            return True

        return False

    async def _move_loop(self, p: Player):
        while p.moving:
            try:
                await asyncio.sleep(MOVE_INTERVAL)
                if p.stop_event.is_set():
                    break

                async with self.lock:
                    if not p.moving:
                        break

                    dx, dy = DIR_VECT[p.dir]
                    x, y = p.pos
                    nx, ny = (x+dx) % GRID_SIZE, (y+dy) % GRID_SIZE
                    current_is_land = (x, y) in p.land
                    next_is_land = (nx, ny) in p.land

                    if current_is_land and next_is_land:
                        p.pos = (nx, ny)
                        await self._broadcast()
                        continue

                    if current_is_land and not next_is_land:
                        p.pos = (nx, ny)
                        p.path.append(p.pos)
                        print(f"[TRAIL START] {p.nickname} at {p.pos}")
                        await self._broadcast()
                        continue

                    if (nx, ny) in p.path:
                        await self._kill_player(p, "Touched own trail!")
                        return

                    owner = self.get_cell_owner(nx, ny)
                    if owner is not None and owner != p.color: 
                        await self._kill_player(p, f"Entered {owner} land!")
                        return

                    if (nx, ny) in p.land:
                        p.pos = (nx, ny)
                        await self._capture_enclosed(p, (nx, ny))
                        return

                    p.pos = (nx, ny)
                    p.path.append(p.pos)
                    print(f"[TRAIL STEP] {p.nickname} at {p.pos}, path len {len(p.path)}")
                    await self._broadcast()

                    if len(p.path) > 5000:
                        await self._kill_player(p, "Path too long")
                        return
            except asyncio.CancelledError:
                break

    async def _broadcast(self):
        if self.broadcast_callback:
            await self.broadcast_callback()

    async def _kill_player(self, p: Player, reason: str):
        p.moving = False
        p.stop_event.set()
        if p.task:
            p.task.cancel()
        async with self.lock:
            spawn = self.find_spawn_center()
            p.land.clear()
            p.path.clear()
            p.init_land(spawn[0], spawn[1])
            p.dir = None
            p.moving = False
        await p.ws.send_json({"type": "death", "message": reason + " Respawned."})
        await self._broadcast()

    async def _capture_enclosed(self, p: Player, land_cell: Tuple[int, int]):
        loop = p.path + [land_cell]
        min_x = min(pt[0] for pt in loop)
        max_x = max(pt[0] for pt in loop)
        min_y = min(pt[1] for pt in loop)
        max_y = max(pt[1] for pt in loop)
        min_x = max(0, min_x - 1)
        max_x = min(GRID_SIZE-1, max_x + 1)
        min_y = max(0, min_y - 1)
        max_y = min(GRID_SIZE-1, max_y + 1)

        captured = []
        loop_set = set(loop)
        for x in range(min_x, max_x+1):
            for y in range(min_y, max_y+1):
                if (x, y) in loop_set:
                    continue
                if self._point_in_polygon(x, y, loop):
                    captured.append((x, y))

        async with self.lock:
            for cx, cy in captured:
                p.land.add((cx, cy))
            for cx, cy in p.path:
                p.land.add((cx, cy))
            p.score = len(p.land)
            p.moving = False
            p.path.clear()
            if p.task:
                p.task.cancel()
        await p.ws.send_json({"type": "capture", "size": len(captured) + len(loop)})
        await self._broadcast()
        print(f"[CAPTURE] {p.nickname} gained {len(captured)+len(loop)} cells, score {p.score}")

    @staticmethod
    def _point_in_polygon(px: int, py: int, poly: List[Tuple[int, int]]) -> bool:
        inside = False
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i+1)%n]
            if ((y1 > py) != (y2 > py)) and (px < (x2-x1)*(py-y1)/(y2-y1) + x1):
                inside = not inside
        return inside

    def change_direction(self, pid: str, new_dir: str) -> bool:
        p = self.players.get(pid)
        if not p or not p.moving:
            return False
        if new_dir == OPPOSITE.get(p.dir):
            return False
        p.dir = new_dir
        return True

    def get_game_state(self):
        grid = {}
        for p in self.players.values():
            for (x, y) in p.land:
                grid[f"{x},{y}"] = p.color
            for (x, y) in p.path:
                grid[f"{x},{y}_path"] = p.color
        players_info = [{
            "id": p.id,
            "nickname": p.nickname,
            "color": p.color,
            "position": p.pos,
            "score": p.score,
            "moving": p.moving,
        } for p in self.players.values()]
        return {"grid": grid, "players": players_info, "grid_size": GRID_SIZE}