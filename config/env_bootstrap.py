"""Arranque local sin configuración manual.

Este módulo no depende de ``django.conf.settings``: se importa desde
``manage.py`` antes de que Django inicialice la configuración. Si no hay
ninguna variable de Django definida en el entorno y tampoco un ``.env``,
genera uno sólo para desarrollo con DEBUG activo y una clave aleatoria.
"""

import os
import sys
from pathlib import Path

from django.core.management.utils import get_random_secret_key


def ensure_local_env(project_dir, *, environ=None, stderr=None):
    """Crea y carga un ``.env`` de desarrollo cuando no hay nada configurado.

    No sobrescribe nada: si ``DJANGO_SECRET_KEY`` o ``DJANGO_DEBUG`` ya están
    en el entorno, o si existe ``project_dir/.env``, no hace cambios. Devuelve
    la ruta del archivo creado o ``None`` cuando no hubo que generarlo.

    ``environ`` y ``stderr`` son inyectables para poder probar la función sin
    modificar el entorno real del proceso de tests.
    """
    environ = os.environ if environ is None else environ
    stderr = sys.stderr if stderr is None else stderr

    env_path = Path(project_dir) / ".env"
    if (
        "DJANGO_SECRET_KEY" in environ
        or "DJANGO_DEBUG" in environ
        or env_path.exists()
    ):
        return None

    secret = get_random_secret_key()
    env_path.write_text(
        "# Generado automáticamente para desarrollo local. No subir a Git.\n"
        "DJANGO_DEBUG=1\n"
        f"DJANGO_SECRET_KEY={secret}\n",
        encoding="utf-8",
    )
    # El loader de config/settings.py usa setdefault: las variables reales
    # del proceso siempre tienen prioridad sobre el archivo.
    environ.setdefault("DJANGO_DEBUG", "1")
    environ.setdefault("DJANGO_SECRET_KEY", secret)

    print(
        f"[f1app] Generado {env_path} para desarrollo "
        "(DJANGO_DEBUG=1, DJANGO_SECRET_KEY aleatorio); no versionarlo.",
        file=stderr,
    )
    return env_path
