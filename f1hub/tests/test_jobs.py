"""Tests del registro de trabajos en segundo plano (sin red, sin hilos reales de FastF1)."""

import threading
import time
from unittest.mock import patch

from django.test import TestCase

from f1hub.jobs import (
    STATUS_ERROR,
    STATUS_GENERATING,
    STATUS_READY,
    TELEMETRY_USER_ERROR,
    clear_jobs,
    get_job,
    start_job,
)

from .helpers import make_driver, make_event, make_season, make_session

PLOT_PATH = "telemetry/tel_prueba.png"


class JobRegistryTests(TestCase):
    def setUp(self):
        clear_jobs()
        self.addCleanup(clear_jobs)
        self.started = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()
        self.season = make_season(2026)
        self.event = make_event(self.season, round_number=1)
        self.session = make_session(self.event, name="Race")
        self.col = make_driver("COL", "Franco Colapinto", "Alpine", "ARG")
        self.ver = make_driver("VER", "Max Verstappen", "Red Bull", "NED")

    def _delayed_success(self, session, driver1, driver2):
        self.started.set()
        self.release.wait(timeout=3)
        self.done.set()
        return PLOT_PATH

    def _delayed_failure(self, session, driver1, driver2):
        self.started.set()
        self.release.wait(timeout=3)
        self.done.set()
        raise RuntimeError("detalle tecnico del fallo")

    def _wait_for_status(self, key, status):
        """Espera el estado final del worker sin depender de sleeps largos."""
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = get_job(key)
            if state.status == status:
                return state
            time.sleep(0.01)
        self.fail(f"El trabajo {key} no llegó a {status}")

    @patch("f1hub.jobs.get_or_generate_telemetry_plot")
    def test_job_finishes_in_background_and_is_deduplicated(self, generate):
        generate.side_effect = self._delayed_success

        job = start_job(self.session, self.col, self.ver)

        self.assertTrue(self.started.wait(timeout=3))
        self.assertEqual(get_job(job.key).status, STATUS_GENERATING)
        # Otra petición con la pareja invertida reutiliza el mismo trabajo.
        same = start_job(self.session, self.ver, self.col)
        self.assertEqual(same.key, job.key)
        self.assertEqual(generate.call_count, 1)

        self.release.set()
        self.assertTrue(self.done.wait(timeout=3))
        state = self._wait_for_status(job.key, STATUS_READY)
        self.assertEqual(state.plot_path, PLOT_PATH)
        self.assertEqual(generate.call_count, 1)

    @patch("f1hub.jobs.get_or_generate_telemetry_plot")
    def test_failure_is_logged_and_exposed_as_friendly_message(self, generate):
        generate.side_effect = self._delayed_failure

        job = start_job(self.session, self.col, self.ver)
        self.assertTrue(self.started.wait(timeout=3))

        with self.assertLogs("f1hub.jobs", level="ERROR") as logs:
            self.release.set()
            self.assertTrue(self.done.wait(timeout=3))
            state = self._wait_for_status(job.key, STATUS_ERROR)

        self.assertEqual(state.status, STATUS_ERROR)
        self.assertEqual(state.error, TELEMETRY_USER_ERROR)
        self.assertNotIn("detalle tecnico del fallo", state.error)
        self.assertIn("detalle tecnico del fallo", "\n".join(logs.output))

    @patch("f1hub.jobs.get_or_generate_telemetry_plot", return_value=PLOT_PATH)
    def test_unknown_key_and_clear_jobs(self, generate):
        self.assertIsNone(get_job("inexistente"))
        job = start_job(self.session, self.col, self.ver)
        self.assertIsNotNone(get_job(job.key))
        self._wait_for_status(job.key, STATUS_READY)
        clear_jobs()
        self.assertIsNone(get_job(job.key))
