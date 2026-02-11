// Volleyball Analytics Dashboard JS
const WEIGHTS = { '#': 1.0, '+': 0.4, '!': -0.3, '-': -1.0 };

// NOMBRES ACTUALIZADOS
const FULL_NAMES = {
    'S': 'Saque',
    'R': 'Recepción de Saque',
    'E': 'Acomodo',
    'A': 'Ataque',
    'D': 'Defensa',
    'B': 'Bloqueo'
};

document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('reportDate').innerText = 'Generado: ' + new Date().toLocaleDateString();
});

function parseLog(logString) {
    // Accepts both player actions (e.g., 7S#) and team actions (e.g., S#)
    const regexPlayer = /^(\d+)([SREADB])([#+!-])$/;
    const regexTeam = /^([SREADB])([#+!-])$/;
    const tokens = logString.trim().split(/\s+/);
    const players = {};
    const team = {
        total: 0, scoreSum: 0,
        grades: { '#': 0, '+': 0, '!': 0, '-': 0 },
        actions: {
            'S': {tot:0, good:0}, 'R': {tot:0, good:0}, 'E': {tot:0, good:0},
            'A': {tot:0, good:0}, 'D': {tot:0, good:0}, 'B': {tot:0, good:0}
        }
    };

    tokens.forEach(token => {
        let match = token.match(regexPlayer);
        if (match) {
            const [_, num, action, grade] = match;
            if (!players[num]) {
                players[num] = {
                    total: 0, scoreSum: 0,
                    grades: { '#': 0, '+': 0, '!': 0, '-': 0 },
                    actions: {
                        'S': {tot:0, good:0}, 'R': {tot:0, good:0}, 'E': {tot:0, good:0},
                        'A': {tot:0, good:0}, 'D': {tot:0, good:0}, 'B': {tot:0, good:0}
                    }
                };
            }
            players[num].total++;
            players[num].grades[grade]++;
            players[num].scoreSum += (WEIGHTS[grade] || 0);
            players[num].actions[action].tot++;
            if (grade === '#' || grade === '+') {
                players[num].actions[action].good++;
            }
        } else {
            match = token.match(regexTeam);
            if (match) {
                const [_, action, grade] = match;
                team.total++;
                team.grades[grade]++;
                team.scoreSum += (WEIGHTS[grade] || 0);
                team.actions[action].tot++;
                if (grade === '#' || grade === '+') {
                    team.actions[action].good++;
                }
            }
        }
    });
    return { players, team };
}

function calculateRating(playerData) {
    if (playerData.total === 0) return 0;
    let rawRating = 6.0 + (playerData.scoreSum / playerData.total) * 4.0;
    return Math.max(1.0, Math.min(10.0, rawRating)).toFixed(1);
}

function generateReport() {
    const logText = document.getElementById('matchLog').value;
    const { players, team } = parseLog(logText);
    const grid = document.getElementById('playersGrid');
    const teamGrid = document.getElementById('teamActionsGrid');
    const actionFilter = document.getElementById('actionFilter').value;

    grid.innerHTML = '';
    teamGrid.innerHTML = '';
    let globalTotal = 0, globalPerfect = 0, ratingSum = 0, playerCount = 0;

    // Filtered player stats
    const playersArray = Object.keys(players).map(num => {
        let data = players[num];
        let filtered = filterStatsByAction(data, actionFilter);
        return {
            num,
            data: filtered,
            rating: calculateRating(filtered)
        };
    }).filter(p => p.data.total > 0)
    .sort((a, b) => b.rating - a.rating);

    playersArray.forEach(p => {
        const stats = p.data;
        globalTotal += stats.total;
        globalPerfect += stats.grades['#'];
        ratingSum += parseFloat(p.rating);
        playerCount++;

        const perfectPct = Math.round((stats.grades['#'] / stats.total) * 100);
        const positivePct = Math.round((stats.grades['+'] / stats.total) * 100);
        const regularPct = Math.round((stats.grades['!'] / stats.total) * 100);
        const errorPct = Math.round((stats.grades['-'] / stats.total) * 100);
        
        let ratingColor = p.rating >= 8 ? '#16a34a' : (p.rating >= 6 ? '#ca8a04' : '#dc2626');

        let actionsHtml = Object.entries(stats.actions)
            .filter(([k,v]) => v.tot > 0)
            .map(([k,v]) => {
                let eff = v.tot > 0 ? (v.good / v.tot) : 0;
                let pillClass = '';
                if (eff === 1.0) pillClass = 'high-perf'; 
                else if (eff < 0.4) pillClass = 'low-perf';
                return `
                <div class="action-pill ${pillClass}">
                    <span class="action-name">${FULL_NAMES[k]}</span>
                    <span class="action-count">${v.good}/${v.tot}</span>
                </div>
            `}).join('');

        const card = document.createElement('div');
        card.className = 'player-card';
        card.innerHTML = `
            <div class="card-header">
                <span class="player-number">#${p.num}</span>
                <span class="player-rating" style="color: ${ratingColor}; background: white;">${p.rating}</span>
            </div>
            <div class="card-body">
                <div class="metric-row"><span>Perfecto (#)</span><span>${perfectPct}%</span></div>
                <div class="bar-container"><div class="bar-fill" style="width: ${perfectPct}%; background-color: var(--success);"></div></div>

                <div class="metric-row"><span>Positivo (+)</span><span>${positivePct}%</span></div>
                <div class="bar-container"><div class="bar-fill" style="width: ${positivePct}%; background-color: var(--primary);"></div></div>
                
                <div class="metric-row"><span>Regular (!)</span><span>${regularPct}%</span></div>
                <div class="bar-container"><div class="bar-fill" style="width: ${regularPct}%; background-color: var(--warning);"></div></div>

                <div class="metric-row"><span>Error (-)</span><span>${errorPct}%</span></div>
                <div class="bar-container"><div class="bar-fill" style="width: ${errorPct}%; background-color: var(--danger);"></div></div>
                
                <div class="action-section">
                    <div class="action-title">Efectividad por Acción (Buenos/Total)</div>
                    <div class="action-grid">${actionsHtml}</div>
                </div>
            </div>
        `;
        grid.appendChild(card);
    });

    // Team-level actions
    let teamStats = filterStatsByAction(team, actionFilter);
    if (teamStats.total > 0) {
        const perfectPct = Math.round((teamStats.grades['#'] / teamStats.total) * 100);
        const positivePct = Math.round((teamStats.grades['+'] / teamStats.total) * 100);
        const regularPct = Math.round((teamStats.grades['!'] / teamStats.total) * 100);
        const errorPct = Math.round((teamStats.grades['-'] / teamStats.total) * 100);
        let rating = calculateRating(teamStats);
        let ratingColor = rating >= 8 ? '#16a34a' : (rating >= 6 ? '#ca8a04' : '#dc2626');
        let actionsHtml = Object.entries(teamStats.actions)
            .filter(([k,v]) => v.tot > 0)
            .map(([k,v]) => {
                let eff = v.tot > 0 ? (v.good / v.tot) : 0;
                let pillClass = '';
                if (eff === 1.0) pillClass = 'high-perf'; 
                else if (eff < 0.4) pillClass = 'low-perf';
                return `
                <div class="action-pill ${pillClass}">
                    <span class="action-name">${FULL_NAMES[k]}</span>
                    <span class="action-count">${v.good}/${v.tot}</span>
                </div>
            `}).join('');
        const card = document.createElement('div');
        card.className = 'player-card';
        card.innerHTML = `
            <div class="card-header">
                <span class="player-number">Equipo</span>
                <span class="player-rating" style="color: ${ratingColor}; background: white;">${rating}</span>
            </div>
            <div class="card-body">
                <div class="metric-row"><span>Perfecto (#)</span><span>${perfectPct}%</span></div>
                <div class="bar-container"><div class="bar-fill" style="width: ${perfectPct}%; background-color: var(--success);"></div></div>

                <div class="metric-row"><span>Positivo (+)</span><span>${positivePct}%</span></div>
                <div class="bar-container"><div class="bar-fill" style="width: ${positivePct}%; background-color: var(--primary);"></div></div>
                
                <div class="metric-row"><span>Regular (!)</span><span>${regularPct}%</span></div>
                <div class="bar-container"><div class="bar-fill" style="width: ${regularPct}%; background-color: var(--warning);"></div></div>

                <div class="metric-row"><span>Error (-)</span><span>${errorPct}%</span></div>
                <div class="bar-container"><div class="bar-fill" style="width: ${errorPct}%; background-color: var(--danger);"></div></div>
                
                <div class="action-section">
                    <div class="action-title">Efectividad por Acción (Buenos/Total)</div>
                    <div class="action-grid">${actionsHtml}</div>
                </div>
            </div>
        `;
        teamGrid.appendChild(card);
        globalTotal += teamStats.total;
        globalPerfect += teamStats.grades['#'];
        ratingSum += parseFloat(rating);
        playerCount++;
    }

    if (globalTotal > 0) {
        document.getElementById('totalActions').innerText = globalTotal;
        document.getElementById('teamRating').innerText = (ratingSum / playerCount).toFixed(1);
        document.getElementById('perfectIndex').innerText = Math.round((globalPerfect / globalTotal) * 100) + '%';
        document.getElementById('dashboard').style.display = 'block';
        document.getElementById('btnDownload').style.display = 'inline-block';
    }
}

// Helper to filter stats by action
function filterStatsByAction(stats, action) {
    if (!stats) return null;
    if (action === 'ALL') return stats;
    // Only keep stats for the selected action
    let filtered = {
        total: stats.actions[action].tot,
        scoreSum: 0,
        grades: { '#': 0, '+': 0, '!': 0, '-': 0 },
        actions: { [action]: { ...stats.actions[action] } }
    };
    // For now, grades and scoreSum are not split by action (limitation)
    return filtered;
}

function downloadPDF() {
    const element = document.getElementById('dashboard');
    const opt = {
        margin:       10,
        filename:     'Reporte_Partido_Voley.pdf',
        image:        { type: 'jpeg', quality: 0.98 },
        html2canvas:  { scale: 2 },
        jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };
    html2pdf().set(opt).from(element).save();
}
