"""Tests de las 4 vistas con datos creados en setUp (sin red)."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from f1hub.context_processors import STATE_UPCOMING
from f1hub.models import Driver
from .helpers import make_driver, make_event, make_season, make_session


class ViewTests(TestCase):
    def setUp(self):
        self.season = make_season(2026)
        self.now = timezone.now()
        today = timezone.localdate()
        self.past_event = make_event(
            self.season,
            round_number=1,
            event_date=today - timedelta(days=10),
            name="Past Grand Prix",
        )
        self.future_event = make_event(
            self.season,
            round_number=2,
            event_date=today + timedelta(days=10),
            name="Future Grand Prix",
        )
        make_session(
            self.past_event, name="Race", date_time=self.now - timedelta(days=10)
        )
        # El processor elige la primera sesión Race futura por date_time;
        # sin esta sesión el futuro evento no sería considerado «próximo».
        self.future_race = make_session(
            self.future_event, name="Race", date_time=self.now + timedelta(days=10)
        )
        self.ver = make_driver("VER", "Max Verstappen", "Red Bull", "NED")
        self.col = make_driver("COL", "Franco Colapinto", "Alpine F1 Team", "ARG")

    def test_dashboard_returns_200_with_expected_context(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "F1 2026 Season Hub")
        # La vista ya no inyecta estos datos: vienen de race_context.
        self.assertEqual(response.context["next_event"], self.future_event)
        self.assertNotEqual(response.context["next_event"], self.past_event)
        self.assertEqual(response.context["countdown"]["status"], STATE_UPCOMING)
        self.assertEqual(
            response.context["countdown"]["target"],
            self.future_race.date_time.isoformat(),
        )
        self.assertEqual(response.context["colapinto"], self.col)
        self.assertEqual(
            list(response.context["calendar_events"]),
            [self.past_event, self.future_event],
        )
        self.assertEqual(
            [team["name"] for team in response.context["constructors"]],
            ["Alpine F1 Team", "Red Bull"],
        )
        self.assertTrue(
            all(set(team) == {"name"} for team in response.context["constructors"])
        )
        self.assertEqual(response.context["today"], timezone.localdate())

    def test_dashboard_uses_real_driver_data_without_fake_standings(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "FRANCO COLAPINTO")
        self.assertContains(response, "Alpine F1 Team")
        self.assertContains(response, "ARG")
        self.assertContains(response, "Sin clasificación oficial cargada")
        self.assertNotContains(response, "Williams Racing")
        self.assertNotContains(response, "EN VIVO")
        self.assertNotContains(response, "78%")
        self.assertNotContains(response, "342")

    def test_dashboard_without_drivers_shows_explicit_empty_state(self):
        Driver.objects.all().delete()
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SIN DATOS")
        self.assertContains(response, "No hay equipos disponibles.")
        self.assertContains(response, "Sin telemetría disponible.")

    def test_drivers_view_lists_drivers_ordered_by_name(self):
        response = self.client.get(reverse("drivers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Max Verstappen")
        self.assertContains(response, "Franco Colapinto")
        self.assertEqual(list(response.context["drivers_list"]), [self.col, self.ver])

    def test_teams_view_lists_distinct_teams(self):
        response = self.client.get(reverse("teams"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpine F1 Team")
        teams = [row["team"] for row in response.context["teams_list"]]
        self.assertEqual(sorted(teams), ["Alpine F1 Team", "Red Bull"])

    def test_insights_view_returns_200(self):
        response = self.client.get(reverse("insights"))
        self.assertEqual(response.status_code, 200)

    def test_drivers_view_with_empty_database(self):
        Driver.objects.all().delete()
        response = self.client.get(reverse("drivers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No hay información de pilotos disponible")
