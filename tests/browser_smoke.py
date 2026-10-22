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
            log + '\n---\n' + '@start: 7-4\n' + log.replace('abcdefghijk', 'ABCDEFGHIJK')
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
        handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, width, marker in (
                ('tests/browser_test.html', 1440, '<p id="result">PASS</p>'),
                ('mobile.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
                ('watch.html', 1440, '<p id="browser-smoke-result">PASS</p>'),
            ):
                url = f'http://127.0.0.1:{server.server_port}/{path}'
                result = subprocess.run(
                    [
                        sys.argv[1],
                        '--headless',
                        '--disable-gpu',
                        '--no-first-run',
                        '--no-default-browser-check',
                        f'--user-data-dir={root / "profile"}',
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
