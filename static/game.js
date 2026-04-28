let ws = null;
let currentPlayerId = null;
let gridSize = 1000;
let gameGrid = new Map();
let players = [];
let cameraX = 0, cameraY = 0;
let canvas, ctx;
let isLoggedIn = false;
let loginInProgress = false;
let nickname = '';
let color = '';
const TILE_SIZE = 20;
let viewWidth, viewHeight;
let initTimeout = null;

// Clean up old WebSocket on page unload
window.addEventListener('beforeunload', () => {
    if (ws) ws.close();
});

function login() {
    if (loginInProgress) {
        console.log('Login already in progress');
        return;
    }
    nickname = document.getElementById('nickname').value.trim();
    color = document.getElementById('colorSelect').value;
    if (!nickname) {
        document.getElementById('loginError').textContent = 'Enter nickname';
        return;
    }
    const btn = document.querySelector('.login-screen button');
    btn.disabled = true;
    btn.textContent = 'Connecting...';
    loginInProgress = true;
    document.getElementById('loginError').textContent = '';

    // Close any existing WebSocket
    if (ws) {
        ws.onclose = null; // prevent auto-reconnect
        ws.close();
        ws = null;
    }

    // Clear any previous timeout
    if (initTimeout) clearTimeout(initTimeout);

    // Create new WebSocket
    ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onopen = () => {
        console.log('WebSocket open, sending login');
        ws.send(JSON.stringify({ type: 'login', nickname, color }));
        // Set a timeout for init response
        initTimeout = setTimeout(() => {
            console.error('Init timeout');
            document.getElementById('loginError').textContent = 'Server not responding';
            ws.close();
            loginInProgress = false;
            btn.disabled = false;
            btn.textContent = 'Start Game';
        }, 5000);
    };
    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        handleMessage(data);
    };
    ws.onerror = (err) => {
        console.error('WebSocket error', err);
        if (!isLoggedIn) {
            document.getElementById('loginError').textContent = 'Connection error';
            loginInProgress = false;
            btn.disabled = false;
            btn.textContent = 'Start Game';
        }
    };
    ws.onclose = () => {
        console.log('WebSocket closed');
        if (initTimeout) clearTimeout(initTimeout);
        if (!isLoggedIn) {
            loginInProgress = false;
            btn.disabled = false;
            btn.textContent = 'Start Game';
        }
    };
}

function handleMessage(data) {
    if (data.type === 'init') {
        if (initTimeout) clearTimeout(initTimeout);
        currentPlayerId = data.player_id;
        updateGameState(data.state);
        document.getElementById('loginScreen').classList.add('hidden');
        document.getElementById('gameScreen').classList.remove('hidden');
        setupCanvas();
        setupControls();
        drawGame();
        isLoggedIn = true;
        loginInProgress = false;
        console.log('Game started');
    } else if (data.type === 'game_state') {
        updateGameState(data.state);
        drawGame();
    } else if (data.type === 'error') {
        alert(data.message);
        document.getElementById('loginScreen').classList.remove('hidden');
        document.getElementById('gameScreen').classList.add('hidden');
        isLoggedIn = false;
        loginInProgress = false;
        const btn = document.querySelector('.login-screen button');
        btn.disabled = false;
        btn.textContent = 'Start Game';
        if (ws) ws.close();
    } else if (data.type === 'death') {
        alert(data.message);
    } else if (data.type === 'capture') {
        console.log(`Captured ${data.size} cells`);
    }
}

function updateGameState(state) {
    gridSize = state.grid_size;
    gameGrid.clear();
    for (const [key, val] of Object.entries(state.grid)) {
        gameGrid.set(key, val);
    }
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
    function resizeAndRedraw() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        viewWidth = canvas.width;
        viewHeight = canvas.height;
        drawGame();
    }
    window.addEventListener('resize', resizeAndRedraw);
    resizeAndRedraw();
}

function drawGame() {
    if (!ctx || players.length === 0) return;
    ctx.clearRect(0, 0, viewWidth, viewHeight);
    const me = players.find(p => p.id === currentPlayerId);
    if (me) {
        const [px, py] = me.position;
        cameraX = px * TILE_SIZE - viewWidth/2;
        cameraY = py * TILE_SIZE - viewHeight/2;
    }
    const sx = Math.floor(cameraX / TILE_SIZE) - 2;
    const sy = Math.floor(cameraY / TILE_SIZE) - 2;
    const ex = sx + Math.ceil(viewWidth / TILE_SIZE) + 4;
    const ey = sy + Math.ceil(viewHeight / TILE_SIZE) + 4;
    for (let gy = sy; gy <= ey; gy++) {
        for (let gx = sx; gx <= ex; gx++) {
            const wx = ((gx % gridSize) + gridSize) % gridSize;
            const wy = ((gy % gridSize) + gridSize) % gridSize;
            const key = `${wx},${wy}`;
            let val = gameGrid.get(key);
            let isPath = false;
            let color = val;
            if (val && val.endsWith('_path')) {
                isPath = true;
                color = val.replace('_path', '');
            }
            if (!color) color = 'gray';
            const scx = gx * TILE_SIZE - cameraX;
            const scy = gy * TILE_SIZE - cameraY;
            if (scx + TILE_SIZE > 0 && scx < viewWidth && scy + TILE_SIZE > 0 && scy < viewHeight) {
                if (isPath) {
                    ctx.fillStyle = color;
                    ctx.fillRect(scx, scy, TILE_SIZE-1, TILE_SIZE-1);
                    ctx.strokeStyle = 'white';
                    ctx.lineWidth = 2;
                    ctx.strokeRect(scx, scy, TILE_SIZE-1, TILE_SIZE-1);
                } else {
                    ctx.fillStyle = color === 'gray' ? '#aaa' : color;
                    ctx.fillRect(scx, scy, TILE_SIZE-1, TILE_SIZE-1);
                    ctx.strokeStyle = '#444';
                    ctx.strokeRect(scx, scy, TILE_SIZE-1, TILE_SIZE-1);
                }
            }
        }
    }
    for (const p of players) {
        const [px, py] = p.position;
        const scx = px * TILE_SIZE - cameraX;
        const scy = py * TILE_SIZE - cameraY;
        if (scx + TILE_SIZE > 0 && scx < viewWidth && scy + TILE_SIZE > 0 && scy < viewHeight) {
            ctx.beginPath();
            ctx.arc(scx + TILE_SIZE/2, scy + TILE_SIZE/2, TILE_SIZE/2 - 2, 0, 2 * Math.PI);
            ctx.fillStyle = p.color;
            ctx.fill();
            ctx.strokeStyle = 'white';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.fillStyle = 'white';
            ctx.font = `${TILE_SIZE/2}px Arial`;
            ctx.textAlign = 'center';
            ctx.fillText(p.nickname[0].toUpperCase(), scx + TILE_SIZE/2, scy + TILE_SIZE/2);
        }
    }
}

function setupControls() {
    window.addEventListener('keydown', (e) => {
        const key = e.key.toLowerCase();
        let dir = null;
        if (key === 'w') dir = 'up';
        else if (key === 's') dir = 'down';
        else if (key === 'a') dir = 'left';
        else if (key === 'd') dir = 'right';
        else return;
        e.preventDefault();
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'move', direction: dir }));
        }
    });
}