"""Dependency-free replay regression tests; synthetic logs never alter teams/."""

import json
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import generate
from analytics import calculate_efficiency, calculate_rating, parse_log, youtube_video_id
from renderer import render_match_page, render_watch_page
from validate_logs import validate_file

VIDEO = '@youtube: https://youtu.be/abcdefghijk\n'
LOG = VIDEO + '7A# @won @t:10-15\n7A- @lost @t:30-38\n@set: 1-1'


def replay(text):
    """Return the first source set from a synthetic log."""
    return parse_log(text)['replay']['sets'][0]


class ReplayAnalyticsTests(unittest.TestCase):
    def test_legacy_outputs(self):
        parsed = parse_log('7A# 8R+\nS-\n@won:se\n@date: 2026-10-01')
        self.assertEqual(parsed['rallies'], [['7A#', '8R+'], ['S-'], []])
        self.assertEqual(parsed['team']['total'], 3)
        self.assertEqual(parsed['players']['7']['total'], 1)
        self.assertEqual(parsed['match_date'], '2026-10-01')
        self.assertEqual(parsed['rally_timestamps'], [None, None, None])
        self.assertEqual(parsed['rally_outcomes'][0], {'result': None, 'cause': None})
        self.assertFalse(parsed['replay']['sets'][0]['eligible'])

    def test_all_logs_legacy_parity(self):
        source = subprocess.check_output(
            ['git', 'show', '05667c40d4f4afd9bbf011df72d02f4c372e6950:analytics.py'],
            encoding='utf-8',
        )
        legacy = {'__name__': 'legacy_analytics'}
        exec(compile(source, 'legacy_analytics.py', 'exec'), legacy)
        paths = sorted(Path('teams').glob('**/matches/*.txt'))
        self.assertEqual(len(paths), 17)
        for path in paths:
            text = path.read_text(encoding='utf-8')
            old = legacy['parse_log'](text)
            for variant in (text, text.replace('@start: 7-4\n', '')):
                parsed = parse_log(variant)
                for key in old.keys() - {'replay'}:
                    with self.subTest(path=path, key=key):
                        self.assertEqual(
                            json.dumps(parsed[key], ensure_ascii=False),
                            json.dumps(old[key], ensure_ascii=False),
                        )

    def test_start_score_offsets_only_score(self):
        item = replay('@start: 7-4\n' + LOG.replace('1-1', '8-5'))
        self.assertTrue(item['eligible'])
        self.assertEqual(item['start_score'], [7, 4])
        self.assertEqual([s['score'] for s in item['snapshots']], [[7, 4], [8, 4], [8, 5]])
        original = replay(LOG)
        for offset, normal in zip(item['snapshots'], original['snapshots'], strict=True):
            for key in ('team', 'players', 'longest'):
                self.assertEqual(offset[key], normal[key])
        self.assertEqual(item['rallies'], original['rallies'])
        zero = replay('@start: 0-0\n' + LOG)
        self.assertEqual(
            {k: v for k, v in zero.items() if k != 'source'},
            {k: v for k, v in original.items() if k != 'source'},
        )
        json.dumps(item, allow_nan=False)

    def test_start_without_final_and_header_order(self):
        item = replay(VIDEO + '@START: 7-4\n7A# @won @t:1-2')
        self.assertTrue(item['eligible'])
        self.assertFalse(item['reconciled'])
        self.assertEqual(item['snapshots'][-1]['score'], [8, 4])
        self.assertTrue(
            replay('@set: 8-5\n@start: 7-4\n' + LOG.replace('@set: 1-1', ''))['eligible']
        )

    def test_start_misuse_and_hint(self):
        for text, reason in [
            ('@start: 0-0\n@start: 0-0\n' + LOG, 'más de un'),
            (LOG + '\n@start: 0-0', 'antes de la primera'),
            ('@start: 2-0\n' + LOG, 'supera'),
            ('@start: broken\n' + LOG, 'Formato'),
        ]:
            with self.subTest(text=text):
                item = replay(text)
                self.assertFalse(item['eligible'])
                self.assertTrue(any(reason in d for d in item['diagnostics']))
        item = replay(LOG.replace('1-1', '8-5'))
        self.assertIn(
            'Faltan 7 ganados y 4 perdidos; si la grabación empezó tarde, agrega `@start: 7-4`.',
            item['diagnostics'],
        )
        self.assertFalse(
            any('Faltan' in d for d in replay(LOG.replace('1-1', '0-1'))['diagnostics'])
        )

    def test_validator_r10(self):
        cases = [
            ('@start: bad\n' + LOG, ['ERROR']),
            ('@start: 0-0\n@start: 0-0\n' + LOG, ['WARN']),
            (LOG + '\n@start: 0-0', ['WARN']),
            ('@start: 2-0\n' + LOG, ['WARN']),
            ('@start: 0-0\n' + LOG, []),
            ('@start: 7-4\n7A# @won', []),
            (LOG + '\n---\n@start: 0-0\n' + LOG, []),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'match.txt'
            for text, expected in cases:
                path.write_text(text, encoding='utf-8')
                issues = validate_file(path, {'7'})
                self.assertEqual([i[1] for i in issues if i[2] == 'R10'], expected)

    def test_eligible_and_snapshot_boundaries(self):
        item = replay(LOG)
        self.assertTrue(item['eligible'])
        self.assertTrue(item['reconciled'])
        self.assertEqual([s['score'] for s in item['snapshots']], [[0, 0], [1, 0], [1, 1]])
        self.assertEqual(item['snapshots'][0]['team']['touches'], 0)
        self.assertIsNone(item['snapshots'][0]['team']['attack_efficiency'])
        self.assertIsNone(item['snapshots'][0]['players'][0]['rating'])
        self.assertIsNone(item['snapshots'][0]['longest'])
        self.assertEqual(item['snapshots'][-1]['longest']['id'], 's1-r2')
        json.dumps(item, allow_nan=False)

    def test_all_prefix_formulas(self):
        lines = [
            '7S# @won @t:1-3',
            '8R- 7E+ A# @won @t:4-6',
            '8B# @won @t:7-9',
            '7A- D- @lost @t:10-12',
            '@won:se @t:12-12',
        ]
        item = replay(VIDEO + '\n'.join(lines))
        self.assertTrue(item['eligible'])
        for index, snapshot in enumerate(item['snapshots'][1:], 1):
            prefix = parse_log('\n'.join(lines[:index]))
            team = snapshot['team']
            self.assertEqual(team['touches'], prefix['team']['total'])
            self.assertEqual(team['rating'], calculate_rating(prefix['team']))
            self.assertEqual(
                team['attack_efficiency'], calculate_efficiency(prefix['team'])['attack_eff']
            )
            self.assertEqual(team['errors'], prefix['team']['grades']['-'])
            for row in snapshot['players']:
                stats = prefix['players'].get(row['number'])
                self.assertEqual(row['touches'], stats['total'] if stats else 0)
                self.assertEqual(row['rating'], calculate_rating(stats) if stats else None)
        final = item['snapshots'][-1]
        self.assertEqual(final['team']['aces'], 1)
        self.assertEqual(final['team']['kills'], 1)
        self.assertEqual(final['team']['blocks'], 1)
        self.assertEqual(final['team']['errors'], 3)
        self.assertEqual(sum(p['touches'] for p in final['players']), 5)
        self.assertEqual(final['team']['touches'], 7)
        self.assertEqual(final['longest']['id'], 's1-r1')  # first duration tie

    def test_missing_final_score_is_not_reconciled(self):
        item = replay(VIDEO + 'S# @won @t:0-0')
        self.assertTrue(item['eligible'])
        self.assertFalse(item['reconciled'])
        self.assertEqual(item['snapshots'][1]['score'], [1, 0])
        self.assertEqual(item['snapshots'][1]['longest']['duration'], 0)
        self.assertEqual(item['snapshots'][1]['players'], [])

    def test_each_ineligibility_condition(self):
        bad = [
            '7A# @t:1-2',
            '7A# @won @lost @t:1-2',
            '7A# @won @t:1',
            '7A# @won @t:2-1',
            '7A# @won @t:-1-2',
            '7A# @won @t:nan-inf',
            '7A# @won @t:1-2 @t:3-4',
            '7A# @won @t:1-2 garbage',
            '@won @t:1-2',
            '@lost @t:1-2',
            '@won:re @t:1-2',
            '@t:1-2',
            '7A# @won @t:1-5\n7A- @lost @t:4-6',
            '7A# @won @t:10-15\n7A- @lost @t:1-2',
            '7A# @won @t:1-2\n@set: 0-1',
            '7A# @won @t:1-2\n@set: 1-0\n@set: 2-0',
            '7A# @won @t:1-2\n--- SEGUNDO SET ---',
            '7A# @won @t:1-2\n(Sin registro)',
            '7A# @won @t:1-2\n@set: broken',
            '7A# @won:other @t:1-2',
            '7A# @won @t:' + '9' * 400 + '-999',
            '',
        ]
        for line in bad:
            with self.subTest(line=line):
                item = replay(VIDEO + line)
                self.assertFalse(item['eligible'])
                self.assertTrue(item['diagnostics'])
                self.assertEqual(item['snapshots'], [])

    def test_video_validation(self):
        for url in [
            'https://youtu.be/abcdefghijk',
            'https://www.youtube.com/watch?v=abcdefghijk&t=10',
            'https://youtube.com/embed/abcdefghijk',
            'https://youtube.com/shorts/abcdefghijk',
        ]:
            self.assertEqual(youtube_video_id(url), 'abcdefghijk')
        for url in [
            'https://youtu.be/short',
            'https://youtube.com.evil/watch?v=abcdefghijk',
            'javascript:abcdefghijk',
            'https://youtube.com/watch?v=abcdefghijk&v=abcdefghijk',
            'https://youtube.com/other/abcdefghijk',
            'https://user@youtube.com/watch?v=abcdefghijk',
        ]:
            self.assertIsNone(youtube_video_id(url))
            self.assertFalse(replay('@youtube: ' + url + '\n7A# @won @t:1-2')['eligible'])
        self.assertFalse(replay(VIDEO + VIDEO + '7A# @won @t:1-2')['eligible'])
        self.assertFalse(replay('7A# @won @t:1-2')['eligible'])

    def test_set_associations_and_empty_blocks(self):
        text = (
            '---\n---\n' + LOG + '\n---\n---\n'
            '@youtube: https://youtu.be/ABCDEFGHIJK\n'
            '8S# @won @t:0-0\n@set: 1-0\n---\n'
        )
        sets = parse_log(text)['replay']['sets']
        self.assertEqual(len(sets), 2)
        self.assertEqual([s['number'] for s in sets], [1, 2])
        self.assertEqual([s['video_id'] for s in sets], ['abcdefghijk', 'ABCDEFGHIJK'])
        self.assertEqual(sets[1]['rallies'][0]['id'], 's2-r1')
        self.assertTrue(all(s['eligible'] for s in sets))

    def test_mixed_sets_and_comments(self):
        sets = parse_log(LOG + '\n---\n' + VIDEO + '8S#\n')['replay']['sets']
        self.assertEqual([s['eligible'] for s in sets], [True, False])
        self.assertTrue(replay(VIDEO + '# comment\n7A# @won @t:1-2 # comment')['eligible'])
        self.assertEqual(parse_log('# comment\n---\n---')['replay']['sets'], [])


class ReplayRenderingTests(unittest.TestCase):
    def test_safe_payload_and_initial_html(self):
        name = '</script><img src=x onerror=alert(1)>&\u2028'
        page = render_watch_page('<Test & Match>', parse_log(LOG)['replay'], {'7': name}, 'a".html')
        self.assertIn('&lt;Test &amp; Match&gt;', page)
        self.assertIn('href="a&quot;.html"', page)
        self.assertNotIn(name, page)
        data = re.search(
            r'<script id="replay-data" type="application/json">(.*?)</script>', page, re.S
        )
        self.assertEqual(json.loads(data.group(1))['names']['7'], name)
        self.assertNotIn('final_score', data.group(1))
        self.assertNotIn('"source"', data.group(1))
        self.assertIn('aria-live="polite">0 - 0', page)
        self.assertIn('data-replay="next" disabled', page)
        self.assertIn('data-replay="longest" disabled', page)
        self.assertIn('<ol id="replay-rallies"></ol>', page)

    def test_mixed_exclusions_and_legacy_report(self):
        parsed = parse_log(LOG + '\n---\n' + VIDEO + '8S# @won @t:1')
        old = render_match_page('Test', parsed, '21/10/2026')
        self.assertNotIn('Ver con estadísticas', old)
        page = render_match_page('Test', parsed, '21/10/2026', parsed['replay'], 'match_watch.html')
        self.assertIn('Ver con estadísticas', page)
        self.assertIn('Set 2:', page)
        viewer = render_watch_page('Test', parsed['replay'], {}, 'match.html')
        self.assertIn('Set 2:', viewer)
        self.assertNotIn('Reproducción sincronizada no disponible.', viewer)
        data = re.search(r'type="application/json">(.*?)</script>', viewer, re.S)
        self.assertEqual(len(json.loads(data.group(1))['sets']), 1)
        bad = parse_log(VIDEO + '7A#')
        report = render_match_page('Test', bad, '21/10/2026', bad['replay'])
        self.assertNotIn('Ver con estadísticas', report)
        self.assertIn('Reproducción sincronizada no disponible.', report)


class ReplayIntegrationTests(unittest.TestCase):
    def test_source_to_output_and_precise_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            matches = source / 'matches'
            matches.mkdir(parents=True)
            (source / 'team.json').write_text(
                json.dumps(
                    {
                        'team': 'Test',
                        'tournament': 'Synthetic',
                        'roster': {'7': {'name': 'Player', 'position': 'OH'}},
                    }
                ),
                encoding='utf-8',
            )
            path = matches / '01_test.txt'
            path.write_text(LOG, encoding='utf-8')
            out = root / 'docs' / 'test' / 'synthetic'
            with (
                patch.object(generate, 'DOCS_ROOT', root / 'docs'),
                patch.object(generate, 'DATA_ROOT', root / 'data'),
                patch.object(generate, 'parse_log', wraps=parse_log) as parser,
                redirect_stdout(StringIO()),
            ):
                generate._generate_dataset('test', 'synthetic', source, '21/10/2026')
                self.assertEqual(parser.call_count, 1)
                report = (out / '01_test.html').read_text(encoding='utf-8')
                self.assertIn('href="01_test_watch.html"', report)
                watch = out / '01_test_watch.html'
                self.assertTrue(watch.exists())
                content = watch.read_bytes()
                self.assertEqual((out / 'viewer.js').read_bytes(), Path('viewer.js').read_bytes())
                generate._generate_dataset('test', 'synthetic', source, '21/10/2026')
                self.assertEqual(watch.read_bytes(), content)
                # Known ineligible stem loses only its own stale watch page.
                neighbor = out / 'unrelated_watch.html'
                neighbor.write_text('preserve', encoding='utf-8')
                path.write_text('7A#', encoding='utf-8')
                generate._generate_dataset('test', 'synthetic', source, '21/10/2026')
                self.assertFalse(watch.exists())
                self.assertEqual(neighbor.read_text(encoding='utf-8'), 'preserve')
                self.assertNotIn(
                    'Ver con estadísticas', (out / '01_test.html').read_text(encoding='utf-8')
                )
                # Even a zero-touch known source cleans up its stale watch file.
                watch.write_text('stale', encoding='utf-8')
                path.write_text('@won @t:0-1', encoding='utf-8')
                generate._generate_dataset('test', 'synthetic', source, '21/10/2026')
                self.assertFalse(watch.exists())
                # A fully graded touchless serve-fault set is publishable.
                path.write_text(VIDEO + '@won:se @t:0-0\n@set: 1-0', encoding='utf-8')
                generate._generate_dataset('test', 'synthetic', source, '21/10/2026')
                self.assertTrue(watch.exists())


if __name__ == '__main__':
    unittest.main()
