import asyncio
import random
from typing import Dict, Set, Tuple, Optional, List, Callable, Awaitable
from collections import deque

GRID_SIZE = 1000
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
                self.land.add(((cx + dx) % GRID_SIZE, (cy + dy) % GRID_SIZE))
        self.score = len(self.land)
        self.pos = (cx, cy)
        self.moving = False

class GameState:
    def __init__(self):
        self.players: Dict[str, Player] = {}
        self.lock = asyncio.Lock()
        self.broadcast_callback: Optional[Callable[[], Awaitable[None]]] = None

    def set_broadcast_callback(self, cb): self.broadcast_callback = cb

    def get_cell_owner(self, x: int, y: int) -> Optional[str]:
        for p in self.players.values():
            if (x, y) in p.land: return p.color
        return None

    def is_free_5x5(self, cx: int, cy: int) -> bool:
        return all(self.get_cell_owner((cx+dx)%GRID_SIZE, (cy+dy)%GRID_SIZE) is None 
                   for dx in range(-2,3) for dy in range(-2,3))

    def find_spawn(self) -> Tuple[int, int]:
        for _ in range(5000):
            cx, cy = random.randint(0, GRID_SIZE-1), random.randint(0, GRID_SIZE-1)
            if self.is_free_5x5(cx, cy): return (cx, cy)
        return (0, 0)

    def add_player(self, pid: str, nickname: str, color: str, ws) -> bool:
        spawn = self.find_spawn()
        p = Player(pid, nickname, color, ws)
        p.init_land(spawn[0], spawn[1])
        self.players[pid] = p
        return True

    def remove_player(self, pid: str):
        p = self.players.pop(pid, None)
        if p and p.task and not p.task.done(): p.task.cancel()

    def is_on_border(self, p: Player) -> bool:
        x, y = p.pos
        return any(((x+dx)%GRID_SIZE, (y+dy)%GRID_SIZE) not in p.land for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)])

    def start_moving(self, pid: str, direction: str) -> bool:
        p = self.players.get(pid)
        if not p or p.pos not in p.land: return False

        # ✅ Rule 1.3 Fix: Allow direction changes while moving on trail
        if p.moving:
            if direction == OPPOSITE.get(p.dir): return False
            p.dir = direction
            return True

        # Start new trail
        dx, dy = DIR_VECT[direction]
        nx, ny = (p.pos[0]+dx)%GRID_SIZE, (p.pos[1]+dy)%GRID_SIZE
        if (nx, ny) in p.land or self.is_on_border(p):
            p.moving = True
            p.dir = direction
            p.path.clear()
            p.stop_event.clear()
            p.task = asyncio.create_task(self._move_loop(p))
            return True
        return False

    async def _move_loop(self, p: Player):
        while p.moving:
            await asyncio.sleep(MOVE_INTERVAL)
            if p.stop_event.is_set(): break

            async with self.lock:
                if not p.moving: break

                dx, dy = DIR_VECT[p.dir]
                cx, cy = p.pos
                nx, ny = (cx+dx)%GRID_SIZE, (cy+dy)%GRID_SIZE
                curr_land = (cx, cy) in p.land
                next_land = (nx, ny) in p.land

                # Inside -> Inside
                if curr_land and next_land:
                    p.pos = (nx, ny)
                    await self._broadcast()
                    continue

                # Inside -> Outside (Start Trail)
                if curr_land and not next_land:
                    p.pos = (nx, ny)
                    p.path.append(p.pos)
                    await self._broadcast()
                    continue

                # On Trail: Self Collision
                if (nx, ny) in p.path:
                    await self._handle_death(p, "Hit own trail!")
                    return

                # On Trail: Enemy Collision
                owner = self.get_cell_owner(nx, ny)
                if owner and owner != p.color:
                    await self._handle_death(p, f"Hit {owner}'s land!")
                    return

                # ✅ Rule 3.3: Trail -> Own Land (Close Loop)
                if next_land:
                    p.pos = (nx, ny)
                    await self._handle_capture(p, (nx, ny))
                    return

                # Normal Trail Step
                p.pos = (nx, ny)
                p.path.append(p.pos)
                await self._broadcast()

                if len(p.path) > 5000:
                    await self._handle_death(p, "Path too long")
                    return

    async def _broadcast(self):
        if self.broadcast_callback: await self.broadcast_callback()

    async def _handle_death(self, p: Player, reason: str):
        p.moving = False
        p.stop_event.set()
        if p.task: p.task.cancel()
        # ✅ No lock here to prevent deadlock
        spawn = self.find_spawn()
        p.init_land(spawn[0], spawn[1])
        p.dir = None
        await p.ws.send_json({"type": "death", "message": reason})
        await self._broadcast()

    async def _handle_capture(self, p: Player, land_entry: Tuple[int, int]):
        loop_pts = p.path + [land_entry]
        if len(loop_pts) < 3:
            p.moving = False; p.path.clear(); return

        min_x = max(0, min(pt[0] for pt in loop_pts) - 1)
        max_x = min(GRID_SIZE-1, max(pt[0] for pt in loop_pts) + 1)
        min_y = max(0, min(pt[1] for pt in loop_pts) - 1)
        max_y = min(GRID_SIZE-1, max(pt[1] for pt in loop_pts) + 1)

        loop_set = set(loop_pts)
        outside = set()
        queue = deque([(min_x, min_y)])
        while queue:
            cx, cy = queue.popleft()
            if (cx, cy) in outside or (cx, cy) in loop_set: continue
            outside.add((cx, cy))
            for dx, dy in [(1,0), (-1,0), (0,1), (0,-1)]:
                nx, ny = cx + dx, cy + dy
                if min_x <= nx <= max_x and min_y <= ny <= max_y:
                    queue.append((nx, ny))

        captured = []
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                if (x, y) not in outside and (x, y) not in loop_set:
                    captured.append((x, y))

        # ✅ Rule 4: Fill smaller loop (wrap-safe)
        box_area = (max_x - min_x + 1) * (max_y - min_y + 1)
        fill_cells = captured if len(captured) <= box_area / 2 else [
            (x,y) for x in range(min_x, max_x+1) for y in range(min_y, max_y+1)
            if (x,y) not in loop_set and (x,y) not in set(captured)
        ]

        p.land.update(fill_cells)
        p.land.update(p.path)
        p.score = len(p.land)
        p.moving = False
        p.path.clear()
        if p.task: p.task.cancel()

        print(f"[CAPTURE] {p.nickname} gained {len(fill_cells)+len(loop_pts)} cells")
        await p.ws.send_json({"type": "capture", "size": len(fill_cells) + len(loop_pts)})
        await self._broadcast()

    def change_direction(self, pid: str, new_dir: str) -> bool:
        p = self.players.get(pid)
        if not p or not p.moving or new_dir == OPPOSITE.get(p.dir): return False
        p.dir = new_dir
        return True

    def get_game_state(self):
        grid = {}
        for p in self.players.values():
            for x, y in p.land: grid[f"{x},{y}"] = p.color
            for x, y in p.path: grid[f"{x},{y}"] = p.color + "_path"
        return {
            "grid": grid,
            "players": [{"id": p.id, "nickname": p.nickname, "color": p.color,
                         "position": list(p.pos), "score": p.score, "moving": p.moving} for p in self.players.values()],
            "grid_size": GRID_SIZE
        }