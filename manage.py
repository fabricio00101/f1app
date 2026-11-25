#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # Antes de django.setup() (lo hace execute_from_command_line): en local,
    # sin variables ni .env, generamos uno con DEBUG y una clave aleatoria.
    from config.env_bootstrap import ensure_local_env

    ensure_local_env(Path(__file__).resolve().parent)
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
