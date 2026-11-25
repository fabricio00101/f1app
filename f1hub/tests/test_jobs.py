"""Tests de trabajos persistentes de telemetría (sin red, sin FastF1 real).

Se usa ``TransactionTestCase`` porque el worker corre en otro hilo y necesita
ver las filas confirmadas en la BD (``TestCase`` las deja dentro de una
transacción no visible para otras conexiones).
"""

import os
import shutil
import tempfile
import threading
import time
from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from f1hub import jobs as jobs_module
from f1hub.jobs import (
    STATUS_ERROR,
    STATUS_GENERATING,
    STATUS_PENDING,
    STATUS_READY,
    TELEMETRY_USER_ERROR,
    clear_jobs,
    get_job,
    start_job,
)
from f1hub.models import STATUS_GENERATING as MODEL_GENERATING
from f1hub.models import STATUS_READY as MODEL_READY
from f1hub.models import TelemetryJob as JobRow
from f1hub.services import TELEMETRY_UNAVAILABLE_MESSAGE, TelemetryUnavailable, build_cache_key

from .helpers import make_driver, make_event, make_season, make_session

PLOT_PATH = "telemetry/tel_prueba.png"


class JobRegistryTests(TransactionTestCase):
    def setUp(self):
        clear_jobs()
        self.addCleanup(clear_jobs)
        # Registramos los hilos para esperarlos antes de que el test termine:
        # un worker escribiendo durante el flush es la causa del lock de SQLite.
        self.workers = []
        real_launch = jobs_module._launch_worker

        def launch_and_register(*args, **kwargs):
            thread = real_launch(*args, **kwargs)
            if thread is not None:
                self.workers.append(thread)
            return thread

        patcher = patch("f1hub.jobs._launch_worker", side_effect=launch_and_register)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._join_workers)
        self.started = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()
        self.season = make_season(2026)
        self.event = make_event(self.season, round_number=1)
        self.session = make_session(self.event, name="Race")
        self.col = make_driver("COL", "Franco Colapinto", "Alpine", "ARG")
        self.ver = make_driver("VER", "Max Verstappen", "Red Bull", "NED")

    def _join_workers(self):
        """El worker siempre debe terminar antes de que cierre la transacción."""
        for thread in self.workers:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), "El worker sigue escribiendo en la BD")
        self.workers.clear()

    def _empty_media(self):
        """MEDIA_ROOT temporal y vacío, sin archivos de PNG."""
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)
        return temp_dir

    def _with_plot(self, directory):
        os.makedirs(os.path.join(directory, "telemetry"), exist_ok=True)
        with open(os.path.join(directory, "telemetry", "tel_prueba.png"), "wb") as fh:
            fh.write(b"png")

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
        """Espera el estado final del worker leyendo siempre desde la BD."""
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
        media = self._empty_media()

        with override_settings(MEDIA_ROOT=media):
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

        # El estado final y las claves ajenas viven en la BD.
        self.assertEqual(JobRow.objects.count(), 1)
        row = JobRow.objects.get(key=job.key)
        self.assertEqual(row.status, MODEL_READY)
        self.assertEqual(row.plot_path, PLOT_PATH)
        self.assertEqual(row.session_id, self.session.pk)
        self.assertEqual({row.driver1_id, row.driver2_id},
                         {self.col.pk, self.ver.pk})
        self.assertIsNotNone(row.started_at)
        self.assertIsNotNone(row.finished_at)

    @patch("f1hub.jobs.get_or_generate_telemetry_plot")
    def test_failure_is_persisted_logged_and_exposed_as_friendly_message(self, generate):
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

        row = JobRow.objects.get(key=job.key)
        self.assertEqual(row.status, STATUS_ERROR)
        self.assertEqual(row.error, TELEMETRY_USER_ERROR)
        self.assertIsNotNone(row.finished_at)

    @patch("f1hub.jobs.get_or_generate_telemetry_plot")
    def test_domain_error_message_is_persisted_for_the_ui(self, generate):
        generate.side_effect = TelemetryUnavailable(TELEMETRY_UNAVAILABLE_MESSAGE)

        with self.assertLogs("f1hub.jobs", level="WARNING") as logs:
            job = start_job(self.session, self.col, self.ver)
            state = self._wait_for_status(job.key, STATUS_ERROR)

        self.assertEqual(state.error, TELEMETRY_UNAVAILABLE_MESSAGE)
        self.assertEqual(JobRow.objects.get(key=job.key).error, TELEMETRY_UNAVAILABLE_MESSAGE)
        self.assertIn(TELEMETRY_UNAVAILABLE_MESSAGE, "\n".join(logs.output))

    @patch("f1hub.jobs.get_or_generate_telemetry_plot", return_value=PLOT_PATH)
    def test_unknown_key_and_clear_jobs(self, generate):
        self.assertIsNone(get_job("inexistente"))
        job = start_job(self.session, self.col, self.ver)
        self.assertIsNotNone(get_job(job.key))
        self._wait_for_status(job.key, STATUS_READY)
        clear_jobs()
        self.assertIsNone(get_job(job.key))
        self.assertEqual(JobRow.objects.count(), 0)

    @patch("f1hub.jobs.get_or_generate_telemetry_plot", return_value=PLOT_PATH)
    def test_ready_job_with_existing_plot_is_reused(self, generate):
        media = self._empty_media()
        self._with_plot(media)
        key = build_cache_key(self.session, self.col, self.ver)
        JobRow.objects.create(
            key=key,
            session=self.session,
            driver1=self.col,
            driver2=self.ver,
            status=MODEL_READY,
            plot_path=PLOT_PATH,
        )

        with override_settings(MEDIA_ROOT=media):
            state = start_job(self.session, self.col, self.ver)

        self.assertEqual(state.status, STATUS_READY)
        self.assertEqual(state.plot_path, PLOT_PATH)
        generate.assert_not_called()

    @patch("f1hub.jobs.get_or_generate_telemetry_plot", return_value=PLOT_PATH)
    def test_ready_job_without_plot_is_regenerated(self, generate):
        media = self._empty_media()
        key = build_cache_key(self.session, self.col, self.ver)
        JobRow.objects.create(
            key=key,
            session=self.session,
            driver1=self.col,
            driver2=self.ver,
            status=MODEL_READY,
            plot_path=PLOT_PATH,
        )

        with override_settings(MEDIA_ROOT=media):
            restarted = start_job(self.session, self.col, self.ver)
            self.assertEqual(restarted.status, STATUS_PENDING)
            state = self._wait_for_status(key, STATUS_READY)

        self.assertEqual(state.plot_path, PLOT_PATH)
        self.assertEqual(generate.call_count, 1)

    @patch("f1hub.jobs.get_or_generate_telemetry_plot", return_value=PLOT_PATH)
    def test_stale_job_is_marked_error_and_restarted_after_restart(self, generate):
        """Simula un worker muerto: el sondeo falla y el próximo request reintenta."""
        key = build_cache_key(self.session, self.col, self.ver)
        JobRow.objects.create(
            key=key,
            session=self.session,
            driver1=self.col,
            driver2=self.ver,
            status=MODEL_GENERATING,
            started_at=timezone.now() - timedelta(hours=1),
        )
        # update() no dispara auto_now, así podemos simular antigüedad real.
        JobRow.objects.filter(key=key).update(
            updated_at=timezone.now() - timedelta(hours=1)
        )

        stale = get_job(key)
        self.assertEqual(stale.status, STATUS_ERROR)
        self.assertEqual(stale.error, TELEMETRY_USER_ERROR)
        self.assertEqual(JobRow.objects.get(key=key).status, STATUS_ERROR)

        restarted = start_job(self.session, self.col, self.ver)
        self.assertEqual(restarted.status, STATUS_PENDING)
        state = self._wait_for_status(key, STATUS_READY)
        self.assertEqual(state.plot_path, PLOT_PATH)
        self.assertEqual(generate.call_count, 1)
