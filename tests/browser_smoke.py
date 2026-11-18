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
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analytics import parse_log  # noqa: E402
from renderer import render_match_page, render_watch_page  # noqa: E402


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
        log = '@youtube: https://youtu.be/abcdefghijk\n7A# @won @t:10-15\n7A- @lost @t:30-38'
        payload = {'sets': parse_log(log)['replay']['sets'], 'names': {'7': 'Test'}}
        (tests / 'fixture.json').write_text(json.dumps(payload), encoding='utf-8')
        mixed = parse_log(
            log
            + '\n---\n'
            + '@start: 7-4\n'
            + log.replace('7A#', '8A#').replace('abcdefghijk', 'ABCDEFGHIJK')
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
        mixed['sets'].extend([boundaries, inconsistent])
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
        report = parse_log((log + '\n---\n') * 5 + log)
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
var sizes = [[320,740],[375,812],[390,844],[768,1024],[1023,768],[1024,600],
  [1279,768],[1280,800],[1366,768],[1920,1080],[844,390],[683,384]];
var cases = [];
['light','dark'].forEach(function(theme) {
  sizes.forEach(function(size) {
    ['real-watch.html','report.html','logger/index.html'].forEach(function(path) {
      cases.push({theme:theme, width:size[0], height:size[1], path:path});
    });
  });
});
var current = -1;
function assert(value, message) { if (!value) throw new Error(message); }
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
      var primaryStyle = win.getComputedStyle(doc.querySelector('.youtube-set-link--stats'));
      var setStyle = win.getComputedStyle(doc.querySelector('.youtube-banner__sets a'));
      assert(primaryStyle.backgroundColor === setStyle.backgroundColor &&
        primaryStyle.color === setStyle.color, 'Report link colors differ');
      var links = doc.querySelectorAll('.youtube-set-link');
      links.forEach(function(link) {
        assert(link.clientHeight >= 42 && link.scrollWidth <= link.clientWidth, 'Clipped report link');
      });
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
            for path, width, marker in (
                ('tests/browser_test.html', 1440, '<p id="result">PASS</p>'),
                ('mobile.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('real-mobile.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('watch.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('watch.html?scenario=boundaries', 1440, '<p id="browser-smoke-result">PASS</p>'),
                (
                    'watch.html?scenario=invalid-delta',
                    1440,
                    '<p id="browser-smoke-result">PASS</p>',
                ),
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
                        f'--user-data-dir={root / ("profile-" + re.sub(r"[^a-zA-Z0-9-]", "-", path))}',
                        f'--window-size={width},1000',
                        '--dump-dom',
                        '--virtual-time-budget=90000'
                        if path == 'layout-matrix.html'
                        else '--virtual-time-budget=5000',
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
                if path == 'layout-matrix.html':
                    print('PASS: responsive matrix, 72 view/viewport/theme combinations.')
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
