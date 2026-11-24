# Ejecución de la app y pruebas

**Fecha:** 24 de noviembre de 2026 (America/Buenos_Aires)  
**Proyecto:** F1 2026 Season Hub  
**Objetivo:** registrar qué se pudo ejecutar, resultados y bloqueos para el siguiente agente.

## Entorno utilizado

- Windows / PowerShell.
- Python 3.15.2 (`C:\Python315\python.exe`).
- Al inicio no había entorno virtual `venv` ni Django en el intérprete disponible.
- Se intentó `python -m pip install -r requirements.txt`. La instalación completa falló durante la preparación de pandas: pip descargó la distribución fuente y Meson no pudo parsear la salida de `vswhere.exe` (`Could not parse vswhere.exe output`). Esto se relaciona con la combinación de Python disponible/dependencias; no es un error de la aplicación.
- Para poder ejecutar Django se instaló Django 6.1.3 en el site de usuario de Python. No se logró instalar FastF1 ni pandas. La instalación no modificó `requirements.txt`.

## Resultados

| Comando/acción | Resultado | Detalle |
|---|---|---|
| `python manage.py check` antes de instalar Django | Bloqueado | `ModuleNotFoundError: No module named 'django'`. |
| `python -m pip install -r requirements.txt` | Falló | Error de build/metadata de pandas al invocar Meson; `vswhere.exe` no se pudo parsear. |
| `python -m pip install Django` | Correcto | Django 6.1.3 y dependencias instalados en el site de usuario. FastF1/pandas siguen ausentes. |
| `python manage.py check` | Correcto | `System check identified no issues (0 silenced)`. |
| `python manage.py migrate --noinput` | Correcto | Se aplicaron migraciones de Django y `f1hub.0001_initial` a SQLite local. |
| `python manage.py test` | Falló | El descubrimiento encontró `test_driver_keys.py`, `test_f1.py` y `test_telemetry.py`; los tres fallaron al importar `fastf1`. No llegaron a ejecutarse comprobaciones funcionales. |
| `python manage.py test f1hub` | Correcto con observación | Terminó con `NO TESTS RAN`; `f1hub/tests.py` no contiene casos. |
| `python manage.py runserver 127.0.0.1:8000 --noreload` + petición HTTP a rutas | Correcto | `/`, `/drivers/`, `/teams/` y `/insights/` respondieron HTTP 200. El servidor se detuvo al acabar la comprobación. |

## Prueba del servidor

Se aplicaron migraciones para crear la base local vacía (ignorada por Git) y luego se inició el servidor de desarrollo. Con `Invoke-WebRequest` se verificaron estas respuestas:

```text
/             200 (14362 bytes)
/drivers/     200 (6766 bytes)
/teams/       200 (6339 bytes)
/insights/    200 (6776 bytes)
```

Esto confirma que Django renderiza las cuatro rutas con la base vacía. No valida la apariencia en navegador, contenido poblado, sincronización FastF1, telemetría ni comportamiento de producción. El servidor ya está detenido.

## Bloqueos y observaciones para continuar

1. **Compatibilidad de dependencias:** el intérprete disponible es Python 3.15.2 y `requirements.txt` no fija versiones. La instalación de pandas intentó compilar desde fuente y no encontró una configuración de Visual Studio usable. Usar una versión de Python compatible con wheels disponibles (por ejemplo, la recomendada por FastF1/pandas) o fijar un entorno probado; después reinstalar todos los requisitos.
2. **Pruebas no aisladas:** `python manage.py test` está descubriendo scripts manuales de la raíz como tests. Estos importan FastF1 y dependen de datos/red. Conviene trasladarlos a pruebas estructuradas o separarlos del descubrimiento Django, y escribir casos automatizados de vistas/modelos sin red.
3. **Sin cobertura de la app:** `python manage.py test f1hub` reporta cero tests. El código todavía no tiene pruebas automatizadas de rutas, próximo evento, calendario, sincronizadores o servicio de telemetría.
4. **Sin datos locales:** la base creada por `migrate` está vacía. No se ejecutaron `sync_schedule`, `sync_drivers` ni `test_telemetry.py`; además requieren FastF1 y potencialmente acceso a datos remotos.
5. **Siguiente ejecución sugerida:** con un Python soportado y dependencias instaladas, ejecutar `python manage.py check`, `python manage.py test`, ambos comandos `sync_*`, iniciar `runserver` y validar vistas con datos. Ejecutar pruebas de FastF1 solo como pruebas de integración separadas, dejando claro que usan red/cache.

## Estado de archivos

Este informe no cambia el código de la aplicación. La base SQLite creada por las migraciones está excluida por `.gitignore`. El servidor de desarrollo fue detenido tras las comprobaciones.
