"""Comandos de consola: `flask --app run reset-db` y `flask --app run seed`."""
import hashlib
import os
import random
import re
import unicodedata
import uuid
from datetime import timedelta

import click
from flask import current_app

from . import db
from .models import (
    Apunte, Calificacion, Comentario, Descarga, Etiqueta, Materia, SolicitudTutoria, Usuario,
    ahora,
)

USUARIOS = [
    ("Ana Torres", "ana@uni.edu", "Ingeniería de Sistemas", 6, "Me encantan las bases de datos y explicar SQL."),
    ("Luis Pérez", "luis@uni.edu", "Ingeniería de Sistemas", 4, "Monitor de Cálculo. Pregunta sin miedo."),
    ("María Gómez", "maria@uni.edu", "Ingeniería Industrial", 5, "Resúmenes con mapas mentales."),
    ("Carlos Ruiz", "carlos@uni.edu", "Ingeniería de Sistemas", 2, "Aprendiendo Python día a día."),
    ("Sofía Díaz", "sofia@uni.edu", "Matemáticas", 7, "Tutorías de álgebra y estadística."),
]

MATERIAS = [
    ("MAT101", "Cálculo Diferencial", "Límites, derivadas y aplicaciones.", "Ciencias Básicas", 1),
    ("MAT201", "Álgebra Lineal", "Matrices, espacios vectoriales y transformaciones.", "Ciencias Básicas", 2),
    ("SIS210", "Programación en Python", "Fundamentos de programación con Python.", "Ingeniería de Sistemas", 2),
    ("SIS305", "Bases de Datos", "Modelo relacional, SQL y normalización.", "Ingeniería de Sistemas", 4),
    ("EST220", "Estadística y Probabilidad", "Distribuciones, inferencia y regresión.", "Ciencias Básicas", 3),
    ("IND330", "Investigación de Operaciones", "Programación lineal y modelos de optimización.", "Ingeniería Industrial", 5),
]

APUNTES = [
    ("Resumen de límites y continuidad", "MAT101", 1, "Resumen", "limites,resumen,parcial1",
     "# Límites\n\nlim x->a f(x) = L\n\n## Propiedades\n- Suma\n- Producto\n- Cociente\n"),
    ("Tabla de derivadas", "MAT101", 1, "Guía", "derivadas,formulario",
     "d/dx x^n = n x^(n-1)\nd/dx sin x = cos x\nd/dx e^x = e^x\n"),
    ("Ejercicios resueltos de matrices", "MAT201", 4, "Ejercicios", "matrices,ejercicios",
     "1) Calcular det(A) para A = [[1,2],[3,4]] -> -2\n"),
    ("Apuntes de clase: espacios vectoriales", "MAT201", 4, "Apuntes", "vectores,teoria",
     "Un espacio vectorial es un conjunto V con dos operaciones...\n"),
    ("Guía de listas y diccionarios", "SIS210", 0, "Guía", "python,estructuras",
     "lista = [1, 2, 3]\ndic = {'a': 1}\nfor k, v in dic.items():\n    print(k, v)\n"),
    ("Parcial 1 resuelto (2025-2)", "SIS210", 3, "Examen resuelto", "python,parcial1",
     "Pregunta 1: invertir una cadena -> s[::-1]\n"),
    ("Normalización 1FN, 2FN, 3FN", "SIS305", 0, "Resumen", "sql,normalizacion,parcial2",
     "1FN: valores atómicos\n2FN: sin dependencias parciales\n3FN: sin dependencias transitivas\n"),
    ("Consultas SQL con JOIN", "SIS305", 0, "Ejercicios", "sql,join",
     "SELECT a.titulo, m.nombre FROM apuntes a JOIN materias m ON m.id = a.materia_id;\n"),
    ("Formulario de distribuciones", "EST220", 4, "Guía", "distribuciones,formulario",
     "Binomial: P(X=k) = C(n,k) p^k (1-p)^(n-k)\nNormal: Z = (X - mu) / sigma\n"),
    ("Método simplex paso a paso", "IND330", 2, "Apuntes", "simplex,optimizacion",
     "1. Forma estándar\n2. Tabla inicial\n3. Variable de entrada / salida\n4. Pivoteo\n"),
]

COMENTARIOS = [
    "¡Muy claro, gracias!",
    "¿Alguien tiene más ejercicios de este tema?",
    "Me salvó el parcial 🙌",
    "Hay un pequeño error en el ejercicio 3, revisa el signo.",
    "Excelente resumen, muy bien organizado.",
]


def _crear_archivo(nombre_base, contenido):
    datos = contenido.encode("utf-8")
    nombre_almacenado = f"{uuid.uuid4().hex}.md"
    with open(os.path.join(current_app.config["UPLOAD_FOLDER"], nombre_almacenado), "wb") as f:
        f.write(datos)
    return {
        "nombre_original": re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", nombre_base.lower()).encode("ascii", "ignore").decode()).strip("_")[:60] + ".md",
        "nombre_almacenado": nombre_almacenado,
        "extension": "md",
        "mimetype": "text/markdown",
        "tamano_bytes": len(datos),
        "hash_sha256": hashlib.sha256(datos).hexdigest(),
    }


def poblar_datos_demo():
    random.seed(42)
    usuarios = []
    for nombre, email, carrera, semestre, bio in USUARIOS:
        u = Usuario(nombre=nombre, email=email, carrera=carrera, semestre=semestre, bio=bio)
        u.set_password("demo123")
        usuarios.append(u)
    usuarios[0].es_admin = True  # ana@uni.edu puede entrar a /admin
    db.session.add_all(usuarios)

    materias = {}
    for codigo, nombre, desc, carrera, semestre in MATERIAS:
        materias[codigo] = Materia(codigo=codigo, nombre=nombre, descripcion=desc, carrera=carrera, semestre=semestre)
    db.session.add_all(materias.values())

    # Muchos a muchos: cada estudiante sigue varias materias
    for u in usuarios:
        u.materias_seguidas = random.sample(list(materias.values()), k=random.randint(3, 5))

    etiquetas = {}
    apuntes = []
    for i, (titulo, codigo, idx_autor, tipo, tags, contenido) in enumerate(APUNTES):
        apunte = Apunte(
            titulo=titulo, descripcion=f"Material de {materias[codigo].nombre}.", tipo=tipo,
            autor=usuarios[idx_autor], materia=materias[codigo],
            fecha_subida=ahora() - timedelta(days=len(APUNTES) - i),
            **_crear_archivo(titulo, contenido),
        )
        for t in tags.split(","):
            etiquetas.setdefault(t, Etiqueta(nombre=t))
            apunte.etiquetas.append(etiquetas[t])
        if materias[codigo] not in apunte.autor.materias_seguidas:
            apunte.autor.materias_seguidas.append(materias[codigo])
        apuntes.append(apunte)
    db.session.add_all(apuntes)

    for apunte in apuntes:
        otros = [u for u in usuarios if u is not apunte.autor]
        for u in random.sample(otros, k=random.randint(1, len(otros))):
            db.session.add(Calificacion(usuario=u, apunte=apunte, estrellas=random.choice([3, 4, 4, 5, 5])))
            db.session.add(Descarga(usuario=u, apunte=apunte))
            if random.random() < 0.6:
                u.apuntes_gustados.append(apunte)
        if random.random() < 0.7:
            c = Comentario(contenido=random.choice(COMENTARIOS), autor=random.choice(otros), apunte=apunte)
            db.session.add(c)
            db.session.add(Comentario(contenido="¡Gracias por comentar! 😊", autor=apunte.autor, apunte=apunte, padre=c))

    db.session.add_all([
        Comentario(contenido="¿Alguien arma grupo de estudio para el parcial del viernes?",
                   autor=usuarios[3], materia=materias["MAT101"]),
        Comentario(contenido="¿Qué temas entran en el segundo corte?", autor=usuarios[2], materia=materias["SIS305"]),
        Comentario(contenido="Normalización y SQL avanzado (subconsultas y vistas).",
                   autor=usuarios[0], materia=materias["SIS305"]),
    ])

    db.session.add_all([
        SolicitudTutoria(solicitante=usuarios[3], tutor=usuarios[0], materia=materias["SIS305"], apunte=apuntes[7],
                         tema="Dudas con LEFT JOIN", mensaje="¿Podrías explicarme la diferencia entre INNER y LEFT JOIN?",
                         modalidad="virtual", fecha_propuesta=ahora() + timedelta(days=2)),
        SolicitudTutoria(solicitante=usuarios[2], tutor=usuarios[4], materia=materias["EST220"],
                         tema="Prueba de hipótesis", mensaje="Necesito repasar para el examen final.",
                         modalidad="presencial", estado="aceptada",
                         respuesta_tutor="¡Claro! Nos vemos en la biblioteca.",
                         fecha_propuesta=ahora() + timedelta(days=4)),
        SolicitudTutoria(solicitante=usuarios[1], tutor=usuarios[0], materia=materias["SIS210"], apunte=apuntes[4],
                         tema="Comprensión de listas", mensaje="No entiendo bien las list comprehensions.",
                         estado="completada", respuesta_tutor="Listo, quedó resuelto."),
    ])
    db.session.commit()


def registrar_comandos(app):
    @app.cli.command("reset-db")
    def reset_db():
        """Borra y vuelve a crear todas las tablas (¡elimina los datos!)."""
        db.drop_all()
        db.create_all()
        click.echo("Base de datos reiniciada.")

    @app.cli.command("hacer-admin")
    @click.argument("email")
    def hacer_admin(email):
        """Da permisos de administrador (/admin) al usuario con ese correo."""
        usuario = Usuario.query.filter_by(email=email.strip().lower()).first()
        if not usuario:
            raise click.ClickException(f"No existe un usuario con el correo {email}.")
        usuario.es_admin = True
        db.session.commit()
        click.echo(f"{usuario.nombre} ahora es administrador. Entra en /admin")

    @app.cli.command("seed")
    def seed():
        """Reinicia la base de datos y la llena con datos de ejemplo."""
        db.drop_all()
        db.create_all()
        poblar_datos_demo()
        click.echo(
            f"Datos de ejemplo creados: {Usuario.query.count()} usuarios, {Materia.query.count()} materias, "
            f"{Apunte.query.count()} apuntes.\nEntra con ana@uni.edu / demo123 (es administradora: /admin)"
        )
