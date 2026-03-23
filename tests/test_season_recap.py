"""
Tests for tools/season_recap.py
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make tools importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.season_recap import (
    _parse_frontmatter,
    _parse_markdown_sections,
    _extract_bullet_list,
    _extract_members_from_text,
    _extract_first_paragraph,
    _event_sort_key,
    build_recap,
    filter_by_hermit,
    filter_timeline_by_month,
    format_text,
    format_timeline_text,
    load_season_file,
    load_events_for_season,
    SEASONS_DIR,
    EVENTS_FILE,
    KNOWN_SEASONS,
    main,
)


# ---------------------------------------------------------------------------
# Unit tests — frontmatter parser
# ---------------------------------------------------------------------------

class TestParseFrontmatter(unittest.TestCase):
    def test_basic_scalar_fields(self):
        content = '---\nseason: 7\nstatus: ended\n---\n'
        fm = _parse_frontmatter(content)
        self.assertEqual(fm['season'], '7')
        self.assertEqual(fm['status'], 'ended')

    def test_quoted_values_stripped(self):
        content = '---\nstart_date: "2020-02-28"\n---\n'
        fm = _parse_frontmatter(content)
        self.assertEqual(fm['start_date'], '2020-02-28')

    def test_no_frontmatter_returns_empty(self):
        self.assertEqual(_parse_frontmatter('# No frontmatter'), {})

    def test_unclosed_frontmatter_returns_empty(self):
        self.assertEqual(_parse_frontmatter('---\nkey: val\n'), {})


# ---------------------------------------------------------------------------
# Unit tests — markdown section parser
# ---------------------------------------------------------------------------

class TestParseMarkdownSections(unittest.TestCase):
    SAMPLE = (
        '---\nseason: 1\n---\n'
        '# Title\n\n'
        '## Overview\n\nThis is the overview.\n\n'
        '## Members\n\nAlice, Bob, Carol\n\n'
        '## Notable Events\n\n- Event one\n- Event two\n'
    )

    def test_overview_extracted(self):
        sections = _parse_markdown_sections(self.SAMPLE)
        self.assertIn('Overview', sections)
        self.assertIn('overview', sections['Overview'].lower())

    def test_members_extracted(self):
        sections = _parse_markdown_sections(self.SAMPLE)
        self.assertIn('Members', sections)
        self.assertIn('Alice', sections['Members'])

    def test_notable_events_extracted(self):
        sections = _parse_markdown_sections(self.SAMPLE)
        self.assertIn('Notable Events', sections)

    def test_sections_without_frontmatter(self):
        content = '## Section A\n\nBody A\n\n## Section B\n\nBody B\n'
        sections = _parse_markdown_sections(content)
        self.assertIn('Section A', sections)
        self.assertIn('Section B', sections)


# ---------------------------------------------------------------------------
# Unit tests — bullet list extractor
# ---------------------------------------------------------------------------

class TestExtractBulletList(unittest.TestCase):
    def test_dash_bullets(self):
        text = '- First item\n- Second item\n- Third item'
        items = _extract_bullet_list(text)
        self.assertEqual(items, ['First item', 'Second item', 'Third item'])

    def test_star_bullets(self):
        text = '* Alpha\n* Beta'
        items = _extract_bullet_list(text)
        self.assertEqual(items, ['Alpha', 'Beta'])

    def test_empty_text(self):
        self.assertEqual(_extract_bullet_list(''), [])

    def test_no_bullets(self):
        self.assertEqual(_extract_bullet_list('Just a paragraph.'), [])


# ---------------------------------------------------------------------------
# Unit tests — member extractor
# ---------------------------------------------------------------------------

class TestExtractMembersFromText(unittest.TestCase):
    def test_simple_comma_list(self):
        text = 'Grian, MumboJumbo, Iskall85, TangoTek\n'
        members = _extract_members_from_text(text)
        self.assertIn('Grian', members)
        self.assertIn('MumboJumbo', members)

    def test_markdown_bold_stripped(self):
        text = '**GeminiTay** *(new)*, Grian, MumboJumbo, Iskall85\n'
        members = _extract_members_from_text(text)
        self.assertIn('GeminiTay', members)
        self.assertIn('Grian', members)

    def test_lowercase_start_handles(self):
        # iJevin and xBCrafted start with lowercase
        text = 'Grian, iJevin, xBCrafted, MumboJumbo\n'
        members = _extract_members_from_text(text)
        self.assertIn('iJevin', members)
        self.assertIn('xBCrafted', members)

    def test_prose_line_skipped_for_better_roster(self):
        # Prose line has fewer valid names than the actual roster
        text = (
            'All 24 Season 7 members returned, plus two new additions:\n\n'
            'Grian, MumboJumbo, Iskall85, TangoTek, Scar, ImpulseSV\n'
        )
        members = _extract_members_from_text(text)
        self.assertGreaterEqual(len(members), 6)
        self.assertIn('Grian', members)


# ---------------------------------------------------------------------------
# Unit tests — first paragraph extractor
# ---------------------------------------------------------------------------

class TestExtractFirstParagraph(unittest.TestCase):
    def test_returns_first_non_empty_line(self):
        text = '\n\nSome intro text here.\n\nMore text.'
        self.assertEqual(_extract_first_paragraph(text), 'Some intro text here.')

    def test_skips_headings(self):
        text = '## Heading\n\nActual paragraph.'
        self.assertEqual(_extract_first_paragraph(text), 'Actual paragraph.')

    def test_empty_text(self):
        self.assertEqual(_extract_first_paragraph(''), '')


# ---------------------------------------------------------------------------
# Integration tests — load_season_file and load_events_for_season
# ---------------------------------------------------------------------------

class TestLoadSeasonFile(unittest.TestCase):
    def test_season_7_loads(self):
        fm, sections = load_season_file(7)
        self.assertEqual(fm.get('season'), '7')
        self.assertIn('Overview', sections)

    def test_season_9_start_date(self):
        fm, _ = load_season_file(9)
        self.assertEqual(fm.get('start_date'), '2022-03-05')

    def test_missing_season_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_season_file(999)

    def test_all_known_seasons_loadable(self):
        for s in KNOWN_SEASONS:
            path = SEASONS_DIR / f'season-{s}.md'
            if path.exists():
                fm, sections = load_season_file(s)
                self.assertIsInstance(fm, dict)
                self.assertIsInstance(sections, dict)


class TestLoadEventsForSeason(unittest.TestCase):
    def test_season_7_has_events(self):
        events = load_events_for_season(7)
        self.assertGreater(len(events), 0)

    def test_all_events_correct_season(self):
        for s in [6, 7, 8, 9]:
            events = load_events_for_season(s)
            for ev in events:
                self.assertEqual(ev.get('season'), s)

    def test_nonexistent_season_returns_empty(self):
        events = load_events_for_season(9999)
        self.assertEqual(events, [])


# ---------------------------------------------------------------------------
# Integration tests — build_recap
# ---------------------------------------------------------------------------

class TestBuildRecap(unittest.TestCase):
    def _recap(self, season: int) -> dict:
        return build_recap(season)

    def test_season_field_correct(self):
        self.assertEqual(self._recap(7)['season'], 7)
        self.assertEqual(self._recap(9)['season'], 9)

    def test_required_keys_present(self):
        required = [
            'season', 'start_date', 'end_date', 'minecraft_version',
            'member_count', 'theme', 'status', 'overview', 'members',
            'key_themes', 'notable_events', 'major_builds', 'sources',
            'timeline_events',
        ]
        recap = self._recap(7)
        for key in required:
            self.assertIn(key, recap, f"Missing key: {key}")

    def test_season_7_start_date(self):
        self.assertEqual(self._recap(7)['start_date'], '2020-02-28')

    def test_season_8_start_date(self):
        self.assertEqual(self._recap(8)['start_date'], '2021-06-19')

    def test_season_9_longest(self):
        recap = self._recap(9)
        # Duration text should mention months
        self.assertIn('month', recap.get('duration', '').lower())

    def test_season_7_has_members(self):
        members = self._recap(7)['members']
        self.assertGreater(len(members), 0)
        self.assertIn('Grian', members)

    def test_season_8_includes_lowercase_handles(self):
        members = self._recap(8)['members']
        self.assertIn('iJevin', members)
        self.assertIn('xBCrafted', members)

    def test_season_9_member_count(self):
        recap = self._recap(9)
        self.assertEqual(recap['member_count'], 26)

    def test_season_7_seed(self):
        self.assertEqual(self._recap(7)['seed'], '-2143500864')

    def test_season_9_unknown_seed_is_none(self):
        self.assertIsNone(self._recap(9)['seed'])

    def test_season_7_has_timeline_events(self):
        self.assertGreater(len(self._recap(7)['timeline_events']), 0)

    def test_season_7_has_notable_events(self):
        self.assertGreater(len(self._recap(7)['notable_events']), 0)

    def test_season_7_has_major_builds(self):
        self.assertGreater(len(self._recap(7)['major_builds']), 0)

    def test_season_7_has_sources(self):
        sources = self._recap(7)['sources']
        self.assertGreater(len(sources), 0)
        self.assertTrue(any('hermitcraft' in s.lower() for s in sources))

    def test_season_7_overview_non_empty(self):
        self.assertTrue(self._recap(7)['overview'])

    def test_seasons_7_8_9_covered(self):
        for s in [7, 8, 9]:
            recap = build_recap(s)
            self.assertGreater(len(recap['members']), 0,
                               f"Season {s} has no members")
            self.assertGreater(len(recap['timeline_events']), 0,
                               f"Season {s} has no timeline events")


# ---------------------------------------------------------------------------
# Integration tests — format_text
# ---------------------------------------------------------------------------

class TestFormatText(unittest.TestCase):
    def setUp(self):
        self.recap7 = build_recap(7)
        self.recap9 = build_recap(9)

    def test_output_is_string(self):
        self.assertIsInstance(format_text(self.recap7), str)

    def test_season_number_in_output(self):
        out = format_text(self.recap7)
        self.assertIn('SEASON 7', out)

    def test_dates_in_output(self):
        out = format_text(self.recap7)
        self.assertIn('2020-02-28', out)

    def test_members_section_present(self):
        out = format_text(self.recap7)
        self.assertIn('MEMBERS', out)

    def test_notable_events_section_present(self):
        out = format_text(self.recap7)
        self.assertIn('NOTABLE EVENTS', out)

    def test_timeline_section_present(self):
        out = format_text(self.recap7)
        self.assertIn('TIMELINE', out)

    def test_sources_section_present(self):
        out = format_text(self.recap7)
        self.assertIn('SOURCES', out)

    def test_empty_recap_does_not_crash(self):
        # A minimal recap with no optional sections should not raise
        minimal = {
            'season': 99, 'start_date': '', 'end_date': '', 'duration': '',
            'minecraft_version': '', 'member_count': 0, 'seed': None,
            'theme': '', 'status': '', 'overview': '', 'members': [],
            'key_themes': [], 'notable_events': [], 'major_builds': [],
            'sources': [], 'timeline_events': [],
        }
        out = format_text(minimal)
        self.assertIn('SEASON 99', out)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

SCRIPT = str(Path(__file__).parent.parent / 'tools' / 'season_recap.py')


class TestCLI(unittest.TestCase):
    def _run(self, *args: str) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, SCRIPT, *args],
            capture_output=True, text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def test_season_7_exits_0(self):
        rc, _, _ = self._run('--season', '7')
        self.assertEqual(rc, 0)

    def test_season_9_exits_0(self):
        rc, _, _ = self._run('--season', '9')
        self.assertEqual(rc, 0)

    def test_text_output_contains_recap_header(self):
        _, stdout, _ = self._run('--season', '7')
        self.assertIn('SEASON 7', stdout)

    def test_json_flag_produces_valid_json(self):
        rc, stdout, _ = self._run('--season', '9', '--json')
        self.assertEqual(rc, 0)
        data = json.loads(stdout)
        self.assertEqual(data['season'], 9)

    def test_json_output_has_required_fields(self):
        _, stdout, _ = self._run('--season', '7', '--json')
        data = json.loads(stdout)
        for key in ('season', 'start_date', 'members', 'notable_events',
                    'timeline_events', 'sources'):
            self.assertIn(key, data)

    def test_unknown_season_exits_2(self):
        rc, _, stderr = self._run('--season', '99')
        self.assertEqual(rc, 2)
        self.assertIn('unknown season', stderr)

    def test_missing_arguments_exits_nonzero(self):
        rc, _, _ = self._run()
        self.assertNotEqual(rc, 0)

    def test_list_flag_exits_0(self):
        rc, stdout, _ = self._run('--list')
        self.assertEqual(rc, 0)
        self.assertIn('1', stdout)
        self.assertIn('11', stdout)

    def test_list_json_flag(self):
        rc, stdout, _ = self._run('--list', '--json')
        self.assertEqual(rc, 0)
        data = json.loads(stdout)
        self.assertIn('available_seasons', data)
        self.assertIn(7, data['available_seasons'])

    def test_season_8_members_include_new(self):
        _, stdout, _ = self._run('--season', '8', '--json')
        data = json.loads(stdout)
        members = data['members']
        self.assertIn('GeminiTay', members)
        self.assertIn('PearlescentMoon', members)

    def test_season_9_json_member_count(self):
        _, stdout, _ = self._run('--season', '9', '--json')
        data = json.loads(stdout)
        self.assertEqual(data['member_count'], 26)


# ---------------------------------------------------------------------------
# Unit tests — _event_sort_key
# ---------------------------------------------------------------------------

class TestEventSortKey(unittest.TestCase):
    def test_full_date_sorts_correctly(self):
        a = {'date': '2020-02-28', 'date_precision': 'day'}
        b = {'date': '2020-06-23', 'date_precision': 'day'}
        self.assertLess(_event_sort_key(a), _event_sort_key(b))

    def test_year_only_sorts_before_month(self):
        year_event = {'date': '2020', 'date_precision': 'year'}
        month_event = {'date': '2020-03', 'date_precision': 'month'}
        # year-only → (2020, 0, 0); month-only → (2020, 3, 0)
        self.assertLess(_event_sort_key(year_event), _event_sort_key(month_event))

    def test_missing_date_returns_zeros(self):
        key = _event_sort_key({'date': ''})
        self.assertEqual(key, (0, 0, 0))

    def test_events_sorted_chronologically(self):
        events = [
            {'date': '2022-12-20', 'season': 9},
            {'date': '2022-03-05', 'season': 9},
            {'date': '2022-07-02', 'season': 9},
        ]
        sorted_events = sorted(events, key=_event_sort_key)
        dates = [e['date'] for e in sorted_events]
        self.assertEqual(dates, ['2022-03-05', '2022-07-02', '2022-12-20'])


# ---------------------------------------------------------------------------
# Unit tests — filter_timeline_by_month
# ---------------------------------------------------------------------------

class TestFilterTimelineByMonth(unittest.TestCase):
    EVENTS = [
        {'id': 'a', 'date': '2022-03-05', 'date_precision': 'day',   'season': 9},
        {'id': 'b', 'date': '2022-07-02', 'date_precision': 'day',   'season': 9},
        {'id': 'c', 'date': '2022',       'date_precision': 'year',  'season': 9},
        {'id': 'd', 'date': '2022-03-15', 'date_precision': 'day',   'season': 9},
        {'id': 'e', 'date': '2023-12-20', 'date_precision': 'day',   'season': 9},
    ]

    def test_filter_march_returns_march_events(self):
        result = filter_timeline_by_month(self.EVENTS, 3)
        ids = [e['id'] for e in result]
        self.assertIn('a', ids)
        self.assertIn('d', ids)
        self.assertNotIn('b', ids)
        self.assertNotIn('e', ids)

    def test_year_only_events_excluded_from_month_filter(self):
        result = filter_timeline_by_month(self.EVENTS, 3)
        ids = [e['id'] for e in result]
        self.assertNotIn('c', ids)

    def test_month_with_no_matches_returns_empty(self):
        result = filter_timeline_by_month(self.EVENTS, 4)
        self.assertEqual(result, [])

    def test_empty_events_returns_empty(self):
        self.assertEqual(filter_timeline_by_month([], 6), [])

    def test_december_filter(self):
        result = filter_timeline_by_month(self.EVENTS, 12)
        ids = [e['id'] for e in result]
        self.assertIn('e', ids)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# Integration tests — load_events_for_season chronological order
# ---------------------------------------------------------------------------

class TestLoadEventsChronological(unittest.TestCase):
    def test_season_7_events_sorted(self):
        events = load_events_for_season(7)
        keys = [_event_sort_key(e) for e in events]
        self.assertEqual(keys, sorted(keys),
                         "Season 7 events are not in chronological order")

    def test_season_9_events_sorted(self):
        events = load_events_for_season(9)
        keys = [_event_sort_key(e) for e in events]
        self.assertEqual(keys, sorted(keys),
                         "Season 9 events are not in chronological order")

    def test_all_seasons_chronological(self):
        for s in range(1, 12):
            events = load_events_for_season(s)
            keys = [_event_sort_key(e) for e in events]
            self.assertEqual(keys, sorted(keys),
                             f"Season {s} events are not in chronological order")


# ---------------------------------------------------------------------------
# Integration tests — format_timeline_text
# ---------------------------------------------------------------------------

class TestFormatTimelineText(unittest.TestCase):
    def setUp(self):
        self.events7 = load_events_for_season(7)
        self.events9 = load_events_for_season(9)

    def test_returns_string(self):
        self.assertIsInstance(format_timeline_text(7, self.events7), str)

    def test_header_contains_season(self):
        out = format_timeline_text(7, self.events7)
        self.assertIn('SEASON 7 TIMELINE', out)

    def test_month_label_in_header(self):
        out = format_timeline_text(9, self.events9, month=3)
        self.assertIn('March', out)

    def test_event_titles_present(self):
        out = format_timeline_text(7, self.events7)
        self.assertIn('Season 7', out)

    def test_hermit_names_present(self):
        out = format_timeline_text(7, self.events7)
        # At least one event references "All" or a hermit name
        self.assertTrue('All' in out or 'TangoTek' in out or 'Grian' in out)

    def test_empty_events_shows_no_events_message(self):
        out = format_timeline_text(9, [], month=4)
        self.assertIn('No events found', out)

    def test_approximate_date_prefixed_with_tilde(self):
        approx_event = [{
            'id': 't1', 'date': '2020-11', 'date_precision': 'approximate',
            'season': 7, 'hermits': ['Grian'], 'title': 'Test Event',
            'description': 'A test.', 'type': 'lore',
        }]
        out = format_timeline_text(7, approx_event)
        self.assertIn('~2020-11', out)


# ---------------------------------------------------------------------------
# CLI tests — timeline-only and month flags
# ---------------------------------------------------------------------------

class TestCLITimeline(unittest.TestCase):
    def _run(self, *args: str) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, SCRIPT, *args],
            capture_output=True, text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def test_timeline_only_exits_0(self):
        rc, _, _ = self._run('--season', '7', '--timeline-only')
        self.assertEqual(rc, 0)

    def test_timeline_only_contains_timeline_header(self):
        _, stdout, _ = self._run('--season', '7', '--timeline-only')
        self.assertIn('SEASON 7 TIMELINE', stdout)

    def test_timeline_only_json_valid(self):
        rc, stdout, _ = self._run('--season', '9', '--timeline-only', '--json')
        self.assertEqual(rc, 0)
        data = json.loads(stdout)
        self.assertEqual(data['season'], 9)
        self.assertIn('events', data)
        self.assertIn('event_count', data)

    def test_timeline_only_json_events_sorted(self):
        _, stdout, _ = self._run('--season', '9', '--timeline-only', '--json')
        data = json.loads(stdout)
        events = data['events']
        keys = [_event_sort_key(e) for e in events]
        self.assertEqual(keys, sorted(keys), "Events not sorted chronologically")

    def test_month_implies_timeline_only(self):
        # --month without --timeline-only should still work (--month implies it)
        rc, stdout, _ = self._run('--season', '9', '--month', '3')
        self.assertEqual(rc, 0)
        self.assertIn('TIMELINE', stdout)
        self.assertIn('March', stdout)

    def test_month_filter_json(self):
        rc, stdout, _ = self._run('--season', '7', '--month', '6', '--json')
        self.assertEqual(rc, 0)
        data = json.loads(stdout)
        self.assertEqual(data['month'], 6)
        for ev in data['events']:
            # Every returned event must be in June
            self.assertTrue(ev['date'].startswith('2') and '-06-' in ev['date']
                            or ev['date'].endswith('-06'),
                            f"Event {ev['date']} not in June")

    def test_month_out_of_range_exits_2(self):
        rc, _, stderr = self._run('--season', '9', '--month', '13')
        self.assertEqual(rc, 2)
        self.assertIn('invalid month', stderr)

    def test_month_with_no_events_exits_0(self):
        # April (month 4) has no events in S9 — should exit 0, not error
        rc, stdout, _ = self._run('--season', '9', '--month', '4')
        self.assertEqual(rc, 0)
        self.assertIn('No events found', stdout)

    def test_timeline_json_each_event_has_required_fields(self):
        _, stdout, _ = self._run('--season', '7', '--timeline-only', '--json')
        data = json.loads(stdout)
        for ev in data['events']:
            for field in ('id', 'date', 'season', 'hermits', 'title', 'description'):
                self.assertIn(field, ev, f"Event missing field '{field}': {ev}")

    def test_seasons_7_8_9_timeline_all_have_events(self):
        for s in [7, 8, 9]:
            rc, stdout, _ = self._run('--season', str(s), '--timeline-only', '--json')
            self.assertEqual(rc, 0)
            data = json.loads(stdout)
            self.assertGreater(data['event_count'], 0, f"Season {s} has no events")


# ---------------------------------------------------------------------------
# Unit tests — filter_by_hermit
# ---------------------------------------------------------------------------

class TestFilterByHermit(unittest.TestCase):
    EVENTS = [
        {'id': 'all-1',   'hermits': ['All'],                 'title': 'Server-wide'},
        {'id': 'grian-1', 'hermits': ['Grian'],               'title': 'Grian solo'},
        {'id': 'duo-1',   'hermits': ['Grian', 'MumboJumbo'], 'title': 'Duo event'},
        {'id': 'tango-1', 'hermits': ['TangoTek'],            'title': 'TangoTek solo'},
        {'id': 'empty-1', 'hermits': [],                      'title': 'Unknown'},
    ]

    def test_all_event_always_included(self):
        ids = [e['id'] for e in filter_by_hermit(self.EVENTS, 'Grian')]
        self.assertIn('all-1', ids)

    def test_named_hermit_included(self):
        ids = [e['id'] for e in filter_by_hermit(self.EVENTS, 'Grian')]
        self.assertIn('grian-1', ids)

    def test_multi_hermit_event_included(self):
        ids = [e['id'] for e in filter_by_hermit(self.EVENTS, 'Grian')]
        self.assertIn('duo-1', ids)

    def test_non_matching_hermit_excluded(self):
        ids = [e['id'] for e in filter_by_hermit(self.EVENTS, 'Grian')]
        self.assertNotIn('tango-1', ids)

    def test_empty_hermit_list_excluded(self):
        ids = [e['id'] for e in filter_by_hermit(self.EVENTS, 'Grian')]
        self.assertNotIn('empty-1', ids)

    def test_case_insensitive_lowercase(self):
        lower = filter_by_hermit(self.EVENTS, 'grian')
        proper = filter_by_hermit(self.EVENTS, 'Grian')
        self.assertEqual([e['id'] for e in lower], [e['id'] for e in proper])

    def test_case_insensitive_uppercase(self):
        upper = filter_by_hermit(self.EVENTS, 'GRIAN')
        proper = filter_by_hermit(self.EVENTS, 'Grian')
        self.assertEqual([e['id'] for e in upper], [e['id'] for e in proper])

    def test_unknown_hermit_returns_only_all_events(self):
        results = filter_by_hermit(self.EVENTS, 'ZombieCleo')
        ids = [e['id'] for e in results]
        self.assertEqual(ids, ['all-1'])

    def test_empty_event_list_returns_empty(self):
        self.assertEqual(filter_by_hermit([], 'Grian'), [])

    def test_tangotek_gets_solo_and_all(self):
        ids = [e['id'] for e in filter_by_hermit(self.EVENTS, 'TangoTek')]
        self.assertIn('tango-1', ids)
        self.assertIn('all-1', ids)
        self.assertNotIn('grian-1', ids)


# ---------------------------------------------------------------------------
# CLI tests — --hermit flag in season_recap
# ---------------------------------------------------------------------------

class TestCLIHermit(unittest.TestCase):
    def _run(self, *args: str) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, SCRIPT, *args],
            capture_output=True, text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def test_hermit_flag_exits_0(self):
        rc, _, _ = self._run('--season', '7', '--hermit', 'TangoTek')
        self.assertEqual(rc, 0)

    def test_hermit_implies_timeline_only(self):
        _, stdout, _ = self._run('--season', '7', '--hermit', 'Grian')
        # Should produce timeline output, not full recap
        self.assertIn('TIMELINE', stdout)
        self.assertNotIn('MEMBERS', stdout)

    def test_hermit_label_in_header(self):
        _, stdout, _ = self._run('--season', '7', '--hermit', 'TangoTek')
        self.assertIn('TangoTek', stdout)

    def test_hermit_json_contains_hermit_field(self):
        rc, stdout, _ = self._run('--season', '7', '--hermit', 'Grian', '--json')
        self.assertEqual(rc, 0)
        data = json.loads(stdout)
        self.assertEqual(data['hermit'], 'Grian')

    def test_hermit_json_events_all_relevant(self):
        _, stdout, _ = self._run('--season', '7', '--hermit', 'TangoTek', '--json')
        data = json.loads(stdout)
        for ev in data['events']:
            hermits = ev.get('hermits', [])
            self.assertTrue(
                hermits == ['All']
                or any(h.lower() == 'tangotek' for h in hermits),
                f"Event has unexpected hermits: {hermits}",
            )

    def test_hermit_case_insensitive(self):
        _, out_lower, _ = self._run('--season', '7', '--hermit', 'grian', '--json')
        _, out_proper, _ = self._run('--season', '7', '--hermit', 'Grian', '--json')
        data_lower = json.loads(out_lower)
        data_proper = json.loads(out_proper)
        self.assertEqual(data_lower['event_count'], data_proper['event_count'])

    def test_hermit_combined_with_month(self):
        rc, stdout, _ = self._run(
            '--season', '7', '--hermit', 'TangoTek', '--month', '6', '--json'
        )
        self.assertEqual(rc, 0)
        data = json.loads(stdout)
        self.assertEqual(data['hermit'], 'TangoTek')
        self.assertEqual(data['month'], 6)

    def test_hermit_decked_out_tangotek_season7(self):
        _, stdout, _ = self._run('--season', '7', '--hermit', 'TangoTek', '--json')
        data = json.loads(stdout)
        titles = [ev['title'] for ev in data['events']]
        # Decked Out event specifically involves TangoTek
        self.assertTrue(
            any('Decked Out' in t or 'TangoTek' in t for t in titles),
            f"Expected Decked Out event, got: {titles}",
        )


# ---------------------------------------------------------------------------
# KNOWN_SEASONS constant
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_known_seasons_is_list(self):
        self.assertIsInstance(KNOWN_SEASONS, list)

    def test_known_seasons_includes_7_8_9(self):
        for s in [7, 8, 9]:
            self.assertIn(s, KNOWN_SEASONS)

    def test_known_seasons_min_max(self):
        self.assertEqual(min(KNOWN_SEASONS), 1)
        self.assertGreaterEqual(max(KNOWN_SEASONS), 11)

    def test_seasons_dir_exists(self):
        self.assertTrue(SEASONS_DIR.exists(), f"SEASONS_DIR not found: {SEASONS_DIR}")

    def test_events_file_exists(self):
        self.assertTrue(EVENTS_FILE.exists(), f"EVENTS_FILE not found: {EVENTS_FILE}")


if __name__ == '__main__':
    # Custom runner matching on_this_day test style
    import traceback

    suites = [
        ('_parse_frontmatter', unittest.TestLoader().loadTestsFromTestCase(TestParseFrontmatter)),
        ('_parse_markdown_sections', unittest.TestLoader().loadTestsFromTestCase(TestParseMarkdownSections)),
        ('_extract_bullet_list', unittest.TestLoader().loadTestsFromTestCase(TestExtractBulletList)),
        ('_extract_members_from_text', unittest.TestLoader().loadTestsFromTestCase(TestExtractMembersFromText)),
        ('_extract_first_paragraph', unittest.TestLoader().loadTestsFromTestCase(TestExtractFirstParagraph)),
        ('_event_sort_key', unittest.TestLoader().loadTestsFromTestCase(TestEventSortKey)),
        ('filter_timeline_by_month', unittest.TestLoader().loadTestsFromTestCase(TestFilterTimelineByMonth)),
        ('load_season_file', unittest.TestLoader().loadTestsFromTestCase(TestLoadSeasonFile)),
        ('load_events_for_season', unittest.TestLoader().loadTestsFromTestCase(TestLoadEventsForSeason)),
        ('load_events_chronological', unittest.TestLoader().loadTestsFromTestCase(TestLoadEventsChronological)),
        ('build_recap', unittest.TestLoader().loadTestsFromTestCase(TestBuildRecap)),
        ('format_text', unittest.TestLoader().loadTestsFromTestCase(TestFormatText)),
        ('format_timeline_text', unittest.TestLoader().loadTestsFromTestCase(TestFormatTimelineText)),
        ('CLI', unittest.TestLoader().loadTestsFromTestCase(TestCLI)),
        ('CLI_timeline', unittest.TestLoader().loadTestsFromTestCase(TestCLITimeline)),
        ('filter_by_hermit', unittest.TestLoader().loadTestsFromTestCase(TestFilterByHermit)),
        ('CLI_hermit', unittest.TestLoader().loadTestsFromTestCase(TestCLIHermit)),
        ('constants', unittest.TestLoader().loadTestsFromTestCase(TestConstants)),
    ]

    total = passed = failed = 0
    for label, suite in suites:
        print(f'{label}:')
        for test in suite:
            total += 1
            try:
                test.debug()
                print(f'  PASS {test._testMethodName}')
                passed += 1
            except Exception as exc:
                print(f'  FAIL {test._testMethodName}: {exc}')
                failed += 1

    print(f'\n{passed} passed, {failed} failed')
    sys.exit(0 if failed == 0 else 1)
