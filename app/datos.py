"""Guardar y cargar los datos de la app en la carpeta `datos/` del proyecto.

Así los datos viajan con el proyecto en GitHub:
  * `flask --app run guardar-datos`  -> exporta la base de datos y los archivos subidos a `datos/`
  * `flask --app run cargar-datos`   -> reemplaza la base de datos por lo que hay en `datos/`
  * Al arrancar con la base de datos vacía (p. ej. recién clonado) se carga `datos/` automáticamente.

Los datos se guardan como JSON (texto), de modo que Git muestra qué cambió en cada commit.
"""
import json
import os
import shutil
import subprocess
from datetime import date, datetime

import click
from flask import current_app
from sqlalchemy import Date, DateTime

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


def guardar_datos():
    """Exporta todas las tablas a datos/datos.json y copia los archivos subidos a datos/archivos/."""
    tablas = {}
    for tabla in db.metadata.sorted_tables:
        orden = list(tabla.primary_key.columns) or list(tabla.columns)
        filas = db.session.execute(tabla.select().order_by(*orden)).mappings()
        tablas[tabla.name] = [{k: _a_json(v) for k, v in fila.items()} for fila in filas]

    os.makedirs(_carpeta_archivos(), exist_ok=True)
    with open(_ruta_json(), "w", encoding="utf-8") as f:
        json.dump({"version": VERSION_FORMATO, "tablas": tablas}, f, ensure_ascii=False, indent=1)
        f.write("\n")

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

    return {nombre: len(filas) for nombre, filas in contenido["tablas"].items()}


def _git(*args):
    return subprocess.run(["git", *args], cwd=os.path.dirname(current_app.config["DATOS_DIR"]),
                          capture_output=True, text=True)


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
        _git("add", "datos")
        commit = _git("commit", "-m", "Actualiza datos de la aplicación")
        if commit.returncode != 0 and "nothing to commit" in commit.stdout + commit.stderr:
            click.echo("No hay cambios nuevos en los datos; no hay nada que subir.")
            return
        if commit.returncode != 0:
            raise click.ClickException("No se pudo hacer commit:\n" + commit.stdout + commit.stderr)
        push = _git("push")
        if push.returncode != 0:
            raise click.ClickException("El commit se hizo, pero falló el push:\n" + push.stderr)
        click.echo("Datos subidos a GitHub.")

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
