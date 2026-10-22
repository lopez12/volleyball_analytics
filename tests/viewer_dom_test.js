/* Browser-only DOM checks using a deterministic fake IFrame API, never YouTube. */
(function () {
    'use strict';
    try { localStorage.setItem('va-replay-player', '8'); } catch (error) {}
    var clock = 0;
    var state = 2;
    var videoId = 'abcdefghijk';
    var events;
    var result = document.createElement('p');
    result.id = 'browser-smoke-result';
    function assert(value, message) { if (!value) throw new Error(message); }
    function score() { return document.getElementById('replay-score').textContent; }
    function values(selector) {
        return Array.from(document.querySelectorAll(selector), function (node) {
            return node.textContent;
        });
    }
    function action(name) { return document.querySelector('[data-replay="' + name + '"]'); }
    function update() { events.onStateChange(); }
    // Track live pollers so lifecycle tests can detect leaked or duplicate timers.
    var intervals = {};
    var nativeSetInterval = window.setInterval.bind(window);
    var nativeClearInterval = window.clearInterval.bind(window);
    window.setInterval = function (callback, delay) {
        var id = nativeSetInterval(callback, delay);
        intervals[id] = true;
        return id;
    };
    window.clearInterval = function (id) {
        delete intervals[id];
        nativeClearInterval(id);
    };
    function pollers() { return Object.keys(intervals).length; }
    function lifecycle(name) { window.dispatchEvent(new Event(name)); }
    function finish(message) {
        result.textContent = message;
        document.body.dataset.testViewport = String(window.innerWidth);
        document.body.append(result);
        if (window.parent !== window) {
            window.parent.postMessage({
                type: 'replay-smoke', message: message, viewport: window.innerWidth
            }, window.location.origin);
        }
        window.dispatchEvent(new Event('pagehide'));
    }
    window.addEventListener('error', function (event) { finish('FAIL: ' + event.message); });
    // Keep every request local: the real API script is replaced at its insertion point.
    var append = document.head.append.bind(document.head);
    document.head.append = function (node) {
        if (node.src === 'https://www.youtube.com/iframe_api') {
            setTimeout(function () {
                try {
                    assert(score() === '0 – 0', 'Initial score leaks results');
                    assert(action('next').disabled, 'Controls enabled before readiness');
                    lifecycle('pagehide');
                    lifecycle('pageshow');
                    lifecycle('pageshow');
                    assert(pollers() === 0 && action('next').disabled,
                        'Lifecycle restore revived an unready controller');
                    window.onYouTubeIframeAPIReady();
                } catch (error) { finish('FAIL: ' + error.message); }
            }, 0);
        } else append(node);
    };
    window.YT = {
        Player: function (id, options) {
            events = options.events;
            var player = {
                getCurrentTime: function () { return clock; },
                getPlayerState: function () { return state; },
                getVideoData: function () { return {video_id: videoId}; },
                seekTo: function (time) { clock = time; },
                playVideo: function () { state = 1; },
                pauseVideo: function () { state = 2; },
                cueVideoById: function (video) {
                    videoId = video.videoId;
                    clock = 0;
                    state = 5;
                }
            };
            setTimeout(function () {
                try {
                    events.onReady();
                    assert(pollers() === 1, 'Ready player did not start exactly one poller');
                    assert(score() === '0 – 0', 'Ready state leaks results');
                    assert(!action('next').disabled, 'Next unavailable with a ready player');
                    action('next').focus();
                    assert(document.activeElement === action('next'), 'Navigation button cannot receive focus');
                    assert(action('repeat').disabled, 'Repeat available before first rally');
                    var spotlightSelect = document.getElementById('replay-spotlight-select');
                    assert(spotlightSelect.options.length === 3, 'Spotlight options omit eligible players');
                    assert(spotlightSelect.options[1].textContent === '#7 · <img src=x>' &&
                        spotlightSelect.options[2].textContent === '#8', 'Spotlight options are not sorted/named');
                    assert(spotlightSelect.value === '8', 'Stored spotlight selection was not restored');
                    assert(!document.getElementById('replay-spotlight').hidden &&
                        document.querySelector('.replay-spotlight-empty').textContent ===
                        'Sin toques registrados en este set', 'Absent player should show zero spotlight');
                    assert(!document.querySelector('#replay-players [data-player="8"]'),
                        'Absent player was added to the table');
                    assert(getComputedStyle(document.querySelector('.replay-spotlight-values'))
                        .gridTemplateColumns.trim().split(/\s+/).length ===
                        (matchMedia('(max-width: 600px)').matches ? 2 : 4),
                        'Spotlight grid has wrong column count');
                    spotlightSelect.value = '7';
                    spotlightSelect.dispatchEvent(new Event('change'));
                    assert(localStorage.getItem('va-replay-player') === '7',
                        'Spotlight selection was not persisted');
                    assert(!document.querySelector('#replay-players img'), 'Player name became HTML');
                    assert(!document.getElementById('replay-rallies').textContent.includes('Completada'),
                        'Future rally rows leak completion');
                    assert(document.getElementById('replay-start-note').hidden,
                        'Zero start should not show note');
                    assert(document.getElementById('replay-scope').textContent ===
                        'Estadísticas del set hasta este momento', 'Legacy scope changed');
                    assert(values('.replay-spotlight-value span').join('|') ===
                        'Toques|Puntos|Errores|Rating', 'Spotlight must show exactly four values');
                    assert(values('#replay-cards .stat-label').join('|') ===
                        'Puntos directos|Kills|Aces|Toques con error|Eficiencia de ataque|Rally m\u00e1s largo',
                        'Wrong team cards or order');
                    clock = 15;
                    update();
                    assert(values('#replay-players tr td').slice(1).join('|') === '1|1|0|10',
                        'Boundary table points/errors incorrect');
                    assert(values('.replay-spotlight-value strong').join('|') === '1|1|0|10',
                        'Boundary spotlight values incorrect');
                    assert(score() === '1 – 0', 'Exact end boundary did not count');
                    assert(document.querySelector('#replay-cards .stat-card:nth-child(2) .stat-value').textContent === '1',
                        'Completed kills incorrect');
                    assert(document.querySelector('#replay-cards .stat-card:last-child .stat-label').textContent ===
                        'Rally más largo', 'Longest rally is not a stat card');
                    assert(document.querySelectorAll('#replay-rallies button').length === 2,
                        'Rally chips were not rendered');
                    assert(document.querySelector('#replay-rallies button[aria-current="true"]').textContent === '1',
                        'Active rally chip is not highlighted');
                    var pinned = document.querySelector('#replay-players tr[aria-current="true"]');
                    assert(pinned && pinned.dataset.player === '7', 'Selected row was not pinned');
                    assert(pinned.querySelector('[aria-hidden="true"]').textContent === '★ ',
                        'Pinned row has no non-color marker');
                    assert(document.querySelector('.replay-spotlight .replay-spotlight-value strong').textContent === '1',
                        'Spotlight did not update live at the rally boundary');
                    var ratingPill = document.querySelector('#replay-spotlight .player-rating');
                    assert(ratingPill.classList.contains('replay-value-pulse'),
                        'Changed rating did not trigger a pulse');
                    // Simulate the finished animation, then reconcile the same paused snapshot.
                    ratingPill.classList.remove('replay-value-pulse');
                    var valueItems = document.querySelectorAll('.replay-spotlight-value');
                    valueItems.forEach(function (item) { item.classList.remove('replay-value-pulse'); });
                    var previousRating = ratingPill.textContent;
                    assert(state === 2, 'Unchanged snapshot regression must run while paused');
                    update();
                    assert(ratingPill.textContent === previousRating &&
                        !ratingPill.classList.contains('replay-value-pulse'),
                        'Unchanged rating re-triggered the pulse while paused');
                    assert(!Array.from(valueItems).some(function (item) {
                        return item.classList.contains('replay-value-pulse');
                    }), 'Unchanged spotlight values pulsed');
                    clock = 12;
                    update();
                    assert(valueItems[0].classList.contains('replay-value-pulse') &&
                        valueItems[1].classList.contains('replay-value-pulse') &&
                        !valueItems[2].classList.contains('replay-value-pulse') &&
                        valueItems[3].classList.contains('replay-value-pulse'),
                        'Only changed spotlight values should pulse on rewind');
                    assert(ratingPill.textContent !== previousRating &&
                        ratingPill.classList.contains('replay-value-pulse'),
                        'Rewinding to a changed rating did not trigger a pulse');
                    assert(score() === '0 – 0', 'Rewind did not restore score');
                    assert(document.querySelector('#replay-cards .stat-card:nth-child(2) .stat-value').textContent === '0',
                        'Rewind did not restore kills');
                    assert(document.querySelector('.replay-spotlight .replay-spotlight-value strong').textContent === '0',
                        'Spotlight did not rewind to zero');
                    assert(!document.querySelector('#replay-players tr[aria-current="true"]'),
                        'Player with no touches was kept in the table');
                    clock = 16;
                    update();
                    assert(document.querySelector('#replay-rallies button[aria-current="true"]').textContent === '1',
                        'Completed rally chip is not highlighted during gap');
                    document.querySelector('#replay-rallies button').click();
                    assert(clock === 10, 'Rally chip did not seek to its start');
                    clock = 16;
                    update();
                    action('next').click();
                    assert(clock === 30 && state === 2, 'Next did not preserve paused intent');
                    clock = 38;
                    update();
                    assert(score() === '1 – 1' && action('next').disabled, 'Final boundary incorrect');
                    assert(values('#replay-players tr td').slice(1, 4).join('|') === '2|1|1',
                        'Error boundary table points/errors incorrect');
                    clock = 16;
                    update();
                    assert(values('#replay-players tr td').slice(1, 4).join('|') === '1|1|0',
                        'Rewind did not restore table points/errors');
                    assert(values('.replay-spotlight-value strong').slice(0, 3).join('|') === '1|1|0',
                        'Rewind did not restore spotlight points/errors');
                    clock = 38;
                    update();
                    var selector = document.getElementById('replay-set');
                    selector.value = '1';
                    selector.dispatchEvent(new Event('change'));
                    assert(score() === '7 – 4' && action('next').disabled, 'Set switch did not reset');
                    assert(document.getElementById('replay-start-note').textContent ===
                        'La grabación inicia con el marcador 7–4.', 'Missing start note');
                    assert(document.getElementById('replay-scope').textContent ===
                        'Estadísticas registradas en la grabación', 'Wrong offset scope');
                    update();
                    assert(videoId === 'ABCDEFGHIJK' && clock === 0, 'Set video clock mapping incorrect');
                    assert(score() === '7 – 4', 'Set switch retained old statistics');
                    clock = 15;
                    update();
                    clock = 12;
                    update();
                    assert(score() === '7 – 4', 'Offset rewind did not restore start');
                    assert(document.querySelector('#replay-cards .stat-card:nth-child(2) .stat-value').textContent === '0',
                        'Offset added phantom kills');
                    spotlightSelect.value = '8';
                    spotlightSelect.dispatchEvent(new Event('change'));
                    clock = 15;
                    update();
                    assert(document.querySelector('#replay-players tr[aria-current="true"]').dataset.player === '8',
                        'Player spotlight did not follow set switching');
                    clock = 38;
                    update();
                    var tableRows = document.querySelectorAll('#replay-players tr');
                    assert(tableRows.length === 2 && tableRows[0].dataset.player === '8',
                        'Pinned row was not moved ahead of the sorted table');
                    spotlightSelect.value = '';
                    spotlightSelect.dispatchEvent(new Event('change'));
                    tableRows = document.querySelectorAll('#replay-players tr');
                    assert(document.getElementById('replay-spotlight').hidden &&
                        !document.querySelector('#replay-players tr[aria-current="true"]') &&
                        tableRows[0].dataset.player === '7' && tableRows[1].dataset.player === '8',
                        'Ninguno did not restore normal player ordering');
                    assert(localStorage.getItem('va-replay-player') === null,
                        'Ninguno was not persisted');
                    // Back/forward cache: pagehide stops polling; pageshow must resume it
                    // and reconcile at once, without onReady and without duplicates.
                    lifecycle('pagehide');
                    assert(pollers() === 0, 'pagehide left a poller running');
                    clock = 38;
                    state = 1;
                    lifecycle('pageshow');
                    assert(score() === '8 – 5', 'pageshow did not reconcile immediately');
                    assert(pollers() === 1, 'pageshow did not restore exactly one poller');
                    lifecycle('pageshow');
                    lifecycle('pagehide');
                    lifecycle('pagehide');
                    lifecycle('pageshow');
                    lifecycle('pageshow');
                    assert(pollers() === 1, 'Repeated lifecycle events duplicated pollers');
                    clock = 15;
                    setTimeout(function () {
                        try {
                            assert(score() === '8 – 4', 'Restored poller does not follow playback');
                            var controls = document.querySelector('.replay-controls');
                            var mobileControls = matchMedia('(max-width: 600px)').matches;
                            assert(getComputedStyle(controls).display === (mobileControls ? 'grid' : 'flex'),
                                'Control bar does not match the responsive layout');
                            if (mobileControls) {
                                assert(getComputedStyle(controls).gridTemplateColumns.trim().split(/\s+/).length === 2,
                                    'Mobile control bar does not use two columns');
                                assert(getComputedStyle(document.querySelector('.replay-control-set')).gridColumnEnd === '-1' &&
                                    getComputedStyle(document.getElementById('replay-youtube')).gridColumnEnd === '-1',
                                    'Set selector and YouTube link must occupy full rows');
                            }
                            assert(document.documentElement.scrollWidth <= window.innerWidth,
                                'Page overflows horizontally');
                            var tableWrap = document.querySelector('.replay-table-wrap');
                            assert(tableWrap.scrollWidth <= tableWrap.clientWidth,
                                'Player table overflows horizontally');
                            var before = getComputedStyle(document.documentElement).getPropertyValue('--surface-2');
                            document.getElementById('themeToggle').click();
                            assert(before !== getComputedStyle(document.documentElement).getPropertyValue('--surface-2'),
                                'Theme toggle did not change theme colors');
                            events.onError();
                            assert(score() === '7 – 4', 'Failure left stale score visible');
                            document.querySelectorAll('[data-replay]').forEach(function (button) {
                                assert(button.disabled, 'Failure left an enabled synchronized control');
                            });
                            assert(document.getElementById('replay-status').textContent.includes('no sincronizadas'),
                                'Failure did not explain unavailable statistics');
                            lifecycle('pagehide');
                            lifecycle('pageshow');
                            assert(pollers() === 0, 'Lifecycle restore revived a failed controller');
                            assert(score() === '7 – 4', 'Lifecycle restore resynchronized after failure');
                            document.querySelectorAll('[data-replay]').forEach(function (button) {
                                assert(button.disabled, 'Lifecycle restore re-enabled a failed control');
                            });
                            finish('PASS');
                        } catch (error) { finish('FAIL: ' + error.message); }
                    }, 1000);
                } catch (error) { finish('FAIL: ' + error.message); }
            }, 0);
            return player;
        }
    };
}());
