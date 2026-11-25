"""Tests del contexto compartido por todas las plantillas y del contador base."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from f1hub.context_processors import (
    STATE_FINISHED,
    STATE_IN_PROGRESS,
    STATE_NO_RACES,
    STATE_UPCOMING,
    race_context,
)

from .helpers import make_event, make_season, make_session

PAGE_URLS = ("dashboard", "drivers", "teams", "insights")


def _standings_models():
    """Los modelos de standings los agrega la capa de datos en paralelo."""
    try:
        from f1hub.models import ConstructorStanding, DriverStanding
    except ImportError:
        return None, None
    return DriverStanding, ConstructorStanding


class SharedContextTests(TestCase):
    def setUp(self):
        self.season = make_season(2026)
        self.now = timezone.now()

    def add_race(self, when, name="GP Futuro", round_number=1):
        event = make_event(
            self.season,
            round_number=round_number,
            event_date=when.date(),
            name=name,
        )
        return event, make_session(event, name="Race", date_time=when)

    def test_context_is_available_on_every_page(self):
        event, race = self.add_race(self.now + timedelta(days=5))

        for url_name in PAGE_URLS:
            with self.subTest(view=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("calendar_events", response.context)
                self.assertIn("today", response.context)
                self.assertIn("next_event", response.context)
                self.assertIn("countdown", response.context)
                self.assertIn("insights", response.context)
                self.assertEqual(response.context["next_event"], event)
                self.assertEqual(response.context["today"], timezone.localdate())
                self.assertEqual(list(response.context["calendar_events"]), [event])
                self.assertEqual(response.context["countdown"]["status"], STATE_UPCOMING)
                self.assertEqual(response.context["countdown"]["target"], race.date_time.isoformat())

    def test_context_processor_uses_real_race_time_and_timezone(self):
        start = self.now + timedelta(days=6, minutes=17)
        _, race = self.add_race(start)

        context = race_context(None)

        self.assertEqual(context["countdown"]["session_name"], "Race")
        self.assertEqual(context["countdown"]["starts_at"], race.date_time)
        self.assertEqual(context["countdown"]["target"], race.date_time.isoformat())
        self.assertEqual(
            context["countdown"]["end_target"],
            (race.date_time + timedelta(hours=2)).isoformat(),
        )
        self.assertTrue(context["countdown"]["timezone"])

    def test_race_started_recently_is_in_progress(self):
        event, _ = self.add_race(self.now - timedelta(minutes=30), name="GP En curso")

        response = self.client.get(reverse("drivers"))

        self.assertEqual(response.context["next_event"], event)
        self.assertEqual(response.context["countdown"]["status"], STATE_IN_PROGRESS)
        self.assertContains(response, "EN CURSO")
        self.assertContains(response, 'data-state="in_progress"')

    def test_race_finished_long_ago_has_finished_state(self):
        self.add_race(self.now - timedelta(days=1, hours=3), name="GP Terminado")

        response = self.client.get(reverse("insights"))

        self.assertIsNone(response.context["next_event"])
        self.assertEqual(response.context["countdown"]["status"], STATE_FINISHED)
        self.assertEqual(response.context["countdown"]["label"], "FINALIZADA")
        self.assertContains(response, "FINALIZADA")
        self.assertNotContains(response, "Gran Premio de Australia")

    def test_no_events_has_explicit_empty_state(self):
        response = self.client.get(reverse("teams"))

        self.assertIsNone(response.context["next_event"])
        self.assertEqual(response.context["countdown"]["status"], STATE_NO_RACES)
        self.assertEqual(response.context["countdown"]["label"], "SIN PRÓXIMA CARRERA")
        self.assertEqual(response.context["countdown"]["target"], "")
        self.assertContains(response, "SIN PRÓXIMA CARRERA")
        self.assertContains(response, "No hay eventos.")
        self.assertNotContains(response, "Gran Premio de Australia")

    def test_mobile_timer_shares_the_same_real_target(self):
        _, race = self.add_race(self.now + timedelta(days=4, seconds=37))
        target = race.date_time.isoformat()

        response = self.client.get(reverse("drivers"))

        self.assertContains(response, 'id="countdown-timer"')
        self.assertContains(response, 'id="mobile-countdown-timer"')
        self.assertContains(response, f'data-date="{target}"', count=2)
        self.assertContains(response, f'data-end-date="{(race.date_time + timedelta(hours=2)).isoformat()}"', count=2)

    @override_settings(F1_SEASON_YEAR=2027)
    def test_season_year_is_configurable(self):
        other_season = make_season(2027)
        event, race = self.add_race(self.now + timedelta(days=7))
        other_event = make_event(other_season, round_number=1, name="GP 2027")
        make_session(other_event, name="Race", date_time=self.now + timedelta(days=9))

        response = self.client.get(reverse("drivers"))

        self.assertEqual(response.context["season_year"], 2027)
        self.assertEqual(list(response.context["calendar_events"]), [other_event])
        self.assertEqual(response.context["next_event"], other_event)
        self.assertNotIn(event, list(response.context["calendar_events"]))
        self.assertContains(response, "F1 2027 Season Hub")


class StandingsContextTests(TestCase):
    """El processor solo lee la BD: nunca llama a Ergast ni a F1TV."""

    def setUp(self):
        self.driver_model, self.constructor_model = _standings_models()
        if self.driver_model is None or self.constructor_model is None:
            self.skipTest("Los modelos de standings aún no fueron creados")
        self.season = make_season(2026)
        try:
            self.driver_row = self.driver_model.objects.create(
                season_year=2026,
                position=1,
                points=25,
                wins=1,
                driver_code="VER",
                driver_name="Max Verstappen",
                constructor_name="Red Bull",
            )
            self.team_row = self.constructor_model.objects.create(
                season_year=2026, position=1, points=25, wins=1,
                constructor_name="Red Bull",
            )
        except Exception as exc:
            self.skipTest(f"Tabla de standings aún no migrada: {exc}")

    def test_context_exposes_standings_for_the_active_season(self):
        context = race_context(None)

        self.assertEqual(list(context["driver_standings"]), [self.driver_row])
        self.assertEqual(list(context["constructor_standings"]), [self.team_row])
        self.assertEqual(context["standings_year"], 2026)
        self.assertEqual(context["standings_source"], "FastF1 (Ergast/Jolpica), sin F1TV")

    def test_other_seasons_are_reported_but_not_mixed_in(self):
        self.driver_model.objects.create(
            season_year=2025, position=1, points=400, wins=10,
            driver_code="OLD", driver_name="Piloto viejo",
            constructor_name="Equipo viejo",
        )

        context = race_context(None)

        self.assertEqual(list(context["driver_standings"]), [self.driver_row])
        self.assertNotIn(2025, [row.season_year for row in context["driver_standings"]])
        self.assertIn(2025, context["standings_other_years"])

    def test_empty_database_keeps_explicit_empty_state(self):
        self.driver_model.objects.all().delete()
        self.constructor_model.objects.all().delete()

        context = race_context(None)

        self.assertEqual(context["driver_standings"], [])
        self.assertEqual(context["constructor_standings"], [])
