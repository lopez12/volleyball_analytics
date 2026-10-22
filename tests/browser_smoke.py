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
from renderer import render_watch_page  # noqa: E402


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
    var pass = wrap.scrollWidth <= wrap.clientWidth && pinned && pinned.dataset.player === '5'
      && document.getElementById('replay-current').textContent.includes('23');
    var result = document.createElement('p');
    result.id = 'browser-smoke-result';
    result.textContent = pass ? 'PASS' : 'FAIL: real roster table overflow or wrong snapshot';
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
                ('logger/index.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('logger-mobile.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
            ):
                url = f'http://127.0.0.1:{server.server_port}/{path}'
                result = subprocess.run(
                    [
                        sys.argv[1],
                        '--headless',
                        '--disable-gpu',
                        '--no-first-run',
                        '--no-default-browser-check',
                        f'--user-data-dir={root / ("profile-" + path.replace("/", "-"))}',
                        f'--window-size={width},1000',
                        '--dump-dom',
                        '--virtual-time-budget=5000',
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=45,
                    check=False,
                )
                if result.returncode or marker not in result.stdout:
                    findings = re.findall(
                        r'<p id="(?:browser-smoke-result|result)">(.*?)</p>', result.stdout
                    )
                    print(f'Browser result: {findings!a}; process exit: {result.returncode}')
                    if not findings:
                        print(result.stderr.encode('ascii', errors='replace').decode())
                    raise SystemExit(f'Browser tests failed: {path}, width {width}.')
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
