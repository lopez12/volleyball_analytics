/* Read-only spectator playback. Statistics are computed exclusively in Python. */
(function () {
    'use strict';

    function finite(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    function snapshotIndex(set, time) {
        var low = 0;
        var high = set.rallies.length;
        while (low < high) {
            var middle = Math.floor((low + high) / 2);
            if (set.rallies[middle].end <= time) low = middle + 1;
            else high = middle;
        }
        return low;
    }

    function nextRally(set, time) {
        return set.rallies.find(function (rally) { return rally.start > time; }) || null;
    }

    function repeatRally(set, time) {
        // At shared boundaries choose the new active interval, not the old one.
        var active = set.rallies.find(function (rally) {
            return rally.start <= time && time < rally.end;
        });
        var index = snapshotIndex(set, time);
        return active || (index ? set.rallies[index - 1] : null);
    }

    function validatePayload(payload) {
        if (!payload || !Array.isArray(payload.sets) || !payload.sets.length ||
                !payload.names || typeof payload.names !== 'object') return false;
        return payload.sets.every(function (set) {
            if (!set || typeof set.id !== 'string' ||
                    !/^[A-Za-z0-9_-]{11}$/.test(set.video_id) ||
                    !Number.isInteger(set.number) || set.number < 1 ||
                    !Array.isArray(set.start_score) || set.start_score.length !== 2 ||
                    !set.start_score.every(function (value) {
                        return Number.isInteger(value) && value >= 0;
                    }) ||
                    !Array.isArray(set.rallies) || !set.rallies.length ||
                    !Array.isArray(set.snapshots) ||
                    set.snapshots.length !== set.rallies.length + 1) return false;
            var previous = 0;
            var ids = {};
            var valid = set.rallies.every(function (rally) {
                if (!rally || typeof rally.id !== 'string' || ids[rally.id] ||
                        !Number.isInteger(rally.number) || rally.number < 1 ||
                        !finite(rally.start) || !finite(rally.end) ||
                        rally.start < previous || rally.end < rally.start) return false;
                previous = rally.end;
                ids[rally.id] = true;
                return true;
            });
            return valid && set.snapshots.every(function (snapshot, index) {
                if (!snapshot || !Array.isArray(snapshot.score) || snapshot.score.length !== 2 ||
                        !snapshot.score.every(function (value) {
                            return Number.isInteger(value) && value >= 0;
                        }) || snapshot.score[0] + snapshot.score[1] !==
                            index + set.start_score[0] + set.start_score[1] ||
                        snapshot.score.some(function (value, side) {
                            return value < set.start_score[side] ||
                                (index === 0 && value !== set.start_score[side]);
                        }) ||
                        !snapshot.team || !Array.isArray(snapshot.players)) return false;
                function counts(row) {
                    return ['touches', 'aces', 'kills', 'blocks', 'errors'].every(function (key) {
                        return Number.isInteger(row[key]) && row[key] >= 0;
                    }) && (row.rating === null || (finite(row.rating) &&
                        row.rating >= 1 && row.rating <= 10)) &&
                        (row.attack_efficiency === null || (finite(row.attack_efficiency) &&
                        Math.abs(row.attack_efficiency) <= 1));
                }
                return (index !== 0 || (snapshot.team.touches === 0 &&
                    snapshot.longest === null && snapshot.players.every(function (row) {
                        return row && row.touches === 0 && row.rating === null;
                    }))) && counts(snapshot.team) && snapshot.players.every(function (row) {
                    return row && /^\d+$/.test(row.number) && counts(row);
                }) && (snapshot.longest === null || (
                    typeof snapshot.longest === 'object' &&
                    set.rallies.slice(0, index).some(function (rally) {
                        return rally.id === snapshot.longest.id &&
                            rally.start === snapshot.longest.start &&
                            rally.end - rally.start === snapshot.longest.duration;
                    })));
            });
        });
    }

    function Controller(payload, update, failure) {
        this.payload = payload;
        this.update = update;
        this.failure = failure;
        this.index = 0;
        this.player = null;
        this.ready = false;
        this.failed = false;
        this.pending = false;
        this.playingIntent = false;
    }

    Controller.prototype.set = function () { return this.payload.sets[this.index]; };
    Controller.prototype.fail = function (message) {
        this.failed = true;
        this.ready = false;
        this.failure(message);
    };
    Controller.prototype.time = function () {
        if (!this.ready || this.failed || !this.player) return null;
        try {
            var data = this.player.getVideoData();
            if (!data || data.video_id !== this.set().video_id) {
                if (!this.pending) {
                    this.fail('El video activo no corresponde al set seleccionado.');
                }
                return null;
            }
            var time = this.player.getCurrentTime();
            if (this.pending && time !== 0) return null;
            return finite(time) && time >= 0 ? time : null;
        } catch (error) {
            this.fail('Se perdió la conexión con el reproductor. Abre el video en YouTube.');
            return null;
        }
    };
    Controller.prototype.reconcile = function () {
        var time = this.time();
        if (this.failed) return;
        if (time === null) {
            this.update(this.set(), 0, 0, false, 'Esperando al video seleccionado; sin sincronización.');
            return;
        }
        this.pending = false;
        var state;
        try { state = this.player.getPlayerState(); } catch (error) {
            this.fail('Se perdió la conexión con el reproductor. Abre el video en YouTube.');
            return;
        }
        if (state === 1) this.playingIntent = true;
        if (state === 2 || state === 5 || state === 0) this.playingIntent = false;
        var message = state === 3 ? 'Cargando video; sincronización en espera.' :
            (state === 1 ? 'Reproduciendo; estadísticas sincronizadas.' :
                'Video en pausa; estadísticas sincronizadas.');
        this.update(this.set(), snapshotIndex(this.set(), time), time, true, message);
    };
    Controller.prototype.attach = function (player) {
        this.player = player;
        this.ready = true;
        // A selector change may have happened while the IFrame was loading.
        try {
            var data = player.getVideoData();
            if (!data || data.video_id !== this.set().video_id) {
                this.pending = true;
                player.cueVideoById({videoId: this.set().video_id, startSeconds: 0});
            }
        } catch (error) {
            this.fail('No se pudo preparar el video seleccionado. Abre el video en YouTube.');
            return;
        }
        this.reconcile();
    };
    Controller.prototype.switchSet = function (index) {
        if (!Number.isInteger(index) || index < 0 || index >= this.payload.sets.length) return;
        this.index = index;
        this.pending = true;
        this.playingIntent = false;
        this.update(this.set(), 0, 0, false, 'Cargando set; estadísticas en cero.');
        if (this.ready && !this.failed) {
            try {
                this.player.cueVideoById({videoId: this.set().video_id, startSeconds: 0});
            } catch (error) {
                this.fail('No se pudo cargar el set. Abre el video en YouTube.');
            }
        }
    };
    Controller.prototype.seek = function (action, id) {
        var time = this.time();
        if (time === null || this.pending) return;
        var set = this.set();
        var rally = null;
        if (action === 'next') rally = nextRally(set, time);
        if (action === 'repeat') rally = repeatRally(set, time);
        if (action === 'rally') {
            rally = set.rallies.find(function (item) { return item.id === id; });
        }
        if (!rally) return;
        try {
            var state = this.player.getPlayerState();
            var playing = state === 1 || (state === 3 && this.playingIntent);
            this.player.seekTo(rally.start, true);
            if (playing) this.player.playVideo();
            else this.player.pauseVideo();
            // seekTo is asynchronous: display only what the actual clock confirms.
            this.reconcile();
        } catch (error) {
            this.fail('No se pudo navegar por el video. Abre el video en YouTube.');
        }
    };

    var exported = {
        snapshotIndex: snapshotIndex, nextRally: nextRally, repeatRally: repeatRally,
        validatePayload: validatePayload, Controller: Controller
    };
    if (typeof module !== 'undefined' && module.exports) module.exports = exported;
    if (typeof document === 'undefined') return;
    var root = document.getElementById('replay-viewer');
    if (!root) return;

    function el(id) { return document.getElementById('replay-' + id); }
    function text(id, value) {
        var node = el(id);
        if (node.textContent !== value) node.textContent = value;
    }
    function element(tag, value) {
        var node = document.createElement(tag);
        if (value !== undefined) node.textContent = value;
        return node;
    }
    function disable() {
        root.querySelectorAll('[data-replay]').forEach(function (button) { button.disabled = true; });
    }
    var payload;
    try { payload = JSON.parse(el('data').textContent); } catch (error) { payload = null; }
    if (!validatePayload(payload)) {
        text('status', 'Datos de sincronización no válidos. Usa el enlace a YouTube o el reporte.');
        disable();
        el('set').disabled = true;
        return;
    }
    var renderedKey = '';
    var timer = null;
    var loadTimeout = null;
    var failed = false;
    var controller;
    var spotlightSelect = el('spotlight-select');
    var playerNumbers = {};
    payload.sets.forEach(function (set) {
        set.snapshots.forEach(function (snapshot) {
            snapshot.players.forEach(function (player) { playerNumbers[player.number] = true; });
        });
    });
    var sortedPlayerNumbers = Object.keys(playerNumbers).sort(function (left, right) {
        return Number(left) - Number(right);
    });
    sortedPlayerNumbers.forEach(function (number) {
        var option = element('option');
        option.value = number;
        var name = Object.prototype.hasOwnProperty.call(payload.names, number) ?
            payload.names[number] : '';
        option.textContent = name ? '#' + number + ' · ' + name : '#' + number;
        spotlightSelect.append(option);
    });
    var selectedPlayer = '';
    try {
        var storedPlayer = window.localStorage.getItem('va-replay-player');
        if (storedPlayer && Object.prototype.hasOwnProperty.call(playerNumbers, storedPlayer)) {
            selectedPlayer = storedPlayer;
        }
    } catch (error) {}
    spotlightSelect.value = selectedPlayer;

    var spotlightCard = el('spotlight');
    var spotlightHeader = element('div');
    spotlightHeader.className = 'card-header';
    var spotlightName = element('span');
    spotlightName.className = 'player-number';
    var spotlightRatingPill = element('span');
    spotlightRatingPill.className = 'player-rating';
    spotlightHeader.append(spotlightName, spotlightRatingPill);
    var spotlightBody = element('div');
    spotlightBody.className = 'card-body';
    var spotlightValues = element('div');
    spotlightValues.className = 'replay-spotlight-values';
    var spotlightValueNodes = {};
    [
        ['touches', 'Toques'], ['kills', 'Kills'], ['aces', 'Aces'],
        ['blocks', 'Bloqueos'], ['rating', 'Rating']
    ].forEach(function (pair) {
        var item = element('div');
        item.className = 'replay-spotlight-value';
        var value = element('strong', '0');
        var label = element('span', pair[1]);
        item.append(value, label);
        spotlightValues.append(item);
        spotlightValueNodes[pair[0]] = item;
    });
    var spotlightEmpty = element('p', 'Sin toques registrados en este set');
    spotlightEmpty.className = 'replay-spotlight-empty';
    spotlightEmpty.hidden = true;
    spotlightBody.append(spotlightValues, spotlightEmpty);
    spotlightCard.append(spotlightHeader, spotlightBody);
    var previousSpotlightPlayer = '';
    var previousSpotlightValues = null;

    function updateSpotlight(snapshot) {
        if (!selectedPlayer) {
            spotlightCard.hidden = true;
            previousSpotlightPlayer = '';
            previousSpotlightValues = null;
            return;
        }
        var player = snapshot.players.find(function (row) {
            return row.number === selectedPlayer;
        });
        var hasTouches = Boolean(player && player.touches > 0);
        var values = hasTouches ? player : {
            touches: 0, kills: 0, aces: 0, blocks: 0, rating: null
        };
        var name = Object.prototype.hasOwnProperty.call(payload.names, selectedPlayer) ?
            payload.names[selectedPlayer] : '';
        spotlightName.textContent = name ? '#' + selectedPlayer + ' · ' + name :
            '#' + selectedPlayer;
        var displayValues = {
            touches: values.touches,
            kills: values.kills,
            aces: values.aces,
            blocks: values.blocks,
            rating: values.rating === null ? '—' : values.rating
        };
        if (previousSpotlightPlayer !== selectedPlayer) previousSpotlightValues = null;
        Object.keys(displayValues).forEach(function (key) {
            var node = spotlightValueNodes[key];
            var value = String(displayValues[key]);
            if (previousSpotlightValues && String(previousSpotlightValues[key]) !== value) {
                node.classList.remove('replay-value-pulse');
                void node.offsetWidth;
                node.classList.add('replay-value-pulse');
            }
            node.firstElementChild.textContent = value;
        });
        var rating = displayValues.rating;
        if (previousSpotlightValues && String(previousSpotlightValues.rating) !== rating) {
            spotlightRatingPill.classList.remove('replay-value-pulse');
            void spotlightRatingPill.offsetWidth;
            spotlightRatingPill.classList.add('replay-value-pulse');
        }
        spotlightRatingPill.textContent = rating;
        spotlightEmpty.hidden = hasTouches;
        spotlightCard.hidden = false;
        previousSpotlightPlayer = selectedPlayer;
        previousSpotlightValues = displayValues;
    }

    function draw(set, index, time, available, message) {
        if (available) clearTimeout(loadTimeout);
        text('status', message);
        var snapshot = set.snapshots[index];
        text('score', snapshot.score.join(' \u2013 '));
        var offset = set.start_score.some(function (value) { return value !== 0; });
        text('scope', offset ? 'Estad\u00edsticas registradas en la grabaci\u00f3n' :
            'Estad\u00edsticas del set hasta este momento');
        text('start-note', offset ? 'La grabaci\u00f3n inicia con el marcador ' +
            set.start_score.join('\u2013') + '.' : '');
        el('start-note').hidden = !offset;
        el('stats').setAttribute('aria-label', available ?
            'Estad\u00edsticas sincronizadas' : 'Estad\u00edsticas no sincronizadas; valores iniciales');
        el('youtube').href = 'https://www.youtube.com/watch?v=' + set.video_id;
        text('reconciliation', set.reconciled ?
            'Set verificado contra el marcador registrado (oculto hasta completar las jugadas).' :
            'Sin marcador final registrado; no hay reconciliaci\u00f3n independiente del resultado.');
        var active = repeatRally(set, time);
        text('current', active ? 'Set ' + set.number + ' \u00b7 Jugada ' + active.number +
            (time < active.end ? ' en curso' : ' completada') : 'Antes de la primera jugada');
        var key = set.id + ':' + index;
        if (renderedKey !== key) {
            renderedKey = key;
            var cards = el('cards');
            cards.replaceChildren();
            [
                ['Aces', snapshot.team.aces],
                ['Kills', snapshot.team.kills],
                ['Bloqueos', snapshot.team.blocks],
                ['Toques con error', snapshot.team.errors],
                ['Eficiencia de ataque', snapshot.team.attack_efficiency === null ? '—' :
                    (snapshot.team.attack_efficiency * 100).toFixed(1) + '%'],
                ['Rally m\u00e1s largo', snapshot.longest ? snapshot.longest.duration + ' s' : '—']
            ].forEach(function (pair) {
                var card = element('div');
                card.className = 'stat-card';
                card.append(element('div', String(pair[1])), element('div', pair[0]));
                card.firstElementChild.className = 'stat-value';
                card.lastElementChild.className = 'stat-label';
                cards.append(card);
            });
            var rows = el('players');
            rows.replaceChildren();
            var tablePlayers = snapshot.players.filter(function (player) {
                return player.touches > 0;
            });
            tablePlayers.sort(function (left, right) {
                if (left.number === selectedPlayer) return -1;
                if (right.number === selectedPlayer) return 1;
                return Number(left.number) - Number(right.number);
            });
            tablePlayers.forEach(function (player) {
                var row = element('tr');
                var name = Object.prototype.hasOwnProperty.call(payload.names, player.number) ?
                    payload.names[player.number] : '#' + player.number;
                var nameCell = element('td');
                if (player.number === selectedPlayer) {
                    row.setAttribute('aria-current', 'true');
                    var marker = element('span', '★ ');
                    marker.setAttribute('aria-hidden', 'true');
                    nameCell.append(marker);
                }
                nameCell.append(element('span', String(name) + ' (#' + player.number + ')'));
                row.append(nameCell);
                [player.touches, player.kills, player.aces, player.blocks,
                    player.rating === null ? '—' : player.rating
                ].forEach(function (value) { row.append(element('td', String(value))); });
                row.dataset.player = player.number;
                rows.append(row);
            });
            var list = el('rallies');
            list.replaceChildren();
            set.rallies.forEach(function (rally) {
                var button = element('button', String(rally.number));
                button.type = 'button';
                button.className = 'action-pill';
                button.setAttribute('aria-label', 'Jugada ' + rally.number);
                button.dataset.replay = 'rally';
                button.dataset.rally = rally.id;
                list.append(button);
            });
        }
        updateSpotlight(snapshot);
        el('rallies').querySelectorAll('[data-replay="rally"]').forEach(function (button) {
            var current = active && button.dataset.rally === active.id;
            if (current) button.setAttribute('aria-current', 'true');
            else button.removeAttribute('aria-current');
        });
        root.querySelectorAll('[data-replay]').forEach(function (button) {
            var action = button.dataset.replay;
            button.disabled = !available ||
                (action === 'next' && !nextRally(set, time)) ||
                (action === 'repeat' && !active);
        });
    }

    function failure(message) {
        failed = true;
        stopSync();
        clearTimeout(loadTimeout);
        draw(controller.set(), 0, 0, false, message + ' Estadísticas no sincronizadas.');
        disable();
    }
    function stopSync() {
        clearInterval(timer);
        timer = null;
    }
    function startSync() {
        // Never more than one poller, and never for a failed or unready controller.
        stopSync();
        if (failed || !controller.ready) return;
        // Also poll while paused: the native scrubber need not emit a new state.
        timer = setInterval(function () { controller.reconcile(); }, 250);
    }
    controller = new Controller(payload, draw, failure);
    draw(controller.set(), 0, 0, false, 'Esperando al reproductor; estadísticas en cero.');
    spotlightSelect.addEventListener('change', function () {
        selectedPlayer = spotlightSelect.value;
        try {
            if (selectedPlayer) window.localStorage.setItem('va-replay-player', selectedPlayer);
            else window.localStorage.removeItem('va-replay-player');
        } catch (error) {}
        renderedKey = '';
        if (controller.failed) draw(controller.set(), 0, 0, false, el('status').textContent);
        else controller.reconcile();
    });

    function waitForVideo() {
        clearTimeout(loadTimeout);
        loadTimeout = setTimeout(function () {
            controller.fail('YouTube no respondió. El acceso o la inserción pueden estar bloqueados.');
        }, 20000);
    }
    root.addEventListener('click', function (event) {
        var button = event.target.closest('[data-replay]');
        if (button && !button.disabled) controller.seek(button.dataset.replay, button.dataset.rally);
    });
    el('set').addEventListener('change', function () {
        if (!failed) waitForVideo();
        controller.switchSet(Number(el('set').value));
        if (failed) failure('El reproductor no está disponible. Abre el video en YouTube.');
    });
    if (window.location.protocol === 'file:') {
        controller.fail('YouTube no permite sincronizar desde file://. Sirve el sitio por HTTP(S).');
        return;
    }
    waitForVideo();
    window.onYouTubeIframeAPIReady = function () {
        if (failed) return;
        try {
            var player = new window.YT.Player('replay-player', {
                width: '100%', height: '100%', videoId: controller.set().video_id,
                playerVars: {playsinline: 1, origin: window.location.origin},
                events: {
                    onReady: function () {
                        if (failed) return;
                        controller.attach(player);
                        startSync();
                    },
                    onStateChange: function () { if (controller.ready) controller.reconcile(); },
                    onError: function () {
                        controller.fail('No se puede reproducir este video o su inserción está bloqueada.');
                    }
                }
            });
        } catch (error) {
            controller.fail('No se pudo iniciar el reproductor de YouTube.');
        }
    };
    var script = document.createElement('script');
    script.src = 'https://www.youtube.com/iframe_api';
    script.onerror = function () { controller.fail('No se pudo cargar la API de YouTube.'); };
    document.head.append(script);
    var suspended = false;
    window.addEventListener('pagehide', function () {
        suspended = true;
        stopSync();
        clearTimeout(loadTimeout);
    });
    // A back/forward cache restore keeps this page and the player alive but
    // fires no new onReady, so polling and the load watchdog are resumed here.
    window.addEventListener('pageshow', function () {
        if (!suspended) return;
        suspended = false;
        if (failed) return;
        if (!controller.ready) {
            waitForVideo();
            return;
        }
        controller.reconcile();
        startSync();
    });
}());
