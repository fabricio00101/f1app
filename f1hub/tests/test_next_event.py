"""Tests de selección del próximo evento/carrera (sin red)."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from f1hub.context_processors import (
    STATE_FINISHED,
    STATE_NO_RACES,
    STATE_UPCOMING,
    get_next_race,
)

from .helpers import make_event, make_season, make_session


class NextRaceSelectionTests(TestCase):
    def setUp(self):
        self.season = make_season(2026)
        self.now = timezone.now()

    def make_race(self, round_number, when, name):
        event = make_event(
            self.season,
            round_number=round_number,
            event_date=when.date(),
            name=name,
        )
        session = make_session(event, name="Race", date_time=when)
        return event, session

    def test_picks_earliest_future_race_by_session_time(self):
        self.make_race(1, self.now - timedelta(days=5), "Past GP")
        self.make_race(2, self.now + timedelta(days=20), "Late GP")
        soon, soon_race = self.make_race(3, self.now + timedelta(days=3), "Soon GP")
        # Otra sesión del mismo fin de semana no debe convertirse en objetivo.
        make_session(soon, name="FP1", date_time=self.now + timedelta(days=2))

        state, event, race = get_next_race(self.now)

        self.assertEqual(state, STATE_UPCOMING)
        self.assertEqual(event, soon)
        self.assertEqual(race, soon_race)
        self.assertEqual(race.name, "Race")

        response = self.client.get(reverse("drivers"))
        self.assertEqual(response.context["next_event"], soon)
        self.assertEqual(response.context["countdown"]["target"], soon_race.date_time.isoformat())

    def test_past_first_event_is_not_used_as_fallback(self):
        self.make_race(1, self.now - timedelta(days=30), "Oldest GP")
        self.make_race(2, self.now - timedelta(days=1), "Recent GP")
        other_season = make_season(2027)
        make_event(other_season, 1, event_date=(self.now - timedelta(days=2)).date(), name="Other GP")

        state, event, race = get_next_race(self.now)

        self.assertEqual(state, STATE_FINISHED)
        self.assertIsNone(event)
        self.assertIsNone(race)

        response = self.client.get(reverse("drivers"))
        self.assertIsNone(response.context["next_event"])
        self.assertNotContains(response, "Gran Premio de Australia")
        self.assertNotContains(response, 'data-date="2026-03-01"')

    def test_events_without_a_race_session_are_not_presented_as_next_race(self):
        make_event(self.season, 1, event_date=(self.now + timedelta(days=3)).date(), name="Sin carrera")

        state, event, race = get_next_race(self.now)

        self.assertEqual(state, STATE_NO_RACES)
        self.assertIsNone(event)
        self.assertIsNone(race)

    def test_finished_season_is_visible_in_the_shared_layout(self):
        self.make_race(1, self.now - timedelta(days=2), "GP Viejo")

        # Aunque dashboard todavía inyecte su propio next_event, el layout
        # comparte el estado calculado por el context processor.
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FINALIZADA")
        self.assertContains(response, 'data-state="finished"')
