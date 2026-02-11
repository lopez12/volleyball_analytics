function importFromGithub() {
    const repo = 'lopez12/volleyball_analytics';
    const branch = 'main';
    const apiUrl = `https://api.github.com/repos/${repo}/contents/`;
    const select = document.getElementById('githubFileSelect');
    select.style.display = 'inline-block';
    select.innerHTML = '<option>Cargando archivos...</option>';
    fetch(apiUrl)
        .then(res => res.json())
        .then(files => {
            const txtFiles = files.filter(f => f.name.endsWith('.txt'));
            if (txtFiles.length === 0) {
                select.innerHTML = '<option>No hay archivos .txt</option>';
                return;
            }
            select.innerHTML = '<option value="">Selecciona un archivo...</option>' +
                txtFiles.map(f => `<option value="${f.name}">${f.name}</option>`).join('');
            select.onchange = function() {
                if (!this.value) return;
                const rawUrl = `https://raw.githubusercontent.com/${repo}/${branch}/${this.value}`;
                fetch(rawUrl)
                  .then(res => res.text())
                  .then(text => {
                      document.getElementById('matchLog').value = text;
                      select.style.display = 'none';
                      generateReport();
                  })
                  .catch(() => alert('No se pudo cargar el archivo.'));
            };
        })
        .catch(() => {
            select.innerHTML = '<option>Error al buscar archivos</option>';
        });
}
window.importFromGithub = importFromGithub;
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
    const baseActions = () => ({'S':{tot:0,good:0},'R':{tot:0,good:0},'E':{tot:0,good:0},'A':{tot:0,good:0},'D':{tot:0,good:0},'B':{tot:0,good:0}});
    const baseGrades = () => ({'#':0,'+':0,'!':0,'-':0});
    const baseActionsByQuality = () => ({'#':[], '+':[], '!':[], '-':[]});
    // For fast summary tables: actionsByGradeCount[grade][action] = count
    const baseActionsByGradeCount = () => ({'#':{'S':0,'R':0,'E':0,'A':0,'D':0,'B':0},'+':{'S':0,'R':0,'E':0,'A':0,'D':0,'B':0},'!':{'S':0,'R':0,'E':0,'A':0,'D':0,'B':0},'-':{'S':0,'R':0,'E':0,'A':0,'D':0,'B':0}});

    const players = {};
    const team = {
        total: 0,
        scoreSum: 0,
        grades: baseGrades(),
        actions: baseActions(),
        actionsByQuality: baseActionsByQuality(),
        actionsByGradeCount: baseActionsByGradeCount()
    };

    tokens.forEach(token => {
        let match = token.match(regexPlayer);
        if (match) {
            const [_, num, action, grade] = match;
            if (!players[num]) {
                players[num] = {
                    total: 0,
                    scoreSum: 0,
                    grades: baseGrades(),
                    actions: baseActions(),
                    actionsByQuality: baseActionsByQuality(),
                    actionsByGradeCount: baseActionsByGradeCount()
                };
            }
            // General stats
            players[num].total++;
            players[num].grades[grade]++;
            players[num].scoreSum += (WEIGHTS[grade] || 0);
            // Per-action stats
            players[num].actions[action].tot++;
            if (grade === '#' || grade === '+') {
                players[num].actions[action].good++;
            }
            // For summary tables
            players[num].actionsByQuality[grade].push(`${num}${action}${grade}`);
            players[num].actionsByGradeCount[grade][action]++;
            // Team aggregate
            team.total++;
            team.grades[grade]++;
            team.scoreSum += (WEIGHTS[grade] || 0);
            team.actions[action].tot++;
            if (grade === '#' || grade === '+') {
                team.actions[action].good++;
            }
            team.actionsByQuality[grade].push(`${num}${action}${grade}`);
            team.actionsByGradeCount[grade][action]++;
        } else {
            match = token.match(regexTeam);
            if (match) {
                const [_, action, grade] = match;
                // Team only
                team.total++;
                team.grades[grade]++;
                team.scoreSum += (WEIGHTS[grade] || 0);
                team.actions[action].tot++;
                if (grade === '#' || grade === '+') {
                    team.actions[action].good++;
                }
                team.actionsByQuality[grade].push(`T${action}${grade}`);
                team.actionsByGradeCount[grade][action]++;
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

    grid.innerHTML = '';
    teamGrid.innerHTML = '';
    let globalTotal = 0, globalPerfect = 0, ratingSum = 0, playerCount = 0;

    // Player stats
    const playersArray = Object.keys(players).map(num => {
        let data = players[num];
        return {
            num,
            data,
            rating: calculateRating(data)
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

        // Build summary table directly from actions and grades for consistency
        let summaryByQuality = { '#': {}, '+': {}, '!': {}, '-': {} };
        Object.keys(FULL_NAMES).forEach(action => {
            summaryByQuality['#'][action] = 0;
            summaryByQuality['+'][action] = 0;
            summaryByQuality['!'][action] = 0;
            summaryByQuality['-'][action] = 0;
        });
        // For each action, distribute the grades based on the player's grades and actions
        // We need to count, for each action, how many of each grade occurred
        // We'll use actionsByQuality for this, but with a direct mapping
        if (stats.actionsByQuality) {
            ['#','+','!','-'].forEach(grade => {
                stats.actionsByQuality[grade].forEach(token => {
                    // token is like 7A-
                    // Instead of regex, just get the last two chars for action and grade
                    // e.g., 7A- => action = token[token.length-2]
                    const action = token[token.length-2];
                    if (summaryByQuality[grade][action] !== undefined) {
                        summaryByQuality[grade][action]++;
                    }
                });
            });
        }
        // Find max good (perfect+positive) and max bad (error) per action row
        const actions = Object.keys(FULL_NAMES);
        let maxGood = {}, maxBad = {};
        actions.forEach(action => {
            maxGood[action] = Math.max(summaryByQuality['#'][action], summaryByQuality['+'][action]);
            maxBad[action] = summaryByQuality['-'][action];
        });
        // Find the highest good and bad values among all actions
        let globalMaxGood = Math.max(...actions.map(a => maxGood[a]));
        let globalMaxBad = Math.max(...actions.map(a => maxBad[a]));

        let actionsByQualityHtml = `
            <div class="action-section" style="margin-top:16px;">
                <div class="action-title" style="margin-bottom:8px;">Resumen por Calidad y Acción</div>
                <div style="overflow-x:auto;">
                <table class="summary-table">
                    <thead>
                        <tr>
                            <th></th>
                            <th>Perfecto</th>
                            <th>Positivo</th>
                            <th>Regular</th>
                            <th>Error</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${actions.map(action => {
                            return `<tr>
                                <td>${FULL_NAMES[action]}</td>
                                <td class="${summaryByQuality['#'][action] === globalMaxGood ? 'highlight-good' : ''}">${summaryByQuality['#'][action]}</td>
                                <td class="${summaryByQuality['+'][action] === globalMaxGood ? 'highlight-good' : ''}">${summaryByQuality['+'][action]}</td>
                                <td>${summaryByQuality['!'][action]}</td>
                                <td class="${summaryByQuality['-'][action] === globalMaxBad && globalMaxBad > 0 ? 'highlight-bad' : ''}">${summaryByQuality['-'][action]}</td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
                </div>
            </div>
        `;

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
                ${actionsByQualityHtml}
            </div>
        `;
        grid.appendChild(card);
    });

    // Team-level actions
    let teamStats = team;
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

        // Team summary table (modern style)
        // Build summary table directly from actions and grades for consistency
        let summaryByQuality = { '#': {}, '+': {}, '!': {}, '-': {} };
        Object.keys(FULL_NAMES).forEach(action => {
            summaryByQuality['#'][action] = 0;
            summaryByQuality['+'][action] = 0;
            summaryByQuality['!'][action] = 0;
            summaryByQuality['-'][action] = 0;
        });
        if (teamStats.actionsByQuality) {
            ['#','+','!','-'].forEach(grade => {
                teamStats.actionsByQuality[grade].forEach(token => {
                    // token is like 7A- or T[A]-
                    const action = token[token.length-2];
                    if (summaryByQuality[grade][action] !== undefined) {
                        summaryByQuality[grade][action]++;
                    }
                });
            });
        }
        // Find max good (perfect+positive) and max bad (error) per action row
        const actions = Object.keys(FULL_NAMES);
        let maxGood = {}, maxBad = {};
        actions.forEach(action => {
            maxGood[action] = Math.max(summaryByQuality['#'][action], summaryByQuality['+'][action]);
            maxBad[action] = summaryByQuality['-'][action];
        });
        let globalMaxGood = Math.max(...actions.map(a => maxGood[a]));
        let globalMaxBad = Math.max(...actions.map(a => maxBad[a]));
        let actionsByQualityHtml = `
            <div class="action-section" style="margin-top:16px;">
                <div class="action-title" style="margin-bottom:8px;">Resumen por Calidad y Acción</div>
                <div style="overflow-x:auto;">
                <table class="summary-table">
                    <thead>
                        <tr>
                            <th></th>
                            <th>Perfecto</th>
                            <th>Positivo</th>
                            <th>Regular</th>
                            <th>Error</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${actions.map(action => {
                            return `<tr>
                                <td>${FULL_NAMES[action]}</td>
                                <td class="${summaryByQuality['#'][action] === globalMaxGood ? 'highlight-good' : ''}">${summaryByQuality['#'][action]}</td>
                                <td class="${summaryByQuality['+'][action] === globalMaxGood ? 'highlight-good' : ''}">${summaryByQuality['+'][action]}</td>
                                <td>${summaryByQuality['!'][action]}</td>
                                <td class="${summaryByQuality['-'][action] === globalMaxBad && globalMaxBad > 0 ? 'highlight-bad' : ''}">${summaryByQuality['-'][action]}</td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
                </div>
            </div>
        `;

        const card = document.createElement('div');
        card.className = 'player-card team-summary-card';
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
                ${actionsByQualityHtml}
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
        // Use the same method for team rating as for the team summary card
        document.getElementById('teamRating').innerText = calculateRating(teamStats);
        document.getElementById('perfectIndex').innerText = Math.round((globalPerfect / globalTotal) * 100) + '%';
        document.getElementById('dashboard').style.display = 'block';
        document.getElementById('btnDownload').style.display = 'inline-block';
    }
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
