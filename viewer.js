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
                        }) || snapshot.score[0] + snapshot.score[1] !== index ||
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
        if (action === 'longest') {
            var longest = set.snapshots[snapshotIndex(set, time)].longest;
            if (longest) rally = set.rallies.find(function (item) { return item.id === longest.id; });
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

    function draw(set, index, time, available, message) {
        if (available) clearTimeout(loadTimeout);
        text('status', message);
        var snapshot = set.snapshots[index];
        text('score', snapshot.score.join(' - '));
        el('stats').setAttribute('aria-label', available ?
            'Estadísticas sincronizadas' : 'Estadísticas no sincronizadas; valores iniciales');
        el('youtube').href = 'https://www.youtube.com/watch?v=' + set.video_id;
        text('reconciliation', set.reconciled ?
            'Set verificado contra el marcador registrado (oculto hasta completar las jugadas).' :
            'Sin marcador final registrado; no hay reconciliación independiente del resultado.');
        var active = repeatRally(set, time);
        text('current', active ? 'Set ' + set.number + ', jugada ' + active.number +
            (time < active.end ? ' en curso' : ' completada') : 'Antes de la primera jugada');
        text('longest', snapshot.longest ? 'Jugada más larga completada: ' +
            snapshot.longest.duration + ' s' : 'Sin jugadas completadas.');
        var key = set.id + ':' + index;
        if (renderedKey !== key) {
            renderedKey = key;
            var cards = el('cards');
            cards.replaceChildren();
            [
                ['Toques registrados', snapshot.team.touches],
                ['Aces', snapshot.team.aces],
                ['Kills de ataque', snapshot.team.kills],
                ['Bloqueos ganadores', snapshot.team.blocks],
                ['Toques con error', snapshot.team.errors],
                ['Eficiencia de ataque', snapshot.team.attack_efficiency === null ? '—' :
                    (snapshot.team.attack_efficiency * 100).toFixed(1) + '%']
            ].forEach(function (pair) {
                var card = element('div');
                card.className = 'stat-card';
                card.append(element('strong', String(pair[1])), element('div', pair[0]));
                cards.append(card);
            });
            var rows = el('players');
            rows.replaceChildren();
            snapshot.players.forEach(function (player) {
                var row = element('tr');
                var name = Object.prototype.hasOwnProperty.call(payload.names, player.number) ?
                    payload.names[player.number] : '#' + player.number;
                [String(name) + ' (#' + player.number + ')', player.touches, player.kills,
                    player.aces, player.blocks, player.rating === null ? '—' : player.rating
                ].forEach(function (value) { row.append(element('td', String(value))); });
                rows.append(row);
            });
            var list = el('rallies');
            list.replaceChildren();
            set.rallies.forEach(function (rally, position) {
                var item = element('li');
                var button = element('button', 'Set ' + set.number + ' · Jugada ' + rally.number);
                button.type = 'button';
                button.dataset.replay = 'rally';
                button.dataset.rally = rally.id;
                item.append(button);
                // Future rows never show outcome, score, duration or touch details.
                if (position < index) {
                    var result = set.snapshots[position + 1].score;
                    item.append(element('span', ' Completada · ' + result.join(' - ')));
                }
                list.append(item);
            });
        }
        root.querySelectorAll('[data-replay]').forEach(function (button) {
            var action = button.dataset.replay;
            button.disabled = !available ||
                (action === 'next' && !nextRally(set, time)) ||
                (action === 'repeat' && !active) ||
                (action === 'longest' && !snapshot.longest);
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
