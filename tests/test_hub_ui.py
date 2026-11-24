"""Root and dataset hub regressions, including generator metadata transport."""

import json
import re
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

import generate
from renderer import render_index_page, render_root_index_page


def _dataset(**overrides):
    values = {
        'team': 'Nova',
        'tournament': 'Copa',
        'type': 'tournament',
        'active': False,
        'href': 'nova/copa/index.html',
        'season_href': 'nova/copa/team_season.html',
        'players_href': 'nova/copa/players.html',
        'matches_href': 'nova/copa/matches.html',
        'latest_match': {
            'title': 'Nova vs Rival',
            'href': 'nova/copa/01_rival.html',
            'result': 'W',
            'set_scores': [(25, 20), (22, 25), (15, 12)],
            'rating': 7.3,
        },
        'rating': 7.4,
        'matches_played': 3,
        'wins': 2,
        'losses': 1,
    }
    return values | overrides


def _set_entries(html):
    return re.findall(
        r'<span class="hub-set-label">Set (\d+)</span>\s*'
        r'<span class="hub-set-value">([^<]+)</span>',
        html,
    )


def test_root_hub_zero_one_and_many_active_datasets():
    empty = render_root_index_page([], '23/11/2026')
    assert 'Aún no hay datos disponibles.' in empty
    assert 'class="hub-tool-chip" href="logger/index.html"' in empty
    assert 'Registro de partido' in empty
    assert 'En curso' not in empty
    assert '0 partidos analizados' in empty

    one = _dataset(
        active=True, rating=8.0, objectives=[{'label': 'Derbis', 'current': 2, 'target': 2}]
    )
    html = render_root_index_page([one], '23/11/2026')
    assert '<section class="hub-current" aria-label="En curso">' in html
    assert 'class="hub-current-grid">' in html

    assert 'hub-current-grid--multiple' not in html
    assert html.count('class="hub-feature"') == 1
    # Status pill and type with decorative emoji.
    assert (
        '<span class="hub-status"><span class="hub-status-dot" aria-hidden="true">●</span>'
        'En curso</span>'
    ) in html
    assert '<span class="hub-emoji" aria-hidden="true">🏆</span> Torneo' in html
    assert 'href="nova/copa/index.html">Nova · Copa</a></h2>' in html
    # KPI chips: number first, then label; only the rating gets a rating pill.
    kpi = '<span class="hub-kpi-value">{}</span><span class="hub-kpi-label">{}</span>'
    high_pill = '<span class="rating-pill" data-tier="high">8.0</span>'
    assert kpi.format(high_pill, 'Rating') in html
    assert kpi.format('2W - 1L', 'Récord') in html
    assert html.count('class="rating-pill"') == 2  # Featured KPI and latest match only.
    assert html.count('class="hub-kpi"') == 3
    assert '1 de 1 objetivo cumplido' in re.sub('<[^>]+>', '', html)
    assert 'class="hub-kpi-label">Partidos' not in html
    # Latest-match scoreboard links to the report.
    assert '<a class="hub-score" href="nova/copa/01_rival.html">' in html
    assert '<span class="hub-score-title">Nova vs Rival</span>' in html
    assert '<span class="result-badge result-win">Victoria</span>' in html
    assert 'Marcador por set:' in html
    assert _set_entries(html) == [('1', '25-20'), ('2', '22-25'), ('3', '15-12')]
    assert (
        '<span class="hub-score-rating">Rating <span class="rating-pill" data-tier="mid">'
        '7.3</span></span>'
    ) in html
    # Mini-tiles with aria-hidden emoji badges.
    assert (
        '<a class="hub-mini-tile" href="nova/copa/team_season.html">'
        '<span class="hub-mini-icon" aria-hidden="true">📊</span><span>Temporada</span></a>'
    ) in html
    icon = '<span class="hub-mini-icon" aria-hidden="true">{}</span>'
    assert 'href="nova/copa/players.html">' + icon.format('👥') in html
    assert 'href="nova/copa/matches.html">' + icon.format('📅') + '<span>Partidos</span>' in html
    assert '<details' not in html
    assert 'Otros equipos y torneos' not in html
    assert html.index('hub-feature') < html.index('Herramientas')
    assert '3 partidos analizados' in html

    two = _dataset(
        team='Vodkas',
        active=True,
        objectives=[{'label': 'Top 4', 'baseline': 12, 'current': 5, 'target': 4}],
    )
    many = render_root_index_page([one, two], 'hoy')
    assert many.count('class="hub-feature"') == 2
    assert 'hub-current-grid hub-current-grid--multiple' in many
    assert '6 partidos analizados' in many
    assert '0 de 1 objetivo cumplido' in re.sub('<[^>]+>', '', many)
    friendly = render_root_index_page(
        [_dataset(type='friendly', tournament='Amistosos', active=True)], 'hoy'
    )
    assert '<span class="hub-emoji" aria-hidden="true">🤝</span> Amistosos' in friendly


def test_root_hub_scoreboard_loss():
    loss = render_root_index_page(
        [
            _dataset(
                active=True,
                latest_match={
                    'title': 'Nova vs Rival',
                    'href': 'nova/copa/02_rival.html',
                    'result': 'L',
                    'set_scores': [(20, 25)],
                    'rating': 5.1,
                },
            )
        ],
        'hoy',
    )
    assert '<span class="result-badge result-loss">Derrota</span>' in loss
    assert 'Victoria' not in loss
    assert _set_entries(loss) == [('1', '20-25')]
    assert '<span class="rating-pill" data-tier="low">5.1</span>' in loss


@pytest.mark.parametrize(
    'optional',
    [
        {},
        {'set_scores': []},
        {'set_scores': [(25,), None, (None, 20), (25, '   '), ([], 20), (True, 15)]},
        {'set_scores': 25, 'result': '?', 'rating': ''},
    ],
)
def test_root_hub_scoreboard_omits_unknowns(optional):
    latest = {'title': 'Nova vs Rival', 'href': 'nova/copa/03_rival.html', **optional}
    unknown = render_root_index_page([_dataset(active=True, latest_match=latest)], 'hoy')
    assert '<a class="hub-score" href="nova/copa/03_rival.html">' in unknown
    assert 'result-badge' not in unknown
    assert 'hub-score-sets' not in unknown
    assert 'Marcador por set:' not in unknown
    assert 'hub-score-rating' not in unknown
    assert 'hub-score-meta' not in unknown


@pytest.mark.parametrize(
    'optional',
    [
        {},
        {'objectives': []},
        {'objectives': 'invalid'},
        {
            'objectives': [
                None,
                {'label': '', 'current': 1, 'target': 2},
                {'label': 'Boolean', 'current': True, 'target': 2},
                {'label': 'Non-finite', 'current': float('nan'), 'target': 2},
                {'label': 'No range', 'current': 0, 'target': 0},
            ]
        },
    ],
)
def test_featured_kpis_without_valid_goals(optional):
    html = render_root_index_page([_dataset(active=True, **optional)], 'hoy')
    assert html.count('class="hub-kpi"') == 2
    assert 'objetivo' not in html and 'MVP' not in html
    assert 'class="hub-kpi-label">Partidos' not in html


def test_root_hub_unmarked_cards_grouped_with_tournaments_first():
    datasets = [
        _dataset(
            tournament='Amistosos',
            type='friendly',
            href='n/f/index.html',
            objectives=[{'label': 'Derbis', 'current': 3, 'target': 2}],
        ),
        _dataset(
            tournament='Copa 2',
            href='n/c2/index.html',
            rating='7.40',
            wins=6,
            losses=2,
            matches_played=8,
        ),
        _dataset(team='Vodkas', tournament='Liga', href='v/l/index.html'),
    ]
    html = render_root_index_page(datasets, 'hoy')
    assert '<h2 id="hub-other-title" class="hub-section-title">Equipos y torneos</h2>' in html
    assert '<details' not in html
    assert 'Otros equipos y torneos' not in html
    assert 'hub-feature' not in html
    assert html.count('class="hub-other-card"') == 3
    assert html.index('Copa 2') < html.index('Amistosos') < html.index('Vodkas')
    assert '<a class="hub-other-card" href="n/c2/index.html">' in html
    assert '<span class="hub-other-icon" aria-hidden="true">🤝</span>' in html
    assert '<span class="hub-other-icon" aria-hidden="true">🏆</span>' in html
    assert (
        '<span class="hub-other-meta">Rating <span class="rating-pill" data-tier="mid">'
        '7.40</span> · 6W - 2L</span>'
    ) in html
    assert html.count(' · 2W - 1L</span>') == 2
    assert '14 partidos analizados' in html and html.count(' partidos') == 1
    assert 'objetivo' not in html
    assert 'Finalizado' not in html and 'Archivado' not in html

    legacy = _dataset()
    legacy.pop('active')
    legacy_html = render_root_index_page([legacy], 'hoy')
    assert 'Equipos y torneos</h2>' in legacy_html
    assert 'En curso' not in legacy_html


def test_root_hub_active_with_visible_others_and_index_fallback():
    active = _dataset(
        type='friendly',
        tournament='Amistosos',
        active=True,
        season_href=None,
        latest_match=None,
    )
    other_a = _dataset(tournament='Anterior', href='n/a/index.html')
    other_b = _dataset(team='Vodkas', tournament='Copa', href='v/c/index.html')
    html = render_root_index_page([active, other_a, other_b], 'hoy')
    # No season page: the first mini-tile falls back to the dataset index.
    assert (
        '<a class="hub-mini-tile" href="nova/copa/index.html">'
        '<span class="hub-mini-icon" aria-hidden="true">🏠</span><span>Equipo</span></a>'
    ) in html
    assert 'Temporada' not in html
    assert 'hub-score' not in html
    other_title = '<h2 id="hub-other-title" class="hub-section-title">{}</h2>'
    assert other_title.format('Otros equipos y torneos') in html
    assert '<details' not in html
    assert html.count('class="hub-other-card"') == 2
    assert html.index('hub-feature') < html.index('hub-other-card') < html.index('Herramientas')


def test_only_owner_confirmed_dataset_is_marked_active():
    repo = Path(__file__).resolve().parents[1]
    configs = list((repo / 'teams').glob('**/team.json'))
    marked = [
        path.relative_to(repo / 'teams').as_posix()
        for path in configs
        if json.loads(path.read_text(encoding='utf-8')).get('active') is True
    ]
    assert marked == ['nova/atlas-chapalita-cup-2026/team.json']


def test_root_hub_escapes_dataset_identity_and_links():
    html = render_root_index_page(
        [
            _dataset(
                team='Nova <script>',
                tournament='Copa & "Final"',
                active=True,
                href='nova/index.html?x="1"&y=2',
                latest_match={
                    'title': 'Nova vs <b>Rival</b>',
                    'href': '01_r.html?a="1"&b=2',
                    'result': 'W',
                    'set_scores': [None, ('<25>', 20), ('', 12), [0, 15]],
                    'rating': '<nota>',
                },
            ),
            _dataset(team='Vodkas <i>', tournament='Liga & "B"', href='v/"l".html'),
        ],
        'hoy',
    )
    assert 'Nova &lt;script&gt; · Copa &amp; &quot;Final&quot;' in html
    assert 'href="nova/index.html?x=&quot;1&quot;&amp;y=2"' in html
    assert 'Nova <script>' not in html
    assert 'Nova vs &lt;b&gt;Rival&lt;/b&gt;' in html
    assert 'href="01_r.html?a=&quot;1&quot;&amp;b=2"' in html
    # Skipped pairs do not renumber later sets, and zero is a known score.
    assert _set_entries(html) == [('2', '&lt;25&gt;-20'), ('4', '0-15')]
    assert '<25>' not in html
    assert '<span class="hub-score-rating">Rating &lt;nota&gt;</span>' in html
    assert '<nota>' not in html
    assert 'Vodkas &lt;i&gt; · Liga &amp; &quot;B&quot;' in html
    assert 'href="v/&quot;l&quot;.html"' in html
    assert '<b>Rival</b>' not in html and 'Vodkas <i>' not in html


def test_generator_transports_active_objectives_navigation_and_latest_match(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    matches = source / 'matches'
    matches.mkdir(parents=True)
    objectives = [
        {'label': 'Top 4', 'baseline': 12, 'current': 3, 'target': 4},
        {'label': 'Saques ace', 'current': 999, 'target': 1000},  # Ring rounds up; not met.
        {'label': 'Derbis', 'current': 1, 'target': 2},
        {'label': 'Sin meta', 'current': 5},  # Not in the denominator.
    ]
    (source / 'team.json').write_text(
        json.dumps(
            {
                'team': 'Nova',
                'tournament': 'Copa',
                'type': 'tournament',
                'active': True,
                'objectives': objectives,
                'roster': {'7': {'name': 'Gio', 'position': 'OH'}},
            }
        ),
        encoding='utf-8',
    )
    (matches / '01_rival.txt').write_text('7A# @won', encoding='utf-8')
    (matches / '02_copa.txt').write_text(
        '7S+ @lost\n@set: 25-20\n---\n7A# @won\n@set: 22-25\n---\n7A# @won\n@set: 15-12',
        encoding='utf-8',
    )
    monkeypatch.setattr(generate, 'DOCS_ROOT', tmp_path / 'docs')
    monkeypatch.setattr(generate, 'DATA_ROOT', tmp_path / 'data')
    with redirect_stdout(StringIO()):
        summary = generate._generate_dataset('nova', 'copa', source, '23/11/2026')

    assert summary['active'] is True
    assert summary['objectives'] == objectives
    assert summary['href'] == 'nova/copa/index.html'
    assert summary['season_href'] == 'nova/copa/team_season.html'
    assert summary['players_href'] == 'nova/copa/players.html'
    assert summary['matches_href'] == 'nova/copa/matches.html'
    latest = summary['latest_match']
    assert latest['title'] == 'Nova vs Copa'
    assert latest['href'] == 'nova/copa/02_copa.html'
    assert latest['result'] == 'W'
    assert [tuple(pair) for pair in latest['set_scores']] == [(25, 20), (22, 25), (15, 12)]
    assert isinstance(latest['rating'], float) and 1.0 <= latest['rating'] <= 10.0
    root = render_root_index_page([summary], '23/11/2026')
    assert '<a class="hub-score" href="nova/copa/02_copa.html">' in root
    assert '<span class="hub-score-title">Nova vs Copa</span>' in root
    assert '<span class="result-badge result-win">Victoria</span>' in root
    assert _set_entries(root) == [('1', '25-20'), ('2', '22-25'), ('3', '15-12')]
    assert '1 de 3 objetivos cumplidos' in re.sub('<[^>]+>', '', root)
    assert '2 partidos analizados' in root
    # Only the second fixture has a recorded result; don't infer a second win or loss.
    assert '<span class="hub-kpi-value">1W - 0L</span>' in root
    season = (tmp_path / 'docs/nova/copa/team_season.html').read_text(encoding='utf-8')
    assert 'aria-label="Saques ace: 100%"' in season  # Rings still use their rounded fill.
    for listing in ('players.html', 'matches.html'):
        page = (tmp_path / 'docs/nova/copa' / listing).read_text(encoding='utf-8')
        headers = re.findall(r'<div class="card-header">(.*?)</div>', page)
        assert headers and all(
            re.search(r'<span class="rating-pill" data-tier="(high|mid|low)">[\d.]+</span>$', h)
            for h in headers
        )


@pytest.mark.parametrize(
    ('log', 'expected_scores', 'expected_entries'),
    [
        ('S- @lost\n---\nA# @won\n@set: 25-20', [None, (25, 20)], [('2', '25-20')]),
        (
            'S- @lost\n@set: 18-25\nA# @won\n@set: 25-20',
            [(18, 25), (25, 20)],
            [('1', '18-25'), ('2', '25-20')],
        ),
    ],
    ids=['unscored-first-set', 'legacy-finals-in-one-block'],
)
def test_latest_match_set_positions(tmp_path, monkeypatch, log, expected_scores, expected_entries):
    matches = tmp_path / 'matches'
    matches.mkdir()
    (tmp_path / 'team.json').write_text(
        json.dumps({'team': 'Nova', 'tournament': 'Copa', 'active': True}), encoding='utf-8'
    )
    (matches / '01_rival.txt').write_text(log, encoding='utf-8')
    monkeypatch.setattr(generate, 'DOCS_ROOT', tmp_path / 'docs')
    monkeypatch.setattr(generate, 'DATA_ROOT', tmp_path / 'data')

    summary = generate._generate_dataset('nova', 'copa', tmp_path, 'hoy')
    assert summary['latest_match']['set_scores'] == expected_scores
    assert _set_entries(render_root_index_page([summary], 'hoy')) == expected_entries


def test_dataset_hub_keeps_reader_destinations_objectives_and_mvp():
    html = render_index_page(
        [{'title': 'Nova vs <Rival>', 'file': '01_rival.html', 'rating': 7.3, 'result': 'W'}],
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
    assert '<body class="hub-page hub-dataset">' in html
    assert 'class="rating-pill"' not in html  # Dataset hub ratings were plain text.
    assert html.count('class="hub-tile-icon" aria-hidden="true"') == 3
    for icon, title in (('📊', 'Equipo'), ('👥', 'Jugadores'), ('📅', 'Partidos')):
        assert f'<span class="hub-tile-icon" aria-hidden="true">{icon}</span>' in html
        assert f'<span class="hub-tile-title">{title}</span>' in html
    assert '<div class="hub-hero">' in html
    assert 'class="hub-tile-btn">Ver Torneo</span>' in html
    assert 'Jugadores' in html and 'Partidos' in html
    assert 'MVP:' in html and '<strong>Gio</strong>' in html
    assert 'Objetivos de Temporada' in html
    assert 'Nova vs &lt;Rival&gt;' in html
    assert 'Ver Reporte' in html


def test_stylesheet_restores_hub_look_and_gates_motion():
    css = (Path(__file__).resolve().parents[1] / 'styles.css').read_text(encoding='utf-8')
    # The R5 flattening overrides are gone, so the original hub styles apply.
    assert '.hub-page .hub-tile-icon' not in css
    assert '.hub-page .hub-hero' not in css
    assert '.hub-page .hub-tile' not in css
    assert '.action-summary-table' not in css
    assert '.action-summary-scroll' not in css
    # Hover transforms live only inside the hover-capable media block.
    hover_start = css.index('@media (hover: hover)')
    hover_end = css.index('\n}\n', hover_start)
    outside = css[:hover_start] + css[hover_end:]
    for selector in ('.hub-tile:hover {', '.hub-feature:hover {', '.hub-other-card:hover {'):
        block_start = outside.find(selector)
        while block_start != -1:
            block = outside[block_start : outside.index('}', block_start)]
            assert 'translateY' not in block, selector
            block_start = outside.find(selector, block_start + 1)
    assert 'translateY(-2px)' in css[hover_start:hover_end]
    reduced = css[css.rindex('@media (prefers-reduced-motion: reduce)') :]
    assert 'transform: none' in reduced and '.hub-feature:hover' in reduced
