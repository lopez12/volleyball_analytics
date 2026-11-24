"""Run controller and mocked-player DOM tests in an existing Chromium browser.

Usage: python tests/browser_smoke.py "C:\\path\\to\\msedge.exe"
The temporary HTTP server and browser are bounded and closed before returning.
This does not verify real YouTube playback or substitute for Node's test run.
"""

import functools
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate  # noqa: E402
from analytics import parse_log  # noqa: E402
from renderer import render_index_page, render_match_page, render_root_index_page, render_watch_page  # noqa: E402


def main():
    """Serve temporary parser fixtures and run the shared JS assertions."""
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tests = root / 'tests'
        tests.mkdir()
        for name in ('browser_test.html', 'viewer_test.js'):
            shutil.copy(repo / 'tests' / name, tests / name)
        shutil.copy(repo / 'viewer.js', root / 'viewer.js')
        shutil.copy(repo / 'styles.css', root / 'styles.css')
        shutil.copy(repo / 'tests' / 'viewer_dom_test.js', root / 'viewer_dom_test.js')
        log = (
            '@youtube: https://youtu.be/abcdefghijk\n7A# @won @t:10-15\n'
            '7A- @lost @t:30-38\n@set: 1-1'
        )
        payload = {'sets': parse_log(log)['replay']['sets'], 'names': {'7': 'Test'}}
        (tests / 'fixture.json').write_text(json.dumps(payload), encoding='utf-8')
        mixed = parse_log(
            log
            + '\n---\n'
            + '@start: 7-4\n'
            + log.replace('7A#', '8A#')
            .replace('abcdefghijk', 'ABCDEFGHIJK')
            .replace('@set: 1-1', '@set: 8-5')
        )['replay']
        boundaries = parse_log(
            '@youtube: https://youtu.be/abcdefghijk\n@start: 3-6\n'
            '7A# @won @t:10-15\n7A- @lost @t:15-20\n@won:se @t:20-20'
        )['replay']['sets'][0]
        boundaries['id'] = 'boundaries'
        boundaries['number'] = 3
        inconsistent = parse_log(log)['replay']['sets'][0]
        inconsistent['id'] = 'inconsistent'
        inconsistent['number'] = 4
        inconsistent['snapshots'][2]['score'] = [0, 2]
        unverified = parse_log('@youtube: https://youtu.be/abcdefghijk\n7A# @won @t:10-15')[
            'replay'
        ]['sets'][0]
        unverified['id'] = 'unverified'
        unverified['number'] = 5
        mixed['sets'].extend([boundaries, inconsistent, unverified])
        page = render_watch_page('Synthetic test', mixed, {'7': '<img src=x>'}, 'report.html')
        page = page.replace(
            '<script src="viewer.js" defer></script>',
            '<script src="viewer_dom_test.js"></script><script src="viewer.js" defer></script>',
        )
        (root / 'watch.html').write_text(page, encoding='utf-8')
        # Chromium's desktop window has a minimum width. An iframe gives the
        # viewer an actual 375 CSS-pixel viewport instead of claiming a mobile
        # test from a silently clamped outer window.
        (root / 'mobile.html').write_text(
            """<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body>
<p id="browser-smoke-result">RUNNING</p>
<script>
window.addEventListener('message', function (event) {
  if (event.origin !== location.origin || event.data.type !== 'replay-smoke') return;
  document.getElementById('browser-smoke-result').textContent = event.data.message;
  document.body.dataset.testViewport = String(event.data.viewport);
});
</script>
<iframe title="375px viewer test" src="watch.html" style="width:375px;height:1000px;border:0"></iframe>
</body></html>""",
            encoding='utf-8',
        )
        (root / 'mobile-dark.html').write_text(
            (root / 'mobile.html')
            .read_text(encoding='utf-8')
            .replace('src="watch.html"', 'src="watch.html?theme=dark"'),
            encoding='utf-8',
        )
        # Exercise the real roster at the screenshot's mid-set snapshot too.
        dataset = repo / 'teams' / 'nova' / 'atlas-chapalita-cup-2026'
        real_replay = parse_log(
            (dataset / 'matches' / '04_cuervas.txt').read_text(encoding='utf-8')
        )['replay']
        roster = json.loads((dataset / 'team.json').read_text(encoding='utf-8'))['roster']
        real_page = render_watch_page(
            'Nova vs Cuervas',
            real_replay,
            {number: player['name'] for number, player in roster.items()},
            '04_cuervas.html',
            'Nova',
            'Cuervas',
        )
        real_test = """<script>
var theme = new URLSearchParams(location.search).get('theme');
if (theme) document.documentElement.dataset.theme = theme;
localStorage.setItem('va-replay-player', '5');
var append = document.head.append.bind(document.head);
document.head.append = function (node) {
  if (node.src === 'https://www.youtube.com/iframe_api') {
    setTimeout(function () { window.onYouTubeIframeAPIReady(); }, 0);
  } else append(node);
};
window.YT = {Player: function (id, options) {
  var payload = JSON.parse(document.getElementById('replay-data').textContent);
  var player = {
    getCurrentTime: function () { return 447; },
    getPlayerState: function () { return 2; },
    getVideoData: function () { return {video_id: payload.sets[0].video_id}; }
  };
  setTimeout(function () {
    options.events.onReady();
    var wrap = document.querySelector('.replay-table-wrap');
    var pinned = document.querySelector('#replay-players tr[aria-current="true"]');
    var controls = document.querySelector('.replay-controls');
    var fallback = document.getElementById('replay-youtube');
    var pass = fallback.hidden && !controls.contains(fallback) && controls.children.length === 3
      && controls.scrollWidth <= controls.clientWidth
      && Math.abs(document.getElementById('replay-set').getBoundingClientRect().top
        - document.querySelector('[data-replay="repeat"]').getBoundingClientRect().top) <= 6
      && Math.abs(document.querySelector('[data-replay="repeat"]').getBoundingClientRect().top
        - document.querySelector('[data-replay="next"]').getBoundingClientRect().top) <= 2
      && (innerWidth < 375 || wrap.scrollWidth <= wrap.clientWidth) && pinned && pinned.dataset.player === '5'
      && document.getElementById('replay-current').textContent.includes('23');
    var result = document.createElement('p');
    result.id = 'browser-smoke-result';
    result.textContent = pass ? 'PASS' : 'FAIL: real roster layout ' + JSON.stringify({
      table:[wrap.scrollWidth,wrap.clientWidth], controls:[controls.scrollWidth,controls.clientWidth],
      set:document.getElementById('replay-set').getBoundingClientRect().toJSON(),
      repeat:document.querySelector('[data-replay="repeat"]').getBoundingClientRect().toJSON(),
      current:document.getElementById('replay-current').textContent
    });
    document.body.append(result);
    document.body.dataset.testViewport = String(window.innerWidth);
    window.parent.postMessage({type: 'replay-smoke', message: result.textContent,
      viewport: window.innerWidth}, location.origin);
    window.dispatchEvent(new Event('pagehide'));
  }, 0);
  return player;
}};
</script>"""
        (root / 'real-watch.html').write_text(
            real_page.replace(
                '<script src="viewer.js" defer></script>',
                real_test + '<script src="viewer.js" defer></script>',
            ),
            encoding='utf-8',
        )
        report_log = (
            '@youtube: https://youtu.be/abcdefghijk\n'
            '7S+ 7R! 7R- 7E# 7E+ 7A# 7A+ 7D! 7D- 7B# 7B+ '
            '@won @t:10-15\n@set: 1-0'
        )
        report = parse_log((report_log + '\n---\n') * 5 + report_log)
        report_page = render_match_page(
            'Equipo vs Rival', report, '17/11/2026', report['replay'], 'real-watch.html'
        )
        (root / 'report.html').write_text(
            report_page.replace(
                '</body>',
                """<script>
document.documentElement.dataset.theme = new URLSearchParams(location.search).get('theme') || 'light';
window.parent.postMessage({type:'replay-smoke', message:'PASS'}, location.origin);
</script></body>""",
            ),
            encoding='utf-8',
        )
        root_hub = render_root_index_page(
            [
                {
                    'team': 'Nova',
                    'tournament': 'Atlas Chapalita Cup',
                    'type': 'tournament',
                    'active': True,
                    'objectives': [
                        {'label': 'Top 4', 'baseline': 12, 'current': 3, 'target': 4},
                        {'label': 'Derbis', 'current': 1, 'target': 2},
                        {'label': 'Aces', 'current': 999, 'target': 1000},
                    ],
                    'href': 'nova/copa/index.html',
                    'season_href': 'nova/copa/team_season.html',
                    'players_href': 'nova/copa/players.html',
                    'matches_href': 'nova/copa/matches.html',
                    'latest_match': {
                        'title': 'Nova vs Rival',
                        'href': 'nova/copa/01_rival.html',
                        'result': 'W',
                        'set_scores': [(25, 20), (22, 25), (15, 12)],
                        'rating': 8.0,
                    },
                    'rating': 7.4,
                    'matches_played': 3,
                    'wins': 2,
                    'losses': 1,
                },
                {
                    'team': 'Vodkas',
                    'tournament': 'Amistosos',
                    'type': 'friendly',
                    'href': 'vodkas/amistosos/index.html',
                    'rating': 5.9,
                    'matches_played': 2,
                    'wins': 1,
                    'losses': 1,
                },
            ],
            '23/11/2026',
        )
        root_hub = root_hub.replace(
            '</body>',
            """<script>
document.documentElement.dataset.theme = new URLSearchParams(location.search).get('theme') || 'light';
window.parent.postMessage({type:'replay-smoke', message:'PASS'}, location.origin);
</script></body>""",
        )
        (root / 'root-hub.html').write_text(root_hub, encoding='utf-8')
        dataset_hub = render_index_page(
            [{'title': 'Nova vs Rival', 'file': '01_rival.html', 'rating': 7.3, 'result': 'W'}],
            '23/11/2026',
            'Nova',
            'Copa',
            player_summaries=[{'name': 'Gio', 'rating': 8.0, 'position': 'OH', 'player_num': '7'}],
            team_season_summary={
                'rating': 7.4,
                'matches_played': 1,
                'wins': 1,
                'losses': 0,
            },
            objectives=[{'label': 'Top 4', 'current': 3, 'baseline': 12, 'target': 4}],
        )
        dataset_hub = dataset_hub.replace(
            '</body>',
            """<script>
document.documentElement.dataset.theme = new URLSearchParams(location.search).get('theme') || 'light';
window.parent.postMessage({type:'replay-smoke', message:'PASS'}, location.origin);
</script></body>""",
        )
        (root / 'dataset-hub.html').write_text(dataset_hub, encoding='utf-8')
        chart_source = root / 'chart-source'
        chart_matches = chart_source / 'matches'
        chart_matches.mkdir(parents=True)
        (chart_source / 'team.json').write_text(
            json.dumps(
                {
                    'team': 'Nova',
                    'tournament': 'Charts',
                    'active': True,
                    'roster': {'7': {'name': 'Gio', 'position': 'OH'}},
                }
            ),
            encoding='utf-8',
        )
        chart_fixtures = [(3, 2, 1, 4), (5, 0, 1, 4), (1, 1, 3, 5), (0, 0, 0, 0)]
        for index, (perfect, positive, regular, error) in enumerate(chart_fixtures, 1):
            actions = ['7A#'] * perfect + ['7A+'] * positive + ['7A!'] * regular + ['7A-'] * error
            if not actions:
                actions = ['7S+']
            (chart_matches / f'{index:02}_rival{index}.txt').write_text(
                ' '.join(actions), encoding='utf-8'
            )
        chart_site = root / 'chart-site'
        chart_data = root / 'chart-data'
        with (
            patch.object(generate, 'DOCS_ROOT', chart_site),
            patch.object(generate, 'DATA_ROOT', chart_data),
            redirect_stdout(StringIO()),
        ):
            generate._generate_dataset('nova', 'charts', chart_source, '23/11/2026')
        chart_page = chart_site / 'nova' / 'charts' / 'team_season.html'
        chart_html = chart_page.read_text(encoding='utf-8').replace(
            '</body>',
            """<script>
window.addEventListener('load', function () {
  setTimeout(async function () {
    var status = document.createElement('p');
    status.id = 'chart-browser-result';
    function assert(value, message) { if (!value) throw new Error(message); }
    function assertDismissed(chart, message) {
      assert(chart.getActiveElements().length === 0 &&
        (!chart.tooltip || chart.tooltip.dataPoints.length === 0), message);
    }
    function chartFor(id) {
      return Object.values(Chart.instances).find(function (chart) {
        return chart.canvas.id === id;
      });
    }
    function touch(chart, type, x, y, id) {
      chart.canvas.dispatchEvent(new PointerEvent(type, {
        bubbles:true, pointerType:'touch', pointerId:id || 21, isPrimary:true,
        clientX:x, clientY:y
      }));
    }
    try {
      if (!window.Chart || !Chart.version) {
        status.textContent = 'BLOCKED: Chart.js CDN did not load';
      } else if (!window.matchMedia('(max-width: 600px)').matches ||
          navigator.maxTouchPoints <= 0) {
        status.textContent = 'BLOCKED: Chromium did not provide a touch-enabled mobile viewport';
      } else {
        var action = chartFor('chart-team-action-a');
        var other = chartFor('chart-team-rating');
        var points = chartFor('chart-points');
        assert(action && other && points, 'Rendered season charts were not instantiated');
        assert(JSON.stringify(action.data.datasets[0].data) === '[50,50,20,null]',
          'Actual Chart.js positive series values differ');
        assert(JSON.stringify(action.data.datasets[1].data) === '[50,50,80,null]',
          'Actual Chart.js complementary series values differ');
        assert(action.data.datasets.length === 2 &&
          action.data.datasets[0].label === 'Positivas (#/+)' &&
          action.data.datasets[1].label === 'Regulares y errores (!/-)',
          'Chart series labels or count changed');
        assert(action.data.datasets[0].spanGaps !== true &&
          action.data.datasets[1].spanGaps !== true, 'Chart spans a missing attempt');
        var rect = action.canvas.getBoundingClientRect();
        var point = action.getDatasetMeta(0).data[0].getCenterPoint();
        var x = rect.left + point.x, y = rect.top + point.y;
        action.canvas.dispatchEvent(new MouseEvent('mousemove', {
          bubbles:true, clientX:x, clientY:y
        }));
        assert(action.getActiveElements().length > 0, 'Desktop hover no longer activates a chart point');
        action.canvas.dispatchEvent(new MouseEvent('mouseout', {
          bubbles:true, clientX:rect.left - 1, clientY:rect.top - 1
        }));
        assertDismissed(action, 'Leaving the plot did not clear hover state');
        var legendBox = action.legend.legendHitBoxes[0];
        var legendClick = function() {
          action.canvas.dispatchEvent(new MouseEvent('click', {
            bubbles:true, clientX:rect.left + legendBox.left + legendBox.width / 2,
            clientY:rect.top + legendBox.top + legendBox.height / 2
          }));
        };
        var hiddenBefore = action.getDatasetMeta(0).hidden;
        legendClick();
        assert(action.getDatasetMeta(0).hidden !== hiddenBefore, 'Chart.js legend did not toggle its series');
        legendClick();
        assert(action.getDatasetMeta(0).hidden === hiddenBefore, 'Chart.js legend could not restore its series');
        touch(action, 'pointerdown', x, y);
        touch(action, 'pointerup', x, y);
        assert(action.getActiveElements().length === 2 &&
          action.tooltip.dataPoints.length === 2, 'Touch tap did not activate tooltip and points');
        var nextPoint = action.getDatasetMeta(0).data[1].getCenterPoint();
        var nextX = rect.left + nextPoint.x, nextY = rect.top + nextPoint.y;
        touch(action, 'pointerdown', nextX, nextY);
        touch(action, 'pointerup', nextX, nextY);
        assert(action.getActiveElements().length === 2 &&
          action.getActiveElements().every(function(element) { return element.index === 1; }),
          'Tapping another match point did not update selection');
        touch(action, 'pointerdown', nextX, nextY);
        touch(action, 'pointerup', nextX, nextY);
        assertDismissed(action, 'Same-point tap did not dismiss selection');
        touch(action, 'pointerdown', x, y);
        touch(action, 'pointerup', x, y);
        document.body.dispatchEvent(new PointerEvent('pointerdown', {
          bubbles:true, pointerType:'touch', pointerId:22, clientX:5, clientY:5
        }));
        document.body.dispatchEvent(new PointerEvent('pointerup', {
          bubbles:true, pointerType:'touch', pointerId:22, clientX:5, clientY:5
        }));
        assertDismissed(action, 'Outside tap did not dismiss selection');
        touch(action, 'pointerdown', x, y);
        touch(action, 'pointerup', x, y);
        document.dispatchEvent(new Event('scroll', {bubbles:true}));
        assertDismissed(action, 'Scroll did not dismiss selection');
        touch(action, 'pointerdown', x, y);
        document.dispatchEvent(new Event('pointercancel'));
        assertDismissed(action, 'Pointer cancel did not dismiss selection');
        touch(action, 'pointerdown', x, y);
        touch(action, 'pointerup', x, y);
        document.dispatchEvent(new Event('touchcancel'));
        assertDismissed(action, 'Touch cancel did not dismiss selection');
        touch(action, 'pointerdown', x, y);
        touch(action, 'pointerup', x, y);
        document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
        assertDismissed(action, 'Escape did not dismiss selection');
        touch(action, 'pointerdown', x, y);
        touch(action, 'pointerup', x, y);
        var previousScroll = window.scrollY;
        window.scrollBy(0, 100);
        await new Promise(function(resolve) { requestAnimationFrame(resolve); });
        assert(window.scrollY > previousScroll, 'Page could not scroll natively after chart selection');
        assertDismissed(action, 'Native page scrolling left a tooltip selected');
        rect = action.canvas.getBoundingClientRect();
        point = action.getDatasetMeta(0).data[0].getCenterPoint();
        x = rect.left + point.x;
        y = rect.top + point.y;
        touch(action, 'pointerdown', x, y);
        touch(action, 'pointerup', x, y);
        var otherPoint = other.getDatasetMeta(0).data[0].getCenterPoint();
        var otherRect = other.canvas.getBoundingClientRect();
        touch(other, 'pointerdown', otherRect.left + otherPoint.x,
          otherRect.top + otherPoint.y, 23);
        touch(other, 'pointerup', otherRect.left + otherPoint.x,
          otherRect.top + otherPoint.y, 23);
        assert(action.getActiveElements().length === 0 && other.getActiveElements().length > 0,
          'Selecting another chart left the previous tooltip active');
        assert(!action.tooltip.dataPoints.length && other.tooltip.dataPoints.length,
          'Selecting another chart did not transfer tooltip state');
        var pointsRect = points.canvas.getBoundingClientRect();
        var pointsPoint = points.getDatasetMeta(0).data[0].getCenterPoint();
        touch(points, 'pointerdown', pointsRect.left + pointsPoint.x,
          pointsRect.top + pointsPoint.y, 24);
        touch(points, 'pointerup', pointsRect.left + pointsPoint.x,
          pointsRect.top + pointsPoint.y, 24);
        assertDismissed(other, 'Selecting the BP/SO chart left the previous chart active');
        assert(points.getActiveElements().length > 0 && points.tooltip.dataPoints.length > 0,
          'BP/SO chart did not support touch selection');
        var previousTheme = document.documentElement.getAttribute('data-theme');
        document.documentElement.setAttribute('data-theme', previousTheme === 'dark' ? 'light' : 'dark');
        await new Promise(function(resolve) { requestAnimationFrame(resolve); });
        var successToken = getComputedStyle(document.documentElement)
          .getPropertyValue('--success').trim();
        assert(action.data.datasets[0].borderColor === successToken,
          'Action-series color did not follow the current theme token');
        var textToken = getComputedStyle(document.documentElement)
          .getPropertyValue('--text-main').trim();
        assert(action.options.plugins.legend.labels.color === textToken,
          'Action-series legend labels did not follow the current theme token');
        status.textContent = 'PASS Chart.js ' + Chart.version + ' · ' +
          window.innerWidth + 'px · touch points ' + navigator.maxTouchPoints + ' · ' +
          navigator.userAgent;
      }
    } catch (error) {
      status.textContent = 'FAIL: ' + error.message;
    }
    document.body.append(status);
    window.dispatchEvent(new Event('pagehide'));
  }, 0);
});
</script></body>""",
        )
        (root / 'chart-test.html').write_text(chart_html, encoding='utf-8')
        (root / 'real-mobile.html').write_text(
            (root / 'mobile.html')
            .read_text(encoding='utf-8')
            .replace('src="watch.html"', 'src="real-watch.html"'),
            encoding='utf-8',
        )
        shutil.copytree(repo / 'logger', root / 'logger')
        shutil.copy(repo / 'tests' / 'logger_dom_test.js', root / 'logger' / 'logger_dom_test.js')
        logger_page = (root / 'logger' / 'index.html').read_text(encoding='utf-8')
        logger_page = logger_page.replace(
            '</body>', '<script src="logger_dom_test.js"></script></body>'
        )
        (root / 'logger' / 'index.html').write_text(logger_page, encoding='utf-8')
        (root / 'logger' / 'datasets.js').write_text(
            'window.LOGGER_DATASETS = '
            + json.dumps(
                [
                    {
                        'team_slug': 'test',
                        'tournament_slug': 'test',
                        'team': 'Test',
                        'tournament': 'Test',
                        'roster': {'7': {'name': 'Test'}},
                    }
                ]
            )
            + ';',
            encoding='utf-8',
        )
        (root / 'logger-mobile.html').write_text(
            (root / 'mobile.html')
            .read_text(encoding='utf-8')
            .replace('src="watch.html"', 'src="logger/index.html"'),
            encoding='utf-8',
        )
        (root / 'layout-matrix.html').write_text(
            """<!DOCTYPE html><html><meta charset="utf-8"><title>Responsive matrix</title>
<body><p id="browser-smoke-result">RUNNING</p><pre id="measurements"></pre>
<iframe title="Measured application viewport" style="border:0"></iframe>
<script>
var frame = document.querySelector('iframe');
var result = document.getElementById('browser-smoke-result');
var sizes = [[320,740],[375,812],[390,844],[600,900],[601,900],[768,1024],
  [844,390],[899,900],[900,900],[1023,768],[1024,600],[1279,768],
  [1280,800],[1366,768],[1440,900],[1920,1080],[683,384]];
var cases = [];
['light','dark'].forEach(function(theme) {
  sizes.forEach(function(size) {
    ['real-watch.html','report.html','root-hub.html','dataset-hub.html',
      'logger/index.html'].forEach(function(path) {
      cases.push({theme:theme, width:size[0], height:size[1], path:path});
    });
  });
});
var current = -1;
function assert(value, message) { if (!value) throw new Error(message); }
function checkHubScore(score, width) {
  var header = score.querySelector('.hub-score-header');
  var area = score.querySelector('.hub-score-sets');
  assert(header && area && header.nextElementSibling === area, 'Missing separate scores area');
  ['.hub-score-label', '.hub-score-title', '.result-badge', '.hub-score-rating'].forEach(function(selector) {
    assert(header.querySelector(selector), 'Missing scoreboard header field: ' + selector);
  });
  var head = header.getBoundingClientRect(), sets = area.getBoundingClientRect();
  assert(sets.top >= head.bottom && Math.abs(sets.left - head.left) <= 1 &&
    Math.abs(sets.right - head.right) <= 1, 'Scores not in a full-width area below the header');
  assert(area.querySelector('.hub-sets-label').textContent === 'Marcador por set:', 'Missing scores label');
  var entries = Array.from(area.querySelectorAll('ol > li'));
  var expected = ['25-20', '22-25', '15-12'];
  assert(entries.length === expected.length, 'Wrong number of recorded sets');
  var previous, firstValue;
  entries.forEach(function(entry, i) {
    var rect = entry.getBoundingClientRect();
    var label = entry.querySelector('.hub-set-label'), value = entry.querySelector('.hub-set-value');
    assert(label.textContent === 'Set ' + (i + 1) && value.textContent === expected[i],
      'Wrong set label, order or team-first score');
    var l = label.getBoundingClientRect(), v = value.getBoundingClientRect();
    assert(Math.abs(l.top - v.top) <= 1 && v.left > l.right, 'Set label and score not on one line');
    if (previous && width <= 600) {
      assert(rect.top >= previous.bottom && Math.abs(rect.left - previous.left) <= 1 &&
        Math.abs(v.left - firstValue.left) <= 1, 'Mobile sets not on separate aligned lines');
    } else if (previous) {
      assert(Math.abs(rect.top - previous.top) <= 1 && rect.left >= previous.right + 8,
        'Desktop set entries not in spaced columns');
    }
    if (!i) firstValue = v;
    previous = rect;
  });
  if (width > 600) {
    // A narrow featured card still wraps whole entries, even at a desktop viewport.
    score.style.maxWidth = '12rem';
    assert(entries.at(-1).getBoundingClientRect().top >= entries[0].getBoundingClientRect().bottom &&
      score.scrollWidth <= score.clientWidth + 1, 'Set columns do not wrap to fit a narrow card');
    score.style.maxWidth = '';
  }
}
function checkMobilePills(grid, pills) {
  // Stress a mobile row with a season-sized count.
  pills[0].querySelector('.action-count').textContent = '123/456';
  var bands = [[0.41, 0.55], [0.60, 0.76], [0.80, 0.94]];
  var centers = [];
  pills.forEach(function(pill, row) {
    var rect = pill.getBoundingClientRect();
    assert(Math.abs(rect.width - grid.getBoundingClientRect().width) <= 1,
      'Mobile pill does not fill its row');
    var previousRight = rect.left;
    ['.action-name', '.action-count', '.action-pct', '.rating-pill'].forEach(function(selector, i) {
      var span = pill.querySelector(selector);
      var cell = span.getBoundingClientRect();
      var range = pill.ownerDocument.createRange();
      range.selectNodeContents(span);
      var text = range.getBoundingClientRect();
      assert(text.width > 0 && text.left >= cell.left - 1 && text.right <= cell.right + 1 &&
        text.left >= previousRight && text.right <= rect.right && text.top >= rect.top &&
        text.bottom <= rect.bottom, 'Clipped or overlapping mobile text: ' + selector);
      if (selector === '.rating-pill') {
        assert(Math.abs(text.left - cell.left - 9) <= 1 && Math.abs(cell.right - text.right - 9) <= 1,
          'Expected 9px on each side of mobile Nota');
        assert(cell.left >= previousRight && cell.right <= rect.right, 'Mobile rating pill does not fit');
      }
      previousRight = text.right;
      if (i === 0) return;
      var center = text.left + text.width / 2;
      var fraction = (center - rect.left) / rect.width;
      assert(fraction >= bands[i-1][0] && fraction <= bands[i-1][1],
        'Misplaced mobile ' + selector + ': ' + fraction.toFixed(2));
      assert(Math.abs(center - cell.left - cell.width / 2) <= 1, 'Off-center text: ' + selector);
      if (row === 0) centers[i] = center;
      else assert(Math.abs(center - centers[i]) <= 1, 'Mobile column drift: ' + selector);
    });
  });
}
function contrastRatio(foreground, background, document) {
  var canvas = document.createElement('canvas');
  var context = canvas.getContext('2d');
  function rgba(color) {
    context.clearRect(0, 0, 1, 1);
    context.fillStyle = color;
    context.fillRect(0, 0, 1, 1);
    var data = context.getImageData(0, 0, 1, 1).data;
    return [data[0], data[1], data[2], data[3] / 255];
  }
  var base = rgba(document.defaultView.getComputedStyle(document.documentElement)
    .getPropertyValue('--card-bg').trim());
  var bg = rgba(background);
  var fg = rgba(foreground);
  var composite = bg.slice(0, 3).map(function(channel, index) {
    return channel * bg[3] + base[index] * (1 - bg[3]);
  });
  function luminance(rgb) {
    var values = rgb.map(function(value) {
      value /= 255;
      return value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2];
  }
  var levels = [luminance(fg.slice(0, 3)), luminance(composite)].sort(function(a, b) {
    return b - a;
  });
  return (levels[0] + 0.05) / (levels[1] + 0.05);
}
function checkRatingPills(doc, selector) {
  var pills = doc.querySelectorAll(selector);
  assert(pills.length, 'Missing rating pill: ' + selector);
  // Resolve the theme token to the same CSSOM color format as the actual fill.
  var swatch = doc.createElement('span');
  swatch.style.backgroundColor = 'var(--surface-3)';
  doc.body.append(swatch);
  var surface = doc.defaultView.getComputedStyle(swatch).backgroundColor;
  swatch.remove();
  pills.forEach(function(pill) {
    var style = doc.defaultView.getComputedStyle(pill);
    assert(style.backgroundColor === surface && style.backgroundImage === 'none',
      'Rating pill does not use the neutral surface: ' + selector);
    assert(['Top', 'Right', 'Bottom', 'Left'].every(function(side) {
      return style['border' + side + 'Width'] === '0px';
    }), 'Rating pill has a border: ' + selector);
    assert(style.paddingLeft === '9px' && style.paddingRight === '9px' &&
      style.justifyContent === 'center' && style.fontVariantNumeric.includes('tabular-nums'),
      'Rating pill inset or alignment: ' + selector);
    assert(contrastRatio(style.color, style.backgroundColor, doc) >= 4.5,
      'Rating pill text contrast below 4.5:1: ' + selector);
  });
}
function checkActionPills(doc) {
  var grid = doc.querySelector('.action-grid--summary');
  var pills = Array.from(grid.querySelectorAll('.action-pill'));
  var expected = {
    high: ['--good-bg', '--good-text'],
    mid: ['--regular-bg', '--rating-mid-text'],
    low: ['--bad-bg', '--ui-loss-text']
  };
  var found = new Set();
  pills.forEach(function(pill) {
    var tier = pill.dataset.tier;
    var rating = pill.querySelector('.rating-pill');
    assert(expected[tier] && rating && rating.dataset.tier === tier,
      'Action and Nota tiers do not match');
    assert(pill.classList.contains('action-pill--' + tier),
      'Action pill class does not match its Nota tier');
    found.add(tier);
    var styles = doc.defaultView.getComputedStyle(pill);
    function token(name) {
      var swatch = doc.createElement('span');
      swatch.style.color = 'var(' + name + ')';
      swatch.style.backgroundColor = 'var(' + name + ')';
      doc.body.append(swatch);
      var value = doc.defaultView.getComputedStyle(swatch).color;
      var background = doc.defaultView.getComputedStyle(swatch).backgroundColor;
      swatch.remove();
      return name.endsWith('-bg') ? background : value;
    }
    assert(styles.backgroundColor === token(expected[tier][0]),
      'Action pill surface does not match its tier: ' + tier);
    assert(styles.borderColor !== 'rgba(0, 0, 0, 0)',
      'Action pill tier boundary is not visible: ' + tier);
    ['.action-name', '.action-count', '.action-pct'].forEach(function(selector) {
      var text = doc.defaultView.getComputedStyle(pill.querySelector(selector));
      assert(text.color === token(expected[tier][1]),
        'Action pill text color does not match its tier: ' + tier);
      assert(contrastRatio(text.color, styles.backgroundColor, doc) >= 4.5,
        'Action pill text contrast below 4.5:1: ' + tier + ' ' + selector);
    });
  });
  // This report is a synthetic fixture constructed with all three tiers; do not
  // require arbitrary real-match reports to contain every tier.
  ['high', 'mid', 'low'].forEach(function(tier) {
    assert(found.has(tier), 'Synthetic action fixture is missing the ' + tier + ' tier');
  });
}
function next() {
  if (++current === cases.length) {
    result.textContent = 'PASS';
    return;
  }
  var item = cases[current];
  frame.style.width = item.width + 'px';
  frame.style.height = item.height + 'px';
  frame.src = item.path + '?layout=1&theme=' + item.theme;
}
window.addEventListener('message', function(event) {
  if (event.origin !== location.origin || event.source !== frame.contentWindow ||
      event.data.type !== 'replay-smoke') return;
  var item = cases[current];
  try {
    assert(event.data.message === 'PASS', event.data.message);
    var win = frame.contentWindow;
    var doc = win.document;
    var box = function(selector) { return doc.querySelector(selector).getBoundingClientRect(); };
    assert(win.innerWidth === item.width && win.innerHeight === item.height, 'Wrong CSS viewport');
    assert(doc.documentElement.scrollWidth <= doc.documentElement.clientWidth + 1, 'Page overflow');
    if (item.path === 'real-watch.html') {
      checkRatingPills(doc, '#replay-spotlight .card-header .rating-pill');
      var video = box('.replay-video-frame');
      var playback = box('.replay-playback');
      var details = box('.replay-details');
      assert(Math.abs(video.width / video.height - 16/9) < 0.02, 'Video aspect ratio');
      assert(box('.replay-scoreboard').bottom <= playback.top, 'Score not above workspace');
      assert(box('.replay-context').top >= video.bottom, 'Context above video');
      assert(box('.replay-context').bottom <= box('.replay-controls').top, 'Context below controls');
      assert(!doc.querySelector('.replay-subtitle'), 'Visible viewer subtitle');
      if (item.width >= 1200) {
        assert(details.left >= playback.right, 'Viewer not split');
        assert(Math.abs(playback.width / details.width - 1.5) < 0.01, 'Viewer track ratio');
      } else assert(details.top >= playback.bottom, 'Viewer not stacked');
      assert(win.getComputedStyle(doc.querySelector('.replay-playback')).position ===
        (item.width >= 1200 && item.height >= 800 ? 'sticky' : 'static'), 'Wrong sticky mode');
      ['#replay-set','[data-replay="repeat"]','[data-replay="next"]'].forEach(function(selector) {
        var target = box(selector);
        assert(target.width >= 44 && target.height >= 44, 'Small playback target');
      });
    } else if (item.path === 'report.html') {
      var primary = box('.youtube-set-link--stats');
      var group = box('.youtube-banner__sets');
      if (item.width <= 767) {
        assert(group.top >= primary.bottom, 'Set links not on next row');
        var linkArea = box('.youtube-banner__links');
        assert(Math.abs(primary.left + primary.width/2 - linkArea.left - linkArea.width/2) < 1,
          'Viewer link not centered');
        assert(primary.width < linkArea.width - 1, 'Viewer link stretched');
      }
      var primaryAnchor = doc.querySelector('.youtube-set-link--stats');
      var primarySurface = doc.querySelector('.youtube-set-link--stats .youtube-set-link__surface');
      var setAnchor = doc.querySelector('.youtube-banner__sets .youtube-set-link');
      var setSurface = doc.querySelector('.youtube-banner__sets .youtube-set-link__surface');
      var primaryStyle = win.getComputedStyle(primarySurface);
      var setStyle = win.getComputedStyle(setSurface);
      assert(primarySurface.getBoundingClientRect().height === 32,
        'Visible report-link surface is not 32px');
      assert(primaryAnchor.getBoundingClientRect().height >= 44 &&
        setAnchor.getBoundingClientRect().height >= 44, 'Report link hit area is below 44px');
      assert(primaryStyle.backgroundColor === setStyle.backgroundColor &&
        primaryStyle.color === setStyle.color, 'Visible report-link colors differ');
      assert(win.getComputedStyle(doc.querySelector('.youtube-banner__links')).gap === '4px',
        'Report link gap was not reduced');
      var links = doc.querySelectorAll('.youtube-set-link');
      links.forEach(function(link) {
        assert(link.clientHeight >= 44 && link.scrollWidth <= link.clientWidth, 'Clipped report link');
      });
      var grid = doc.querySelector('.action-grid--summary');
      var pills = Array.from(grid ? grid.querySelectorAll('.action-pill') : []);
      assert(pills.length >= 2, 'Action pills missing');
      checkRatingPills(doc, '.card-header .rating-pill');
      checkRatingPills(doc, '.action-grid--summary .rating-pill');
      checkActionPills(doc);
      assert(parseFloat(win.getComputedStyle(pills[0]).fontSize) >= 13, 'Action pill text below 13px');
      // The widest Nota must fit and share a column center with narrower values.
      pills[0].querySelector('.rating-pill').textContent = '10.0';
      if (item.width <= 600) checkMobilePills(grid, pills);
      var firstRect = pills[0].getBoundingClientRect();
      pills.forEach(function(pill) {
        var rect = pill.getBoundingClientRect();
        assert(Math.abs(rect.width - firstRect.width) <= 1, 'Action pills have unequal widths');
        assert(pill.scrollWidth <= pill.clientWidth + 1, 'Action pill content clipped');
        if (item.width <= 600) return; // Mobile column centers were checked above.
        ['.action-count', '.action-pct', '.rating-pill'].forEach(function(selector) {
          var cell = pill.querySelector(selector).getBoundingClientRect();
          var ref = pills[0].querySelector(selector).getBoundingClientRect();
          // Compare positions within each row, even across different grid columns.
          function anchor(box) {
            return selector === '.rating-pill' ? box.left + box.width/2 : box.right;
          }
          assert(Math.abs((rect.right - anchor(cell)) - (firstRect.right - anchor(ref))) <= 1,
            'Action numbers not aligned: ' + selector);
        });
      });
      assert(doc.documentElement.scrollWidth <= doc.documentElement.clientWidth + 1,
        'Report page overflow');
    } else if (item.path === 'root-hub.html') {
      var feature = doc.querySelector('.hub-feature');
      assert(doc.body.classList.contains('hub-root') && feature,
        'Root hub lost current-competition feature');
      assert(feature.getBoundingClientRect().width >=
        doc.querySelector('.container').getBoundingClientRect().width - 1,
        'Single active competition does not span the root content width');
      var chips = feature.querySelectorAll('.hub-kpi');
      assert(feature.querySelector('.hub-status') && chips.length === 3 &&
        chips[2].textContent === '1 de 3 objetivos cumplidos', 'Featured status or goal count incorrect');
      var score = doc.querySelector('a.hub-score');
      assert(score && score.getAttribute('href') === 'nova/copa/01_rival.html', 'Missing latest report link');
      checkHubScore(score, item.width);
      ['.hub-kpi-value', '.hub-score-rating', '.hub-other-meta'].forEach(function(selector) {
        checkRatingPills(doc, selector + ' .rating-pill');
      });
      if (item.height >= 800 && item.width <= 400) {
        assert(score.getBoundingClientRect().bottom <= item.height,
          'Scoreboard not in the first mobile viewport');
      }
      Array.from(doc.querySelectorAll('.hub-mini-tile, .hub-tool-chip')).forEach(function(link) {
        assert(link.getBoundingClientRect().height >= 44, 'Hub link below 44px');
      });
      var tiles = Array.from(doc.querySelectorAll('.hub-mini-tile'));
      var tileColumns = new Set(tiles.map(function(t) { return Math.round(t.getBoundingClientRect().left); })).size;
      assert(tileColumns === (item.width <= 600 ? 1 : 3), 'Mini-tiles have wrong columns');
      assert(doc.querySelector('.hub-other-card') && !doc.querySelector('details'),
        'Other datasets should be visible cards');
      assert(doc.querySelector('.hub-tool-chip[href="logger/index.html"]') &&
        doc.querySelector('.hub-tools h2').textContent === 'Herramientas',
        'Logger utility is not in the root footer');
      assert(doc.documentElement.scrollWidth <= doc.documentElement.clientWidth + 1,
        'Root hub page overflow');
    } else if (item.path === 'dataset-hub.html') {
      assert(doc.body.classList.contains('hub-dataset'), 'Dataset hub missing scoped styling');
      var nav = doc.querySelector('.hub-nav');
      var columns = win.getComputedStyle(nav).gridTemplateColumns.trim().split(/\\s+/).length;
      assert(columns === (item.width > 600 ? 3 : 1),
        'Dataset hub navigation has wrong responsive columns');
      assert(win.getComputedStyle(doc.querySelector('.hub-tile-icon')).display !== 'none',
        'Dataset hub tile emoji hidden');
      assert(doc.querySelector('.hub-hero-objectives') &&
        doc.querySelector('.hub-last-match a') &&
        doc.querySelector('.hub-tile-stat').textContent.includes('MVP'),
        'Dataset hub dropped objectives, MVP or latest report');
      assert(doc.documentElement.scrollWidth <= doc.documentElement.clientWidth + 1,
        'Dataset hub page overflow');
    } else {
      var grid = win.getComputedStyle(doc.querySelector('.lg-analysis')).gridTemplateColumns.split(' ');
      if (item.width >= 1024) assert(Math.abs(parseFloat(grid[0]) / parseFloat(grid[1]) -
        (item.width >= 1280 ? 2 : 1.4)) < 0.01, 'Logger track ratio');
    }
    document.getElementById('measurements').textContent +=
      item.path + ' ' + item.width + 'x' + item.height + ' ' + item.theme + ' PASS\\n';
    next();
  } catch(error) {
    result.textContent = 'FAIL: ' + JSON.stringify(item) + ': ' + error.message;
  }
});
next();
</script></body></html>""",
            encoding='utf-8',
        )
        handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            version_result = subprocess.run(
                [sys.argv[1], '--version'], capture_output=True, text=True, timeout=10, check=False
            )
            print(f'Browser executable version: {version_result.stdout.strip() or "unavailable"}')
            for path, width, marker in (
                ('tests/browser_test.html', 1440, '<p id="result">PASS</p>'),
                ('mobile.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('mobile-dark.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('real-mobile.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('watch.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('watch.html?theme=dark', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('watch.html?scenario=boundaries', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('watch.html?scenario=notes', 1440, '<p id="browser-smoke-result">PASS</p>'),
                (
                    'watch.html?scenario=invalid-delta',
                    1440,
                    '<p id="browser-smoke-result">PASS</p>',
                ),
                ('chart-test.html', 412, 'id="chart-browser-result"'),
                ('logger/index.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('logger-mobile.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('layout-matrix.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
            ):
                url = f'http://127.0.0.1:{server.server_port}/{path}'
                result = subprocess.run(
                    [
                        sys.argv[1],
                        '--headless',
                        '--disable-gpu',
                        '--no-first-run',
                        '--no-default-browser-check',
                        *(['--touch-events=enabled'] if path == 'chart-test.html' else []),
                        f'--user-data-dir={root / ("profile-" + re.sub(r"[^a-zA-Z0-9-]", "-", path))}',
                        f'--window-size={width},1000',
                        '--dump-dom',
                        '--virtual-time-budget=90000'
                        if path == 'layout-matrix.html'
                        else (
                            '--virtual-time-budget=30000'
                            if path == 'chart-test.html'
                            else '--virtual-time-budget=5000'
                        ),
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=180 if path == 'layout-matrix.html' else 45,
                    check=False,
                )
                if result.returncode or marker not in result.stdout:
                    findings = re.findall(
                        r'<p id="(?:browser-smoke-result|result)">(.*?)</p>', result.stdout
                    )
                    print(f'Browser result: {findings!a}; process exit: {result.returncode}')
                    if not findings:
                        print(result.stderr.encode('ascii', errors='replace').decode())
                    print(result.stdout[-3000:].encode('ascii', errors='replace').decode())
                    raise SystemExit(f'Browser tests failed: {path}, width {width}.')
                if path == 'chart-test.html':
                    chart_result = re.search(
                        r'<p id="chart-browser-result">(.*?)</p>', result.stdout, re.S
                    )
                    chart_message = chart_result.group(1) if chart_result else 'missing result'
                    if chart_message.startswith('BLOCKED:'):
                        print(f'BLOCKED: actual Chart.js touch run: {chart_message}')
                    elif chart_message.startswith('FAIL:'):
                        raise SystemExit(f'Chart.js touch browser test failed: {chart_message}')
                    else:
                        print(f'PASS: actual Chart.js touch test: {chart_message}')
                if path == 'layout-matrix.html':
                    print('PASS: responsive matrix, 170 view/viewport/theme combinations.')
                actual = re.search(r'data-test-viewport="(\d+)"', result.stdout)
                viewport = actual.group(1) if actual else str(width)
                print(
                    f'PASS: {path}, viewport {viewport}px (requested {width}px), headless Chromium.'
                )
            print(
                'Real YouTube playback, visual inspection and deployment CSP remain manual checks.'
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()
