"""Guardar y cargar los datos de la app en la carpeta `datos/` del proyecto.

Así los datos viajan con el proyecto en GitHub:
  * `flask --app run guardar-datos`  -> exporta la base de datos y los archivos subidos a `datos/`
  * `flask --app run cargar-datos`   -> reemplaza la base de datos por lo que hay en `datos/`

Sincronización automática (AUTO_GUARDAR, activada por defecto):
  * Unos segundos después de cada cambio en la app, `datos/` se actualiza sola.
  * Al arrancar, si `datos/datos.json` cambió desde la última vez (por ejemplo tras un `git pull`),
    se carga automáticamente. Con la base de datos vacía (proyecto recién clonado) también se carga.
  * Con AUTO_SUBIR=1 además se hace commit y push de `datos/` a GitHub un rato después del último cambio.

Los datos se guardan como JSON (texto), de modo que Git muestra qué cambió en cada commit.
"""
import atexit
import hashlib
import json
import os
import shutil
import subprocess
import threading
from datetime import date, datetime

import click
from flask import current_app, has_app_context
from sqlalchemy import Date, DateTime, event
from sqlalchemy.orm import Session

from . import db

VERSION_FORMATO = 1


def _ruta_json():
    return os.path.join(current_app.config["DATOS_DIR"], "datos.json")


def _carpeta_archivos():
    return os.path.join(current_app.config["DATOS_DIR"], "archivos")


def hay_datos_guardados():
    return os.path.exists(_ruta_json())


def _a_json(valor):
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return valor


# --------------------------------------------------------------------------
# Huella: recuerda qué versión de datos/datos.json corresponde a la base de datos local
# --------------------------------------------------------------------------
def _huella_datos():
    try:
        with open(_ruta_json(), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return None


def _leer_huella_guardada():
    try:
        with open(current_app.config["SYNC_ESTADO"], encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _guardar_huella(huella):
    ruta = current_app.config["SYNC_ESTADO"]
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(huella or "")


# --------------------------------------------------------------------------
# Exportar e importar
# --------------------------------------------------------------------------
def guardar_datos():
    """Exporta todas las tablas a datos/datos.json y copia los archivos subidos a datos/archivos/."""
    tablas = {}
    for tabla in db.metadata.sorted_tables:
        orden = list(tabla.primary_key.columns) or list(tabla.columns)
        filas = db.session.execute(tabla.select().order_by(*orden)).mappings()
        tablas[tabla.name] = [{k: _a_json(v) for k, v in fila.items()} for fila in filas]

    os.makedirs(_carpeta_archivos(), exist_ok=True)
    # Se escribe en un archivo temporal y luego se reemplaza: nunca queda un datos.json a medias
    temporal = _ruta_json() + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump({"version": VERSION_FORMATO, "tablas": tablas}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(temporal, _ruta_json())

    # Copia solo los archivos que usa algún apunte y quita los que ya no se usan
    usados = {a["nombre_almacenado"] for a in tablas.get("apuntes", [])}
    origen = current_app.config["UPLOAD_FOLDER"]
    for nombre in usados:
        ruta_origen = os.path.join(origen, nombre)
        ruta_destino = os.path.join(_carpeta_archivos(), nombre)
        if os.path.exists(ruta_origen) and not os.path.exists(ruta_destino):
            shutil.copy2(ruta_origen, ruta_destino)
    for nombre in os.listdir(_carpeta_archivos()):
        if nombre not in usados:
            os.remove(os.path.join(_carpeta_archivos(), nombre))

    _guardar_huella(_huella_datos())
    return {nombre: len(filas) for nombre, filas in tablas.items()}


def cargar_datos():
    """Reemplaza la base de datos por el contenido de datos/datos.json."""
    with open(_ruta_json(), encoding="utf-8") as f:
        contenido = json.load(f)

    db.session.remove()
    db.drop_all()
    db.create_all()

    for tabla in db.metadata.sorted_tables:  # padres antes que hijos (claves foráneas)
        filas = contenido["tablas"].get(tabla.name, [])
        if not filas:
            continue
        columnas = {c.name: c for c in tabla.columns}
        convertidas = []
        for fila in filas:
            nueva = {}
            for nombre, valor in fila.items():
                columna = columnas.get(nombre)
                if columna is None:  # columna que ya no existe en esta versión
                    continue
                if valor is not None and isinstance(columna.type, DateTime):
                    valor = datetime.fromisoformat(valor)
                elif valor is not None and isinstance(columna.type, Date):
                    valor = date.fromisoformat(valor)
                nueva[nombre] = valor
            convertidas.append(nueva)
        db.session.execute(tabla.insert(), convertidas)
    db.session.commit()

    destino = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(destino, exist_ok=True)
    if os.path.isdir(_carpeta_archivos()):
        for nombre in os.listdir(_carpeta_archivos()):
            shutil.copy2(os.path.join(_carpeta_archivos(), nombre), os.path.join(destino, nombre))

    _guardar_huella(_huella_datos())
    return {nombre: len(filas) for nombre, filas in contenido["tablas"].items()}


def sincronizar_al_iniciar(app, base_vacia):
    """Al arrancar: carga datos/ si la base está vacía o si datos/ cambió desde la última sincronización."""
    if not hay_datos_guardados():
        return False
    if base_vacia:
        if not app.config["AUTO_SEED"]:
            return False
        cargar_datos()
        app.logger.warning("Base de datos vacía: se cargaron los datos guardados en la carpeta datos/.")
        return True
    if not app.config["AUTO_GUARDAR"]:
        return False
    guardada, actual = _leer_huella_guardada(), _huella_datos()
    if guardada is None:
        # Primera vez con sincronización: se toma la base actual como punto de partida
        _guardar_huella(actual)
        app.logger.warning("Sincronización automática activada: los cambios se guardarán en datos/.")
    elif guardada != actual:
        cargar_datos()
        app.logger.warning("La carpeta datos/ cambió (por ejemplo tras un git pull): se cargaron sus datos.")
        return True
    return False


# --------------------------------------------------------------------------
# Subir a GitHub
# --------------------------------------------------------------------------
def _git(*args):
    return subprocess.run(["git", *args], cwd=os.path.dirname(current_app.config["DATOS_DIR"]),
                          capture_output=True, text=True)


def subir_a_github(mensaje="Actualiza datos de la aplicación"):
    """Hace commit y push SOLO de la carpeta datos/. Devuelve False si no había nada nuevo."""
    _git("add", "datos")
    if _git("diff", "--cached", "--quiet", "--", "datos").returncode == 0:
        return False
    commit = _git("commit", "-m", mensaje, "--", "datos")
    if commit.returncode != 0:
        raise RuntimeError("No se pudo hacer commit:\n" + commit.stdout + commit.stderr)
    push = _git("push")
    if push.returncode != 0:
        raise RuntimeError(
            "El commit se hizo, pero falló el push (¿hay cambios nuevos en GitHub? ejecuta 'git pull'):\n"
            + push.stderr
        )
    return True


# --------------------------------------------------------------------------
# Guardado automático después de cada cambio
# --------------------------------------------------------------------------
@event.listens_for(Session, "after_flush")
def _marcar_cambios(session, contexto):
    if session.new or session.dirty or session.deleted:
        session.info["hubo_cambios"] = True


@event.listens_for(Session, "after_commit")
def _despues_de_confirmar(session):
    if not session.info.pop("hubo_cambios", False) or not has_app_context():
        return
    estado = current_app.extensions.get("auto_guardado")
    if estado:
        app = current_app._get_current_object()
        _programar(app, estado, "guardar", app.config["AUTO_GUARDAR_SEGUNDOS"], _guardar_en_segundo_plano)
        if app.config["AUTO_SUBIR"]:
            _programar(app, estado, "subir", app.config["AUTO_SUBIR_SEGUNDOS"], _subir_en_segundo_plano)


@event.listens_for(Session, "after_rollback")
def _descartar_marca(session):
    session.info.pop("hubo_cambios", None)


def _programar(app, estado, tarea, segundos, funcion):
    """Ejecuta `funcion` cuando pasen `segundos` sin cambios nuevos (agrupa varios cambios seguidos)."""
    with estado["lock"]:
        anterior = estado.get(tarea)
        if anterior:
            anterior.cancel()
        temporizador = threading.Timer(segundos, funcion, args=(app, estado))
        temporizador.daemon = True
        estado[tarea] = temporizador
        temporizador.start()


def _guardar_en_segundo_plano(app, estado):
    with estado["lock_trabajo"], app.app_context():
        estado["guardar"] = None
        try:
            guardar_datos()
            app.logger.info("Datos guardados automáticamente en datos/.")
        except Exception:
            app.logger.exception("No se pudieron guardar automáticamente los datos en datos/.")
        finally:
            db.session.remove()


def _subir_en_segundo_plano(app, estado):
    with estado["lock_trabajo"], app.app_context():
        estado["subir"] = None
        try:
            guardar_datos()
            if subir_a_github("Actualiza datos de la aplicación (automático)"):
                app.logger.warning("Datos subidos automáticamente a GitHub.")
        except FileNotFoundError:
            app.logger.warning("AUTO_SUBIR: git no está instalado aquí; los datos quedaron guardados en datos/.")
        except Exception as error:
            app.logger.warning(f"AUTO_SUBIR: no se pudieron subir los datos a GitHub. {error}")
        finally:
            db.session.remove()


def activar_guardado_automatico(app):
    if not app.config["AUTO_GUARDAR"]:
        return
    estado = {"lock": threading.Lock(), "lock_trabajo": threading.Lock(), "guardar": None, "subir": None}
    app.extensions["auto_guardado"] = estado

    def guardar_pendientes_al_salir():
        """Si la app se detiene con un guardado pendiente (p. ej. Ctrl + C), lo hace en ese momento."""
        for tarea, funcion in (("guardar", _guardar_en_segundo_plano), ("subir", _subir_en_segundo_plano)):
            temporizador = estado.get(tarea)
            if temporizador and temporizador.is_alive():
                temporizador.cancel()
                funcion(app, estado)

    atexit.register(guardar_pendientes_al_salir)


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------
def registrar_comandos_datos(app):
    @app.cli.command("guardar-datos")
    @click.option("--subir", is_flag=True, help="Además hace commit y push de la carpeta datos/ a GitHub.")
    def guardar_datos_cmd(subir):
        """Guarda la base de datos y los archivos subidos en la carpeta datos/ del proyecto."""
        conteo = guardar_datos()
        click.echo("Datos guardados en datos/: " + ", ".join(f"{n} {t}" for t, n in conteo.items() if n))
        if not subir:
            click.echo("Para subirlos a GitHub: git add datos && git commit -m \"Actualiza datos\" && git push")
            click.echo("(o vuelve a ejecutar este comando con --subir)")
            return
        try:
            subido = subir_a_github()
        except (RuntimeError, FileNotFoundError) as error:
            raise click.ClickException(str(error))
        click.echo("Datos subidos a GitHub." if subido else "No hay cambios nuevos en los datos; no hay nada que subir.")

    @app.cli.command("cargar-datos")
    @click.option("--si", is_flag=True, help="No pedir confirmación.")
    def cargar_datos_cmd(si):
        """Reemplaza la base de datos actual por los datos guardados en datos/."""
        if not hay_datos_guardados():
            raise click.ClickException("No existe datos/datos.json. Primero ejecuta 'guardar-datos'.")
        if not si:
            click.confirm("Esto reemplaza TODOS los datos actuales por los de la carpeta datos/. ¿Continuar?",
                          abort=True)
        conteo = cargar_datos()
        click.echo("Datos cargados: " + ", ".join(f"{n} {t}" for t, n in conteo.items() if n))
