"""Dependency-free replay regression tests; synthetic logs never alter teams/."""

import json
import unittest

from analytics import calculate_efficiency, calculate_rating, parse_log, youtube_video_id

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


if __name__ == '__main__':
    unittest.main()
