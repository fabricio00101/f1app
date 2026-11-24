"""Tests de la vista de telemetría con el servicio/hilos mockeados (sin red)."""

from datetime import date as date_cls, datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .helpers import make_driver, make_event, make_season, make_session

PLOT_PATH = "telemetry/tel_prueba.png"


class TelemetryViewTests(TestCase):
    def setUp(self):
        self.season = make_season(2026)
        self.event = make_event(
            self.season,
            round_number=22,
            event_date=date_cls(2026, 11, 21),
            name="Gran Premio de Las Vegas",
        )
        self.fp1 = make_session(
            self.event,
            name="FP1",
            date_time=datetime(2026, 11, 20, 15, tzinfo=dt_timezone.utc),
        )
        self.race = make_session(
            self.event,
            name="Race",
            date_time=datetime(2026, 11, 21, 15, tzinfo=dt_timezone.utc),
        )
        self.col = make_driver("COL", "Franco Colapinto", "Alpine F1 Team", "ARG")
        self.col.season = self.season
        self.col.save(update_fields=["season"])
        self.nor = make_driver("NOR", "Lando Norris", "McLaren", "GBR")
        self.nor.season = self.season
        self.nor.save(update_fields=["season"])
        self.ver = make_driver("VER", "Max Verstappen", "Red Bull", "NED")
        self.ver.season = self.season
        self.ver.save(update_fields=["season"])

    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot")
    def test_returns_200_without_params_and_sensible_defaults(self, cached, start_job):
        cached.return_value = PLOT_PATH

        response = self.client.get(reverse("telemetry"))

        self.assertEqual(response.status_code, 200)
        # Sin parámetros: dos primeros pilotos por nombre y última carrera.
        cached.assert_called_once_with(self.race, self.col, self.nor)
        start_job.assert_not_called()
        self.assertEqual(response.context["d1"], self.col)
        self.assertEqual(response.context["d2"], self.nor)
        self.assertEqual(response.context["selected_session"], self.race)
        self.assertEqual(response.context["error"], "")
        self.assertTrue(response.context["plot_url"].endswith(PLOT_PATH))

    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot")
    def test_renders_image_and_source_metadata(self, cached, start_job):
        cached.return_value = PLOT_PATH

        response = self.client.get(reverse("telemetry"))

        plot_url = response.context["plot_url"]
        self.assertIn("media/", plot_url)
        self.assertContains(response, f'<img src="{plot_url}"')
        self.assertContains(response, 'data-state="success"')
        label = "Gran Premio de Las Vegas – Race – %s" % timezone.localtime(
            self.race.date_time
        ).strftime("%d/%m/%Y")
        self.assertEqual(response.context["source_label"], label)
        self.assertContains(response, label)
        self.assertContains(response, "FastF1")

    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot")
    def test_selects_requested_drivers_and_session(self, cached, start_job):
        cached.return_value = PLOT_PATH

        response = self.client.get(
            reverse("telemetry"),
            {"d1": "VER", "d2": "COL", "session": self.fp1.pk},
        )

        self.assertEqual(response.status_code, 200)
        cached.assert_called_once_with(self.fp1, self.ver, self.col)
        start_job.assert_not_called()
        self.assertEqual(response.context["d1"], self.ver)
        self.assertEqual(response.context["d2"], self.col)
        self.assertEqual(response.context["selected_session"], self.fp1)
        self.assertContains(response, "Gran Premio de Las Vegas – FP1 –")

    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot")
    def test_cache_lookup_failure_shows_friendly_error_and_logs_detail(self, cached, start_job):
        cached.side_effect = RuntimeError("detalle tecnico secreto")

        with self.assertLogs("f1hub.views", level="ERROR") as logs:
            response = self.client.get(
                reverse("telemetry"), {"d1": "VER", "d2": "COL"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-state="error"')
        self.assertContains(response, "No se pudo generar la telemetría")
        self.assertNotContains(response, "detalle tecnico secreto")
        self.assertIn("detalle tecnico secreto", "\n".join(logs.output))
        self.assertEqual(response.context["plot_url"], "")
        self.assertNotContains(response, "<img")
        start_job.assert_not_called()

    @patch("f1hub.views.get_cached_telemetry_plot")
    def test_invalid_session_shows_error_without_calling_service(self, cached):
        response = self.client.get(reverse("telemetry"), {"session": "999999"})

        self.assertEqual(response.status_code, 200)
        cached.assert_not_called()
        self.assertContains(response, "La sesión seleccionada no existe.")

    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot")
    def test_drivers_from_another_season_are_rejected_before_generation(self, cached, start_job):
        old = make_driver("ANT", "Piloto 2025", "Equipo viejo", "ITA")
        old.season = make_season(2025)
        old.save(update_fields=["season"])

        response = self.client.get(
            reverse("telemetry"), {"d1": "ANT", "d2": "COL"}
        )

        self.assertEqual(response.status_code, 200)
        cached.assert_not_called()
        start_job.assert_not_called()
        self.assertContains(response, "no pertenece a la temporada 2026")
        self.assertEqual(response.context["plot_url"], "")

    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot", return_value="")
    def test_starts_background_job_when_no_cached_plot(self, cached, start_job):
        start_job.return_value = SimpleNamespace(key="job-123")

        response = self.client.get(
            reverse("telemetry"), {"d1": "VER", "d2": "COL"}
        )

        self.assertEqual(response.status_code, 200)
        cached.assert_called_once_with(self.race, self.ver, self.col)
        start_job.assert_called_once_with(self.race, self.ver, self.col)
        self.assertEqual(response.context["job_key"], "job-123")
        self.assertEqual(response.context["plot_url"], "")
        self.assertContains(response, 'data-job-key="job-123"')
        self.assertContains(response, 'data-state="generando"')
        self.assertContains(response, reverse("telemetry_job_status"))
        # El request termina sin llamar al servicio síncrono.
        self.assertNotContains(response, 'data-state="success"')

    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot", return_value="")
    def test_session_selector_is_limited_and_criterion_is_visible(self, cached, start_job):
        for index in range(60):
            make_session(
                self.event,
                name="Race",
                date_time=datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
                + timedelta(days=index),
            )

        response = self.client.get(reverse("telemetry"))

        self.assertEqual(len(response.context["sessions_list"]), 50)
        self.assertContains(response, "Últimas 50 sesiones de la temporada 2026")
        self.assertEqual(
            response.context["sessions_list"][0].date_time,
            max(s.date_time for s in response.context["sessions_list"]),
        )

    @override_settings(F1_SEASON_YEAR=2027)
    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot")
    def test_configured_season_filters_sessions(self, cached, start_job):
        response = self.client.get(reverse("telemetry"))

        self.assertEqual(response.context["sessions_list"], [])
        self.assertContains(response, "No hay pilotos ni sesiones disponibles")
        cached.assert_not_called()
        start_job.assert_not_called()

    @patch("f1hub.views.start_job")
    @patch("f1hub.views.get_cached_telemetry_plot")
    def test_empty_database_shows_empty_state_without_calling_service(self, cached, start_job):
        from f1hub.models import Driver, Session

        Driver.objects.all().delete()
        Session.objects.all().delete()

        response = self.client.get(reverse("telemetry"))

        self.assertEqual(response.status_code, 200)
        cached.assert_not_called()
        start_job.assert_not_called()
        self.assertContains(response, "No hay pilotos ni sesiones disponibles")

    @patch("f1hub.views.get_job")
    def test_job_status_endpoint_returns_ready_plot_url(self, get_job):
        get_job.return_value = SimpleNamespace(
            status="ready", plot_path=PLOT_PATH, error=""
        )

        response = self.client.get(
            reverse("telemetry_job_status"), {"key": "job-123"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertTrue(response.json()["plot_url"].endswith(PLOT_PATH))
        self.assertEqual(response.json()["error"], "")

    @patch("f1hub.views.get_job")
    def test_job_status_endpoint_returns_error_message(self, get_job):
        get_job.return_value = SimpleNamespace(
            status="error", plot_path="", error="No se pudo generar la telemetría."
        )

        response = self.client.get(
            reverse("telemetry_job_status"), {"key": "job-123"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "error")
        self.assertIn("No se pudo generar", response.json()["error"])

    @patch("f1hub.views.get_job", return_value=None)
    def test_job_status_endpoint_unknown_key(self, get_job):
        response = self.client.get(
            reverse("telemetry_job_status"), {"key": "no-existe"}
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["status"], "unknown")
