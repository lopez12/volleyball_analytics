/* Browser-only DOM checks using a deterministic fake IFrame API, never YouTube. */
(function () {
    'use strict';
    var clock = 0;
    var state = 2;
    var videoId = 'abcdefghijk';
    var events;
    var result = document.createElement('p');
    result.id = 'browser-smoke-result';
    function assert(value, message) { if (!value) throw new Error(message); }
    function score() { return document.getElementById('replay-score').textContent; }
    function action(name) { return document.querySelector('[data-replay="' + name + '"]'); }
    function update() { events.onStateChange(); }
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
                    assert(score() === '0 - 0', 'Initial score leaks results');
                    assert(action('next').disabled, 'Controls enabled before readiness');
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
                    assert(score() === '0 - 0', 'Ready state leaks results');
                    assert(!action('next').disabled, 'Next unavailable with a ready player');
                    action('next').focus();
                    assert(document.activeElement === action('next'), 'Navigation button cannot receive focus');
                    assert(action('repeat').disabled, 'Repeat available before first rally');
                    assert(!document.querySelector('#replay-players img'), 'Player name became HTML');
                    assert(!document.getElementById('replay-rallies').textContent.includes('Completada'),
                        'Future rally rows leak completion');
                    clock = 15;
                    update();
                    assert(score() === '1 - 0', 'Exact end boundary did not count');
                    assert(document.querySelector('#replay-cards strong').textContent === '1',
                        'Completed touches incorrect');
                    clock = 12;
                    update();
                    assert(score() === '0 - 0', 'Rewind did not restore score');
                    assert(document.querySelector('#replay-cards strong').textContent === '0',
                        'Rewind did not restore touches');
                    clock = 16;
                    update();
                    action('next').click();
                    assert(clock === 30 && state === 2, 'Next did not preserve paused intent');
                    clock = 38;
                    update();
                    assert(score() === '1 - 1' && action('next').disabled, 'Final boundary incorrect');
                    var selector = document.getElementById('replay-set');
                    selector.value = '1';
                    selector.dispatchEvent(new Event('change'));
                    assert(score() === '0 - 0' && action('next').disabled, 'Set switch did not reset');
                    update();
                    assert(videoId === 'ABCDEFGHIJK' && clock === 0, 'Set video clock mapping incorrect');
                    assert(score() === '0 - 0', 'Set switch retained old statistics');
                    var columns = getComputedStyle(document.querySelector('.replay-layout'))
                        .gridTemplateColumns.trim().split(/\s+/).length;
                    assert(columns === (matchMedia('(max-width: 800px)').matches ? 1 : 2),
                        'Responsive grid has the wrong column count');
                    assert(document.documentElement.scrollWidth <= window.innerWidth,
                        'Page overflows horizontally');
                    var before = getComputedStyle(document.documentElement).getPropertyValue('--surface-2');
                    document.getElementById('themeToggle').click();
                    assert(before !== getComputedStyle(document.documentElement).getPropertyValue('--surface-2'),
                        'Theme toggle did not change theme colors');
                    events.onError();
                    assert(score() === '0 - 0', 'Failure left stale score visible');
                    document.querySelectorAll('[data-replay]').forEach(function (button) {
                        assert(button.disabled, 'Failure left an enabled synchronized control');
                    });
                    assert(document.getElementById('replay-status').textContent.includes('no sincronizadas'),
                        'Failure did not explain unavailable statistics');
                    finish('PASS');
                } catch (error) { finish('FAIL: ' + error.message); }
            }, 0);
            return player;
        }
    };
}());
