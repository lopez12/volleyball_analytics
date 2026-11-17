/* Real logger UI/import/export/IndexedDB checks; no production test hooks. */
(function () {
    'use strict';
    var expected = '@set: 8-5\n@start: 7-4\n7A# @won @t:10-15\n7A- @lost @t:30-38\n---\n@set: 1-0\n@won:se @t:0-0';
    function assert(value, message) { if (!value) throw new Error(message); }
    function el(id) { return document.getElementById(id); }
    function input(selector, value) {
        var node = document.querySelector(selector);
        node.value = value;
        node.dispatchEvent(new Event('input', {bubbles: true}));
    }
    function waitFor(predicate, label) {
        return new Promise(function (resolve, reject) {
            var attempts = 0;
            function check() {
                try {
                    if (predicate()) { resolve(); return; }
                    if (++attempts > 100) throw new Error('Timed out waiting for logger state: ' + label + '; review=' + (el('review-log') && el('review-log').textContent));
                    // Network-backed turns let real IndexedDB I/O settle under virtual time.
                    fetch('datasets.js', {cache: 'no-store'}).then(function () {
                        setTimeout(check, 20);
                    }, reject);
                } catch (error) { reject(error); }
            }
            check();
        });
    }
    function review() {
        location.hash = '#review';
        window.dispatchEvent(new Event('hashchange'));
        return el('review-log').textContent;
    }
    function analysisScreen() {
        location.hash = '#analysis';
        window.dispatchEvent(new Event('hashchange'));
    }
    function layout() {
        var workspace = document.querySelector('.lg-analysis');
        var side = document.querySelector('.lg-analysis__side');
        var scroll = document.querySelector('.lg-analysis__controls');
        var footer = document.querySelector('.lg-analysis__submit');
        var video = el('analysis-video').getBoundingClientRect();
        var actions = Array.from(document.querySelectorAll('[data-action]'));
        assert(document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
            'Analysis page overflows');
        actions.forEach(function (button) {
            var box = button.getBoundingClientRect();
            assert(box.width >= 44 && box.height >= 44 && button.title.includes(button.dataset.action),
                'Compact action lacks size or full-name tooltip');
        });
        if (innerWidth >= 1024) {
            window.scrollTo(0, window.scrollY + workspace.getBoundingClientRect().top - 16);
            var bounds = footer.getBoundingClientRect();
            assert(bounds.top >= 16 && bounds.bottom <= innerHeight - 15,
                'Submit footer outside viewport: ' + JSON.stringify(bounds.toJSON()));
            assert(actions.every(function (button) {
                return Math.abs(button.getBoundingClientRect().top - actions[0].getBoundingClientRect().top) < 1;
            }), 'Desktop actions do not share one row');
            var pageScroll = window.scrollY;
            scroll.scrollTop = scroll.scrollHeight;
            assert((scroll.scrollHeight <= scroll.clientHeight + 1 || scroll.scrollTop > 0) &&
                window.scrollY === pageScroll, 'Sidebar does not scroll independently');
            scroll.scrollTop = 0;
        } else {
            assert(getComputedStyle(side).display === 'contents' &&
                getComputedStyle(scroll).display === 'contents', 'Mobile sidebar is a nested scroller');
            assert(footer.getBoundingClientRect().bottom <= document.querySelector('.lg-a-rallies')
                .getBoundingClientRect().top, 'Mobile submission follows history');
            assert(actions.every(function (button) {
                return getComputedStyle(button.querySelector('small')).position !== 'absolute';
            }), 'Mobile action names are visually hidden');
        }
        return {width: video.width, height: video.height};
    }
    function importLog(text) {
        var transfer = new DataTransfer();
        transfer.items.add(new File([text], 'test.txt', {type: 'text/plain'}));
        var node = el('lg-import-file');
        node.files = transfer.files;
        node.dispatchEvent(new Event('change'));
        return waitFor(function () { return review() === expected; }, 'import');
    }
    function records() {
        return new Promise(function (resolve, reject) {
            var request = indexedDB.open('registro-partido', 1);
            request.onsuccess = function () {
                var db = request.result;
                var tx = db.transaction('drafts', 'readonly');
                var read = tx.objectStore('drafts').getAll();
                read.onsuccess = function () {
                    resolve(read.result.sort(function (a, b) { return b.updatedAt - a.updatedAt; }));
                };
                tx.oncomplete = function () { db.close(); };
                tx.onerror = function () { reject(tx.error); };
            };
            request.onerror = function () { reject(request.error); };
        });
    }
    function saveLegacyDraft(record) {
        record.sets.forEach(function (set) { delete set.sv; delete set.sr; });
        record.analysis.sets.forEach(function (set) { delete set.start_score; });
        if (record.session) record.session.sets.forEach(function (set) { delete set.start_score; });
        return new Promise(function (resolve, reject) {
            var request = indexedDB.open('registro-partido', 1);
            request.onsuccess = function () {
                var db = request.result;
                var tx = db.transaction('drafts', 'readwrite');
                tx.objectStore('drafts').put(record);
                tx.oncomplete = function () { db.close(); resolve(); };
                tx.onerror = function () { reject(tx.error); };
            };
            request.onerror = function () { reject(request.error); };
        });
    }
    function finish(message) {
        var node = document.createElement('p');
        node.id = 'browser-smoke-result';
        node.textContent = message;
        document.body.append(node);
        document.body.dataset.testViewport = String(innerWidth);
        if (window.parent !== window) window.parent.postMessage({
            type: 'replay-smoke', message: message, viewport: innerWidth
        }, location.origin);
    }
    window.addEventListener('error', function (event) { finish('FAIL: ' + event.message); });
    window.addEventListener('DOMContentLoaded', function () {
        var query = new URLSearchParams(location.search);
        if (query.has('theme')) document.documentElement.dataset.theme = query.get('theme');
        waitFor(function () { return document.querySelector('.lg-set__start-v'); }, 'initial render').then(async function () {
            if (sessionStorage.getItem('logger-start-phase') === 'legacy') {
                assert(document.querySelector('.lg-set__start-v').value === '', 'Old draft has team offset');
                assert(document.querySelector('.lg-set__start-r').value === '', 'Old draft has rival offset');
                assert(review() === expected.replace('@start: 7-4\n', ''), 'Old draft export changed');
                sessionStorage.removeItem('logger-start-phase');
                finish('PASS');
                return;
            }
            if (sessionStorage.getItem('logger-start-phase') === 'reload') {
                assert(document.querySelector('.lg-set__start-v').value === '7', 'Draft lost team start');
                assert(document.querySelector('.lg-set__start-r').value === '4', 'Draft lost rival start');
                assert(review() === expected, 'Draft lost imported/exported start score');
                var stored = await records();
                assert(stored[0].analysis.sets[0].start_score === '7-4', 'Analysis start not persisted');
                assert(stored[0].sets[0].sv === '7', 'Setup start not persisted');
                // Old logs without the token still import and export unchanged.
                expected = expected.replace('@start: 7-4\n', '');
                await importLog(expected);
                assert(document.querySelector('.lg-set__start-v').value === '', 'Legacy import retained start');
                assert(document.querySelector('.lg-set__start-r').value === '', 'Legacy import retained rival start');
                stored = await records();
                await saveLegacyDraft(stored[0]);
                sessionStorage.setItem('logger-start-phase', 'legacy');
                location.reload();
                return;
            }
            el('home-new').click();
            location.hash = '#setup';
            input('#setup-dataset', 'test/test');
            input('#setup-opponent', 'Rival');
            input('#setup-order', '01');
            input('.lg-set__score-v', '8');
            input('.lg-set__score-r', '5');
            input('.lg-set__start-v', '7');
            assert(el('setup-start').disabled, 'Incomplete start accepted');
            assert(document.querySelector('.lg-set__start-error').textContent.includes('incompleto'), 'No inline error');
            input('.lg-set__start-r', '-1');
            assert(el('setup-start').disabled, 'Negative start accepted');
            input('.lg-set__start-r', '4.5');
            assert(el('setup-start').disabled, 'Fractional start accepted');
            input('.lg-set__start-r', '4');
            assert(!el('setup-start').disabled, 'Valid start rejected');
            assert(!document.querySelector('.lg-set__start-error').textContent, 'Inline error not cleared');
            el('setup-start').click();
            assert(review() === '@set: 8-5\n@start: 7-4', 'Setup start not exported');
            if (query.has('layout')) {
                analysisScreen();
                var shortSize = layout();
                var addTouch = function () {
                    document.querySelector('[data-player="7"]').click();
                    document.querySelector('[data-action="A"]').click();
                    document.querySelector('[data-grade="+"]').click();
                };
                for (var touch = 0; touch < 100; touch++) addTouch();
                assert(el('analysis-chain').textContent.split(' ').length === 100,
                    'Long active chain did not retain all touches');
                el('analysis-undo').click();
                addTouch();
                assert(!el('analysis-send').disabled, 'Send remains disabled after touches');
                var longSize = layout();
                assert(Math.abs(longSize.width - shortSize.width) <= 1 &&
                    Math.abs(longSize.height - shortSize.height) <= 1, 'Long active chain resized video');
                el('analysis-send').click();
                for (var rally = 0; rally < 101; rally++) {
                    addTouch();
                    el('analysis-send').click();
                }
                document.querySelector('[data-rally-toggle]').click();
                var expanded = layout();
                assert(Math.abs(expanded.width - shortSize.width) <= 1 &&
                    Math.abs(expanded.height - shortSize.height) <= 1, 'Expanded history resized video');
                var exported = review();
                assert(exported.includes(Array(100).fill('7A+').join(' ')),
                    'Visual wrapping changed exported token line');
                analysisScreen();
                document.querySelector('[data-edit="0"]').click();
                layout();
                el('analysis-send').click();
                document.querySelector('[data-del="1"]').click();
                layout();
                finish('PASS');
                return;
            }
            // Import explicit zero in set 2; export must omit it without losing rallies/timestamps.
            await importLog(expected.replace('@set: 1-0\n', '@set: 1-0\n@start: 0-0\n'));
            assert(review() === expected, 'Import/export canonical round-trip failed');
            await importLog(review());
            assert(review() === expected, 'Export/import round-trip failed');
            // Per-set @role: lines survive import/export in their own set and never become rallies.
            var plain = expected;
            expected = '@set: 8-5\n@start: 7-4\n@role: 7=S\n@role: 7=XX\n7A# @won @t:10-15\n7A- @lost @t:30-38\n---\n@set: 1-0\n@role: 7=OPP, 8=mb\n@won:se @t:0-0';
            await importLog('@role: 7=S\n@role: 7=XX\n@set: 8-5\n@start: 7-4\n7A# @won @t:10-15\n7A- @lost @t:30-38\n---\n@set: 1-0\n@role: 7=OPP, 8=mb\n@won:se @t:0-0');
            assert(review() === expected, 'Role lines not preserved per set');
            var roleRecords = [];
            await waitFor(function () {
                records().then(function (list) { roleRecords = list; });
                var sets = roleRecords.length && roleRecords[0].analysis && roleRecords[0].analysis.sets;
                return sets && sets.length === 2 && sets[0].roles.join('|') === '@role: 7=S|@role: 7=XX' &&
                    sets[1].roles.join('|') === '@role: 7=OPP, 8=mb' &&
                    sets[0].rallies.length === 2 && sets[1].rallies.length === 1;
            }, 'role persistence');
            expected = plain;
            await importLog(expected);
            location.hash = '#setup';
            window.dispatchEvent(new Event('hashchange'));
            assert(document.documentElement.scrollWidth <= innerWidth, 'Logger overflows viewport');
            // Wait for the actual persisted transaction, not merely the in-memory draft.
            var saved = false;
            await waitFor(function () {
                records().then(function (list) {
                    saved = list.some(function (d) {
                        return d.analysis && d.analysis.sets[0].start_score === '7-4' && d.sets[0].sv === '7';
                    });
                });
                return saved;
            }, 'IndexedDB save');
            sessionStorage.setItem('logger-start-phase', 'reload');
            location.reload();
        }).catch(function (error) { finish('FAIL: ' + error.message); });
    });
}());
