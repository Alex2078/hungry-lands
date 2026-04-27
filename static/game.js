let ws = null;
let currentPlayerId = null;
let gridSize = 16;
let cellSize = 30; // 480/16
let gameGrid = [];
let players = [];

const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');

function login() {
    const nickname = document.getElementById('nickname').value.trim();
    const color = document.getElementById('colorSelect').value;
    
    if (!nickname) {
        document.getElementById('loginError').textContent = 'Please enter a nickname';
        return;
    }
    
    // Connect WebSocket
    ws = new WebSocket(`ws://${window.location.host}/ws`);
    
    ws.onopen = () => {
        ws.send(JSON.stringify({
            type: 'login',
            nickname: nickname,
            color: color
        }));
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        document.getElementById('loginError').textContent = 'Connection error. Make sure server is running.';
    };
    
    ws.onclose = () => {
        console.log('WebSocket closed');
        if (currentPlayerId) {
            alert('Disconnected from server');
            location.reload();
        }
    };
}

function handleWebSocketMessage(data) {
    if (data.type === 'init') {
        currentPlayerId = data.player_id;
        updateGameState(data.state);
        document.getElementById('loginScreen').classList.add('hidden');
        document.getElementById('gameScreen').classList.remove('hidden');
        setupKeyboardControls();
    } else if (data.type === 'game_state') {
        updateGameState(data.state);
    } else if (data.type === 'error') {
        alert(data.message);
        if (data.message.includes('Color taken') || data.message.includes('spawn')) {
            location.reload();
        }
    }
}

function updateGameState(state) {
    gameGrid = state.grid;
    players = state.players;
    gridSize = state.grid_size;
    cellSize = canvas.width / gridSize;
    
    // Update current player info
    const currentPlayer = players.find(p => p.id === currentPlayerId);
    if (currentPlayer) {
        document.getElementById('currentPlayerName').innerHTML = 
            `<div class="color-preview" style="background-color: ${currentPlayer.color}"></div>
             ${currentPlayer.nickname}`;
        document.getElementById('currentScore').textContent = `Score: ${currentPlayer.score}`;
    }
    
    // Update leaderboard
    const sortedPlayers = [...players].sort((a, b) => b.score - a.score);
    const leaderboardHtml = sortedPlayers.map(player => `
        <div class="leaderboard-item ${player.id === currentPlayerId ? 'current' : ''}">
            <div>
                <div class="color-preview" style="background-color: ${player.color}"></div>
                ${player.nickname}
            </div>
            <div>${player.score}</div>
        </div>
    `).join('');
    document.getElementById('leaderboard').innerHTML = leaderboardHtml || '<div>No players</div>';
    
    // Draw game
    drawGame();
}

function drawGame() {
    if (!gameGrid) return;
    
    // Draw cells
    for (let x = 0; x < gridSize; x++) {
        for (let y = 0; y < gridSize; y++) {
            const color = gameGrid[x][y];
            ctx.fillStyle = color === 'gray' ? '#cccccc' : color;
            ctx.fillRect(x * cellSize, y * cellSize, cellSize - 1, cellSize - 1);
            
            // Add border
            ctx.strokeStyle = '#999';
            ctx.strokeRect(x * cellSize, y * cellSize, cellSize, cellSize);
        }
    }
    
    // Draw players
    for (const player of players) {
        const [x, y] = player.position;
        ctx.beginPath();
        ctx.arc(x * cellSize + cellSize/2, y * cellSize + cellSize/2, cellSize/2 - 2, 0, 2 * Math.PI);
        ctx.fillStyle = player.color;
        ctx.fill();
        ctx.strokeStyle = 'white';
        ctx.lineWidth = 2;
        ctx.stroke();
        
        // Draw player initial
        ctx.fillStyle = 'white';
        ctx.font = `${cellSize/2}px Arial`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(player.nickname.charAt(0).toUpperCase(), x * cellSize + cellSize/2, y * cellSize + cellSize/2);
    }
}

function setupKeyboardControls() {
    window.addEventListener('keydown', (e) => {
        const key = e.key.toLowerCase();
        let direction = null;
        
        if (key === 'w') direction = 'up';
        else if (key === 's') direction = 'down';
        else if (key === 'a') direction = 'left';
        else if (key === 'd') direction = 'right';
        
        if (direction && ws && ws.readyState === WebSocket.OPEN) {
            e.preventDefault();
            ws.send(JSON.stringify({
                type: 'move',
                direction: direction
            }));
        }
    });
}

// Handle window resize for better display
function adjustCanvas() {
    const container = document.querySelector('.canvas-container');
    const size = Math.min(container.clientWidth, 480);
    canvas.width = size;
    canvas.height = size;
    cellSize = size / gridSize;
    if (gameGrid) drawGame();
}

window.addEventListener('resize', adjustCanvas);