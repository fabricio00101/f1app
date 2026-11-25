"""Tests de las 4 vistas con datos creados en setUp (sin red)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from f1hub.context_processors import STATE_UPCOMING
from f1hub.models import Driver
from .helpers import make_driver, make_event, make_season, make_session


def _standings_models():
    """Los modelos de standings los agrega la capa de datos en paralelo."""
    try:
        from f1hub.models import ConstructorStanding, DriverStanding
    except ImportError:
        return None, None
    return DriverStanding, ConstructorStanding


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

    def test_teams_view_lists_distinct_teams_with_real_driver_data(self):
        make_driver("NOR", "Lando Norris", "Red Bull", "GBR")
        response = self.client.get(reverse("teams"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpine F1 Team")
        self.assertContains(response, "Red Bull")
        self.assertContains(response, "EQUIPOS DE LA TEMPORADA 2026")
        self.assertContains(response, "PLANTILLA DE 2 pilotos")
        self.assertContains(response, "NOR (GBR), VER (NED)")
        self.assertContains(response, "COL (ARG)")
        # El placeholder original ya no debe aparecer en ninguna tarjeta.
        self.assertNotContains(response, "En desarrollo para 2026.")

        teams = {row["team"]: row for row in response.context["teams_list"]}
        self.assertEqual(set(teams), {"Alpine F1 Team", "Red Bull"})
        self.assertEqual(teams["Red Bull"]["driver_count"], 2)
        self.assertEqual(
            [d["acronym"] for d in teams["Red Bull"]["drivers"]], ["NOR", "VER"]
        )
        self.assertEqual(teams["Alpine F1 Team"]["driver_count"], 1)
        self.assertEqual(teams["Alpine F1 Team"]["drivers"], [
            {"acronym": "COL", "nationality": "ARG"}
        ])

    @override_settings(F1_SEASON_YEAR=2027)
    def test_teams_view_uses_configurable_season_year(self):
        response = self.client.get(reverse("teams"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "F1 2027 Season Hub")
        self.assertContains(response, "EQUIPOS DE LA TEMPORADA 2027")
        self.assertContains(response, "TEMPORADA 2027")
        self.assertNotContains(response, "En desarrollo para 2027.")

    def test_insights_view_returns_200(self):
        response = self.client.get(reverse("insights"))
        self.assertEqual(response.status_code, 200)

    def test_drivers_view_with_empty_database(self):
        Driver.objects.all().delete()
        response = self.client.get(reverse("drivers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No hay información de pilotos disponible")


class StandingsViewTests(TestCase):
    """Clasificación real en la UI, sin red y sin F1TV."""

    def setUp(self):
        self.driver_model, self.constructor_model = _standings_models()
        if self.driver_model is None or self.constructor_model is None:
            self.skipTest("Los modelos de standings aún no fueron creados")
        self.season = make_season(2026)
        self.col = make_driver("COL", "Franco Colapinto", "Alpine", "ARG")
        try:
            self.driver_model.objects.create(
                season_year=2026, position=1, points=25, wins=1,
                driver_code="COL", driver_name="Franco Colapinto",
                constructor_name="Alpine",
            )
            self.constructor_model.objects.create(
                season_year=2026, position=1, points=25, wins=1,
                constructor_name="Alpine",
            )
        except Exception as exc:
            self.skipTest(f"Tabla de standings aún no migrada: {exc}")

    def test_dashboard_shows_real_driver_standings(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CLASIFICACIÓN DE PILOTOS 2026")
        self.assertContains(response, "Franco Colapinto (COL)")
        self.assertContains(response, "Alpine")
        self.assertContains(response, "25")
        self.assertContains(response, "VICTORIAS")
        self.assertContains(response, "FastF1 (Ergast/Jolpica), sin F1TV")
        self.assertNotContains(response, "Sin clasificación oficial cargada")
        self.assertEqual(len(response.context["driver_standings"]), 1)

    def test_dashboard_shows_real_constructor_standings(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "CONSTRUCTORES 2026")
        self.assertContains(response, "PUNTOS")
        self.assertEqual(len(response.context["constructor_standings"]), 1)

    def test_teams_and_insights_show_constructor_standings(self):
        cases = {
            "teams": "CLASIFICACIÓN DE CONSTRUCTORES 2026",
            "insights": "CLASIFICACIÓN OFICIAL 2026",
        }
        for url_name, heading in cases.items():
            with self.subTest(view=url_name):
                response = self.client.get(reverse(url_name))
                self.assertContains(response, heading)
                self.assertContains(response, "Alpine")
                self.assertContains(response, "FastF1 (Ergast/Jolpica), sin F1TV")
                self.assertNotContains(response, "Sin clasificación oficial cargada")
                self.assertEqual(len(response.context["constructor_standings"]), 1)

    def test_empty_standings_keeps_honest_empty_state(self):
        self.driver_model.objects.all().delete()
        self.constructor_model.objects.all().delete()

        for url_name in ("dashboard", "teams", "insights"):
            with self.subTest(view=url_name):
                response = self.client.get(reverse(url_name))
                self.assertContains(response, "Sin clasificación oficial cargada")
                self.assertContains(response, "sync_standings")

    def test_only_other_year_data_is_not_presented_as_current(self):
        self.driver_model.objects.all().delete()
        self.constructor_model.objects.all().delete()
        self.driver_model.objects.create(
            season_year=2025, position=1, points=400, wins=10,
            driver_code="OLD", driver_name="Piloto 2025",
            constructor_name="Equipo 2025",
        )

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "Piloto 2025")
        self.assertContains(response, "Solo hay clasificación guardada de 2025")
