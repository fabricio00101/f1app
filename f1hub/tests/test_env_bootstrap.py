"""Tests del bootstrap de entorno local: sin red y con directorios temporales."""

import io
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from config.env_bootstrap import ensure_local_env

# Juego de caracteres que django.core.management.utils.get_random_secret_key usa.
SECRET_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)")


@contextmanager
def clean_environment():
    """Aísla sólo las dos variables que decide el bootstrap."""
    with patch.dict(os.environ):
        os.environ.pop("DJANGO_SECRET_KEY", None)
        os.environ.pop("DJANGO_DEBUG", None)
        yield


def read_env(env_path):
    """Parsea el .env generado con la misma gramática simple de settings.py."""
    values = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


class EnvBootstrapTests(SimpleTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.project_dir = Path(self.tmpdir.name)
        self.stderr = io.StringIO()

    def test_creates_env_with_debug_and_secret_when_nothing_is_configured(self):
        with clean_environment():
            environ = dict(os.environ)

            result = ensure_local_env(
                self.project_dir, environ=environ, stderr=self.stderr
            )

            env_path = self.project_dir / ".env"
            self.assertEqual(result, env_path)
            values = read_env(env_path)
            self.assertEqual(values["DJANGO_DEBUG"], "1")
            self.assertTrue(values["DJANGO_SECRET_KEY"])
            self.assertEqual(environ["DJANGO_DEBUG"], "1")
            self.assertEqual(environ["DJANGO_SECRET_KEY"], values["DJANGO_SECRET_KEY"])
            self.assertEqual(os.environ.get("DJANGO_DEBUG"), None)
            self.assertEqual(os.environ.get("DJANGO_SECRET_KEY"), None)

        message = self.stderr.getvalue()
        self.assertEqual(len(message.splitlines()), 1)
        self.assertIn(str(env_path), message)
        self.assertIn("DJANGO_DEBUG=1", message)
        self.assertIn("DJANGO_SECRET_KEY", message)

    def test_does_not_overwrite_an_existing_env(self):
        env_path = self.project_dir / ".env"
        env_path.write_text(
            "# Configuración del usuario\nDJANGO_DEBUG=0\n"
            "DJANGO_SECRET_KEY=secret-original\n",
            encoding="utf-8",
        )
        original = env_path.read_text(encoding="utf-8")
        with clean_environment():
            environ = dict(os.environ)

            result = ensure_local_env(
                self.project_dir, environ=environ, stderr=self.stderr
            )

            self.assertIsNone(result)
            self.assertEqual(env_path.read_text(encoding="utf-8"), original)
            self.assertNotIn("DJANGO_DEBUG", environ)
            self.assertNotIn("DJANGO_SECRET_KEY", environ)

        self.assertEqual(self.stderr.getvalue(), "")

    def test_respects_real_environment_variables(self):
        env_path = self.project_dir / ".env"
        for key, value in (("DJANGO_DEBUG", "0"), ("DJANGO_SECRET_KEY", "real-secret")):
            with self.subTest(key=key):
                with patch.dict(os.environ, {key: value}):
                    # Limpiamos la otra variable para aislar cada caso.
                    other = (
                        "DJANGO_SECRET_KEY" if key == "DJANGO_DEBUG" else "DJANGO_DEBUG"
                    )
                    with patch.dict(os.environ):
                        os.environ.pop(other, None)

                        result = ensure_local_env(
                            self.project_dir, environ=dict(os.environ), stderr=self.stderr
                        )

                        self.assertIsNone(result)
                        self.assertFalse(env_path.exists())
                        self.assertEqual(os.environ[key], value)

        self.assertEqual(self.stderr.getvalue(), "")

    def test_generated_secrets_are_valid_and_different(self):
        with clean_environment():
            secrets = []
            for index in range(2):
                directory = self.project_dir / f"proyecto-{index}"
                directory.mkdir()
                environ = {}
                ensure_local_env(directory, environ=environ, stderr=io.StringIO())
                secrets.append(environ["DJANGO_SECRET_KEY"])

        self.assertNotEqual(secrets[0], secrets[1])
        for secret in secrets:
            self.assertEqual(len(secret), 50)
            self.assertTrue(set(secret) <= SECRET_CHARS)
