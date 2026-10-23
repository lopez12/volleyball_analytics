/* Run with node tests/viewer_test.js; no npm or browser required. */
'use strict';
var assert = require('assert');
var viewer = require('../viewer.js');
var childProcess = require('child_process');
var payload = JSON.parse(childProcess.execFileSync('python', ['-c',
    'import json; from analytics import parse_log; ' +
    's=parse_log("@youtube: https://youtu.be/abcdefghijk\\n7A# @won @t:10-15\\n7A- @lost @t:30-38")["replay"]["sets"]; ' +
    'print(json.dumps({"sets":s,"names":{"7":"Test"}}))'
], {encoding: 'utf8'}));
var set = payload.sets[0];
assert(viewer.validatePayload(payload));
[
    [0, 0], [12, 0], [14.999, 0], [15, 1], [16, 1],
    [30, 1], [37.999, 1], [38, 2], [100, 2], [12, 0]
].forEach(function (pair) {
    assert.strictEqual(viewer.snapshotIndex(set, pair[0]), pair[1]);
});
assert.strictEqual(viewer.nextRally(set, 16).start, 30);
assert.strictEqual(viewer.nextRally(set, 30), null);
assert.strictEqual(viewer.repeatRally(set, 9), null);
assert.strictEqual(viewer.repeatRally(set, 12).start, 10);
assert.strictEqual(viewer.repeatRally(set, 16).start, 10);
assert.strictEqual(viewer.repeatRally(set, 32).start, 30);
assert.strictEqual(viewer.snapshotIndex({rallies: [{start: 0, end: 0}, {start: 0, end: 0}]}, 0), 2);
assert.strictEqual(viewer.validatePayload({sets: [], names: {}}), false);
var invalid = JSON.parse(JSON.stringify(payload));
invalid.sets[0].rallies[0].end = Infinity;
assert.strictEqual(viewer.validatePayload(invalid), false);
invalid = JSON.parse(JSON.stringify(payload));
invalid.sets[0].snapshots[0].team.touches = 100;
assert.strictEqual(viewer.validatePayload(invalid), false);

var clock = 0;
var state = 2;
var videoId = set.video_id;
var events = [];
var player = {
    getCurrentTime: function () { return clock; },
    getVideoData: function () { return {video_id: videoId}; },
    getPlayerState: function () { return state; },
    seekTo: function (time) { clock = time; events.push(['seek', time]); },
    playVideo: function () { state = 1; },
    pauseVideo: function () { state = 2; },
    cueVideoById: function (video) {
        events.push(['cue', video.videoId, video.startSeconds]);
        // Asynchronous player: retain the old clock until the test confirms reset.
    }
};
var updates = [];
var failures = [];
var second = JSON.parse(JSON.stringify(set));
second.id = 's2';
second.number = 2;
second.video_id = 'ABCDEFGHIJK';
payload.sets.push(second);
var controller = new viewer.Controller(payload, function (s, index, time, available, message) {
    updates.push({set: s.id, index: index, time: time, available: available, message: message});
}, function (message) { failures.push(message); });
controller.seek('next');
assert.deepStrictEqual(events, []);
controller.attach(player);
assert.strictEqual(updates.at(-1).index, 0);
clock = 16;
controller.seek('next');
assert.strictEqual(clock, 30);
assert.strictEqual(state, 2); // paused intent
state = 1;
controller.seek('repeat');
assert.strictEqual(clock, 30);
assert.strictEqual(state, 1); // playing intent
clock = 38;
controller.reconcile();
controller.reconcile();
assert.strictEqual(updates.at(-1).index, 2); // no double counting
clock = 12;
state = 3;
controller.reconcile();
assert.strictEqual(updates.at(-1).index, 0);
assert(updates.at(-1).message.includes('Cargando'));
controller.switchSet(1);
assert.strictEqual(updates.at(-1).index, 0);
assert.strictEqual(updates.at(-1).available, false);
controller.reconcile();
assert.strictEqual(updates.at(-1).available, false);
videoId = second.video_id;
controller.reconcile();
assert.strictEqual(updates.at(-1).available, false); // new ID, stale clock
clock = 0;
controller.reconcile();
assert.strictEqual(updates.at(-1).available, true);
assert.strictEqual(updates.at(-1).index, 0);
// Same-video set switches must also wait for their independent zero clock.
clock = 38;
controller.switchSet(1);
controller.reconcile();
assert.strictEqual(updates.at(-1).available, false);
clock = 0;
controller.reconcile();
assert.strictEqual(updates.at(-1).index, 0);
controller.fail('failure');
controller.seek('next');
assert.strictEqual(failures.length, 1);
assert.strictEqual(controller.time(), null);
var early = new viewer.Controller(payload, function () {}, function () {});
early.switchSet(1);
videoId = set.video_id;
clock = 0;
early.attach(player);
assert.deepStrictEqual(events.at(-1), ['cue', second.video_id, 0]);
videoId = second.video_id;
state = 1;
early.reconcile();
state = 3;
clock = 16;
early.reconcile();
early.seek('next');
assert.strictEqual(clock, 30);
assert.strictEqual(state, 1); // buffering keeps previously playing intent
videoId = 'wrongwrong0';
early.reconcile();
assert.strictEqual(early.failed, true); // never show stats for an unrelated video
var broken = new viewer.Controller(payload, function () {}, function () {});
broken.attach({getVideoData: function () { throw new Error('API disconnected'); }});
assert.strictEqual(broken.failed, true);
videoId = set.video_id;
var disconnected = new viewer.Controller(payload, function () {}, function () {});
disconnected.attach(Object.assign({}, player, {
    getCurrentTime: function () { throw new Error('No current time'); }
}));
assert.strictEqual(disconnected.failed, true);
// First-play seeks must not interrupt the first load with pauseVideo().
function navigationCase(initialState, initialClock, action, expectedStart, intent, asynchronous) {
    var calls = [];
    var mockState = initialState;
    var mockClock = initialClock;
    var mockId = set.video_id;
    var navigation = new viewer.Controller(payload, function () {}, function () {});
    navigation.attach({
        getCurrentTime: function () { return mockClock; },
        getVideoData: function () { return {video_id: mockId}; },
        getPlayerState: function () { return mockState; },
        seekTo: function (time, allowSeekAhead) {
            calls.push(['seek', time, allowSeekAhead]);
            if (!asynchronous) mockClock = time;
        },
        playVideo: function () { calls.push(['play']); if (!asynchronous) mockState = 1; },
        pauseVideo: function () { calls.push(['pause']); mockState = 2; },
        cueVideoById: function () {}
    });
    navigation.playingIntent = !!intent;
    navigation.seek(action, set.rallies[1].id);
    var shouldPlay = initialState === -1 || initialState === 5 ||
        initialState === 1 || (initialState === 3 && intent);
    assert.deepStrictEqual(calls, [
        ['seek', expectedStart, true], [shouldPlay ? 'play' : 'pause']
    ]);
    if (initialState === -1 || initialState === 5) {
        assert.strictEqual(navigation.playingIntent, true);
        // Emulate an asynchronous first load whose clock is still unavailable.
        mockState = initialState;
        mockClock = initialClock;
        navigation.seek('rally', set.rallies[0].id);
        assert.deepStrictEqual(calls.slice(2), [['seek', 10, true], ['play']]);
    }
    calls.length = 0;
    navigation.pending = true;
    mockClock = null;
    mockState = -1;
    navigation.seek('next');
    assert.deepStrictEqual(calls, []); // set switches still guard all navigation
    navigation.pending = false;
    mockId = 'wrongwrong0';
    navigation.seek('rally', set.rallies[0].id);
    assert.deepStrictEqual(calls, []); // never seek an unrelated loaded video
    assert.strictEqual(navigation.failed, true);
}
[-1, 5, 2, 1, 0].forEach(function (initialState) {
    navigationCase(initialState, 0, 'rally', 30);
});
navigationCase(3, 0, 'rally', 30, true);
navigationCase(3, 0, 'rally', 30, false);
[-1, 5].forEach(function (initialState) {
    [null, undefined, NaN].forEach(function (initialClock) {
        navigationCase(initialState, initialClock, 'next', 10);
        navigationCase(initialState, initialClock, 'repeat', 10);
        navigationCase(initialState, initialClock, 'rally', 30);
        navigationCase(initialState, initialClock, 'rally', 30, false, true);
    });
});
// An unavailable clock is not enough to bypass readiness for started players.
[1, 2, 3, 0].forEach(function (initialState) {
    var guarded = new viewer.Controller(payload, function () {}, function () {});
    var calls = [];
    guarded.attach({
        getCurrentTime: function () { return null; },
        getVideoData: function () { return {video_id: set.video_id}; },
        getPlayerState: function () { return initialState; },
        seekTo: function () { calls.push('seek'); }
    });
    guarded.seek('next');
    assert.deepStrictEqual(calls, []);
});
console.log('Viewer tests passed: boundaries, rewind, zero-duration, navigation, first-play seeks, unavailable clocks, readiness, buffering, set resets, validation and failure.');
