"""Tests de la página de análisis con datos reales creados en setUp (sin red)."""

from datetime import date as date_cls, datetime, time, timedelta, timezone as dt_timezone

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import dateformat, timezone

from f1hub import insights
from f1hub.models import Driver, Event, Session, TelemetryCache

from .helpers import make_driver, make_event, make_season, make_session


class InsightsPageTests(TestCase):
    def setUp(self):
        self.season = make_season(2026)
        self.now = timezone.now()

        self.old_event = make_event(
            self.season,
            round_number=1,
            event_date=timezone.localdate() - timedelta(days=12),
            name="Gran Premio de Prueba Viejo",
            location="Sede Vieja",
        )
        self.recent_event = make_event(
            self.season,
            round_number=2,
            event_date=timezone.localdate() - timedelta(days=3),
            name="Gran Premio de Prueba Reciente",
            location="Sede Reciente",
        )
        self.old_race = make_session(
            self.old_event, name="Race", date_time=self.now - timedelta(days=12)
        )
        self.recent_race = make_session(
            self.recent_event, name="Race", date_time=self.now - timedelta(days=3)
        )
        make_session(
            self.recent_event, name="FP1", date_time=self.now - timedelta(days=4)
        )

        local_next = timezone.localdate() + timedelta(days=3)
        self.next_start = timezone.make_aware(
            datetime.combine(local_next, time(12)), timezone.get_current_timezone()
        )
        self.next_event = make_event(
            self.season,
            round_number=3,
            event_date=local_next,
            name="Gran Premio de Prueba Futuro",
            location="Sede Futura",
        )
        self.next_race = make_session(
            self.next_event, name="Race", date_time=self.next_start
        )

        self.col = make_driver("COL", "Franco Colapinto", "Alpine F1 Team", "ARG")
        self.col.season = self.season
        self.col.save(update_fields=["season"])
        self.ver = make_driver("VER", "Max Verstappen", "Red Bull", "NED")
        self.ver.season = self.season
        self.ver.save(update_fields=["season"])

        self.cache = TelemetryCache.objects.create(
            session=self.recent_race,
            driver1=self.col,
            driver2=self.ver,
            file_path="telemetry/tel_prueba.png",
        )

    def test_page_shows_real_calendar_teams_and_season_totals(self):
        response = self.client.get(reverse("insights"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gran Premio de Prueba Futuro")
        self.assertContains(response, "Sede Futura")
        self.assertContains(response, "Gran Premio de Prueba Reciente")
        self.assertContains(response, "Sede Reciente")
        self.assertContains(
            response,
            dateformat.format(timezone.localdate() - timedelta(days=3), "d M Y"),
        )
        self.assertContains(response, "Alpine F1 Team")
        self.assertContains(response, "Red Bull")
        self.assertContains(response, "TEMPORADA 2026")

        data = response.context["insights"]
        self.assertEqual(data["next_gp"]["event"], self.next_event)
        self.assertEqual(data["next_gp"]["days"], 3)
        self.assertEqual(
            [row["name"] for row in data["recent_gps"]],
            ["Gran Premio de Prueba Reciente", "Gran Premio de Prueba Viejo"],
        )
        self.assertEqual(data["recent_gps"][0]["location"], "Sede Reciente")
        self.assertEqual(data["season"]["sessions"], 4)
        self.assertEqual(data["season"]["past_sessions"], 3)
        self.assertEqual(data["season"]["future_sessions"], 1)
        self.assertEqual(data["season"]["drivers"], 2)
        self.assertEqual(data["season"]["team_count"], 2)
        self.assertEqual(data["season"]["teams"], ["Alpine F1 Team", "Red Bull"])

    def test_placeholder_and_fake_live_labels_are_gone(self):
        response = self.client.get(reverse("insights"))

        self.assertNotContains(response, "ANÁLISIS AVANZADO")
        self.assertNotContains(response, "estará completamente operativo")
        self.assertNotContains(response, "AWS Insights")
        self.assertNotContains(response, "EN VIVO")
        self.assertContains(response, "Sin clasificación oficial cargada")

    def test_recent_gps_are_limited_and_newest_first(self):
        rows = insights.recent_gps(limit=1, now=self.now, year=2026)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Gran Premio de Prueba Reciente")
        self.assertEqual(rows[0]["location"], "Sede Reciente")
        self.assertEqual(rows[0]["round"], 2)

    def test_next_gp_accepts_the_race_already_selected_by_the_layout(self):
        data = insights.next_gp(race=self.next_race, now=self.now)

        self.assertEqual(data["event"], self.next_event)
        self.assertEqual(data["starts_at"], self.next_start)
        self.assertEqual(data["days"], 3)
        self.assertTrue(data["has_race"])

    def test_season_summary_ignores_other_seasons(self):
        other = make_season(2027)
        event = make_event(
            other, round_number=1, event_date=date_cls(2027, 1, 1), name="GP 2027"
        )
        make_session(
            event,
            name="Race",
            date_time=datetime(2027, 1, 1, 12, tzinfo=dt_timezone.utc),
        )
        other_driver = make_driver("OTH", "Otro Piloto", "Otro Equipo", "GBR")
        other_driver.season = other
        other_driver.save(update_fields=["season"])

        data = insights.season_summary(now=self.now, year=2026)

        self.assertEqual(data["sessions"], 4)
        self.assertEqual(data["drivers"], 2)
        self.assertEqual(data["teams"], ["Alpine F1 Team", "Red Bull"])

    def test_telemetry_status_reports_real_cached_comparisons(self):
        data = insights.telemetry_status(year=2026)

        self.assertEqual(data["comparisons"], 1)
        self.assertEqual(data["sessions"], 1)
        self.assertTrue(data["available"])
        self.assertIsNotNone(data["last_created_at"])
        self.assertContains(self.client.get(reverse("insights")), "CACHÉ ACTIVA")

        TelemetryCache.objects.all().delete()
        response = self.client.get(reverse("insights"))
        data = insights.telemetry_status(year=2026)

        self.assertEqual(data["comparisons"], 0)
        self.assertFalse(data["available"])
        self.assertContains(response, "Todavía no hay gráficos de telemetría guardados")
        self.assertContains(response, "SIN CACHÉ")

    def test_telemetry_link_describes_lap_times_not_speed(self):
        response = self.client.get(reverse("insights"))

        self.assertContains(response, "Compará tiempos por vuelta")
        self.assertNotContains(response, "vuelta más rápida")

    def test_page_links_to_telemetry_drivers_and_teams(self):
        response = self.client.get(reverse("insights"))

        self.assertContains(response, "ABRIR TELEMETRÍA →")
        self.assertContains(response, "VER PILOTOS →")
        self.assertContains(response, "VER EQUIPOS →")
        self.assertContains(response, f'href="{reverse("telemetry")}"')

    def test_empty_database_shows_explicit_empty_state(self):
        TelemetryCache.objects.all().delete()
        Session.objects.all().delete()
        Event.objects.all().delete()
        Driver.objects.all().delete()

        response = self.client.get(reverse("insights"))
        data = response.context["insights"]

        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["next_gp"]["has_race"])
        self.assertIsNone(data["next_gp"]["days"])
        self.assertEqual(data["recent_gps"], [])
        self.assertEqual(data["season"]["sessions"], 0)
        self.assertEqual(data["season"]["drivers"], 0)
        self.assertContains(response, "No hay una próxima carrera")
        self.assertContains(response, "No hay carreras finalizadas cargadas.")
        self.assertContains(response, "Equipos de la temporada: sin datos.")

    @override_settings(F1_SEASON_YEAR=2027)
    def test_uses_configured_season_year(self):
        other = make_season(2027)
        event = make_event(
            other,
            round_number=1,
            event_date=timezone.localdate() + timedelta(days=5),
            name="GP 2027",
        )
        make_session(event, name="Race", date_time=self.now + timedelta(days=5))

        response = self.client.get(reverse("insights"))

        self.assertEqual(response.context["season_year"], 2027)
        self.assertEqual(response.context["insights"]["season"]["sessions"], 1)
        self.assertContains(response, "TEMPORADA 2027")
        self.assertNotContains(response, "Gran Premio de Prueba Futuro")
