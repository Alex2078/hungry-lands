let ws = null, currentPlayerId = null, gridSize = 1000;
let gameGrid = new Map(), players = [], cameraX = 0, cameraY = 0;
let canvas, ctx, isLoggedIn = false, loginInProgress = false;
let nickname = '', color = '';
const TILE_SIZE = 20;
let viewWidth, viewHeight, initTimeout = null;

window.addEventListener('beforeunload', () => { if (ws) ws.close(); });

function login() {
    if (loginInProgress) return;
    nickname = document.getElementById('nickname').value.trim();
    color = document.getElementById('colorSelect').value;
    if (!nickname) { document.getElementById('loginError').textContent = 'Enter nickname'; return; }
    
    const btn = document.querySelector('.login-screen button');
    btn.disabled = true; btn.textContent = 'Connecting...';
    loginInProgress = true; document.getElementById('loginError').textContent = '';
    
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    if (initTimeout) clearTimeout(initTimeout);

    ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'login', nickname, color }));
        initTimeout = setTimeout(() => {
            document.getElementById('loginError').textContent = 'Server not responding';
            ws.close(); loginInProgress = false; btn.disabled = false; btn.textContent = 'Start Game';
        }, 5000);
    };
    ws.onmessage = e => handleMessage(JSON.parse(e.data));
    ws.onerror = () => { if(!isLoggedIn) { document.getElementById('loginError').textContent='Connection error'; loginInProgress=false; btn.disabled=false; btn.textContent='Start Game'; }};
    ws.onclose = () => { if(initTimeout) clearTimeout(initTimeout); if(!isLoggedIn) { loginInProgress=false; btn.disabled=false; btn.textContent='Start Game'; }};
}

function handleMessage(data) {
    if (data.type === 'init') {
        if (initTimeout) clearTimeout(initTimeout);
        currentPlayerId = data.player_id;
        updateGameState(data.state);
        document.getElementById('loginScreen').classList.add('hidden');
        document.getElementById('gameScreen').classList.remove('hidden');
        setupCanvas(); setupControls(); drawGame();
        isLoggedIn = true; loginInProgress = false;
    } else if (data.type === 'game_state') {
        updateGameState(data.state); drawGame();
    } else if (data.type === 'death') { alert(data.message); }
    else if (data.type === 'capture') { console.log(`Captured ${data.size} cells`); drawGame(); }
}

function updateGameState(state) {
    gridSize = state.grid_size; gameGrid.clear();
    for (const [k, v] of Object.entries(state.grid)) gameGrid.set(k, v);
    players = state.players;
    const me = players.find(p => p.id === currentPlayerId);
    if (me) {
        document.getElementById('currentPlayerName').innerHTML = `<div style="background:${me.color};width:16px;height:16px;border-radius:50%;display:inline-block;"></div> ${me.nickname}`;
        document.getElementById('currentScore').innerText = `Score: ${me.score}`;
    }
}

function setupCanvas() {
    canvas = document.getElementById('gameCanvas');
    ctx = canvas.getContext('2d');
    function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; viewWidth = canvas.width; viewHeight = canvas.height; drawGame(); }
    window.addEventListener('resize', resize); resize();
}

function drawGame() {
    if (!ctx || !players.length) return;
    // White background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, viewWidth, viewHeight);

    const me = players.find(p => p.id === currentPlayerId);
    if (me) {
        cameraX = me.position[0] * TILE_SIZE - viewWidth/2;
        cameraY = me.position[1] * TILE_SIZE - viewHeight/2;
    }

    const sx = Math.floor(cameraX / TILE_SIZE) - 2;
    const sy = Math.floor(cameraY / TILE_SIZE) - 2;
    const ex = sx + Math.ceil(viewWidth / TILE_SIZE) + 4;
    const ey = sy + Math.ceil(viewHeight / TILE_SIZE) + 4;

    // Batch draw
    const batches = {};
    for (let gy = sy; gy <= ey; gy++) {
        for (let gx = sx; gx <= ex; gx++) {
            const wx = ((gx % gridSize) + gridSize) % gridSize;
            const wy = ((gy % gridSize) + gridSize) % gridSize;
            const key = `${wx},${wy}`;
            let val = gameGrid.get(key);
            let isPath = false, cellColor = val;

            if (val && val.endsWith('_path')) { isPath = true; cellColor = val.replace('_path', ''); }
            if (!cellColor) cellColor = '#ffffff';

            const scx = gx * TILE_SIZE - cameraX;
            const scy = gy * TILE_SIZE - cameraY;
            if (!batches[cellColor]) batches[cellColor] = [];
            batches[cellColor].push({ x: scx, y: scy, path: isPath });
        }
    }

    for (const [c, rects] of Object.entries(batches)) {
        ctx.fillStyle = c;
        for (const r of rects) {
            ctx.fillRect(r.x, r.y, TILE_SIZE-1, TILE_SIZE-1);
            if (r.path) {
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 2;
                ctx.strokeRect(r.x, r.y, TILE_SIZE-1, TILE_SIZE-1);
            }
        }
    }

    for (const p of players) {
        const scx = p.position[0] * TILE_SIZE - cameraX;
        const scy = p.position[1] * TILE_SIZE - cameraY;
        if (scx > -TILE_SIZE && scx < viewWidth && scy > -TILE_SIZE && scy < viewHeight) {
            ctx.beginPath();
            ctx.arc(scx + TILE_SIZE/2, scy + TILE_SIZE/2, TILE_SIZE/2 - 2, 0, Math.PI*2);
            ctx.fillStyle = p.color; ctx.fill();
            ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
            ctx.fillStyle = '#fff'; ctx.font = `bold ${TILE_SIZE/2}px Arial`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(p.nickname[0].toUpperCase(), scx + TILE_SIZE/2, scy + TILE_SIZE/2);
        }
    }
}

function setupControls() {
    let last = 0;
    window.addEventListener('keydown', e => {
        const k = e.key.toLowerCase();
        let d = null;
        if(k==='w') d='up'; else if(k==='s') d='down'; else if(k==='a') d='left'; else if(k==='d') d='right'; else return;
        e.preventDefault();
        const now = performance.now();
        if(now - last < 100) return; last = now;
        if(ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'move', direction:d}));
    });
}