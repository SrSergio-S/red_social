import hashlib
import os
import uuid

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request,
    send_from_directory, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from . import db
from .models import (
    Apunte, Calificacion, Comentario, Descarga, Etiqueta, Materia, Usuario, likes,
    seguimientos,
)

bp = Blueprint("main", __name__)

TIPOS_APUNTE = ["Apuntes", "Resumen", "Examen resuelto", "Ejercicios", "Presentación", "Guía", "Otro"]


def extension_de(nombre):
    return nombre.rsplit(".", 1)[1].lower() if "." in nombre else ""


def obtener_etiquetas(texto):
    nombres = {t.strip().lower().lstrip("#") for t in texto.split(",") if t.strip()}
    etiquetas = []
    for nombre in sorted(nombres):
        etiqueta = Etiqueta.query.filter_by(nombre=nombre[:40]).first()
        if not etiqueta:
            etiqueta = Etiqueta(nombre=nombre[:40])
            db.session.add(etiqueta)
        etiquetas.append(etiqueta)
    return etiquetas


# --------------------------------------------------------------------------
# Inicio y exploración
# --------------------------------------------------------------------------
@bp.route("/")
def inicio():
    if not current_user.is_authenticated:
        stats = {
            "usuarios": Usuario.query.count(),
            "materias": Materia.query.count(),
            "apuntes": Apunte.query.count(),
            "descargas": Descarga.query.count(),
        }
        return render_template("bienvenida.html", stats=stats)

    ids_materias = [m.id for m in current_user.materias_seguidas]
    feed = []
    if ids_materias:
        feed = (
            Apunte.query.filter(Apunte.materia_id.in_(ids_materias))
            .order_by(Apunte.fecha_subida.desc())
            .limit(20)
            .all()
        )
    mejor_valorados = (
        db.session.query(Apunte, func.avg(Calificacion.estrellas).label("prom"), func.count(Calificacion.id))
        .join(Calificacion)
        .group_by(Apunte.id)
        .having(func.count(Calificacion.id) >= 1)
        .order_by(func.avg(Calificacion.estrellas).desc(), func.count(Calificacion.id).desc())
        .limit(5)
        .all()
    )
    pendientes = sum(1 for s in current_user.tutorias_recibidas if s.estado == "pendiente")
    return render_template(
        "inicio.html", feed=feed, mejor_valorados=mejor_valorados, pendientes=pendientes
    )


@bp.route("/materias")
def materias():
    q = request.args.get("q", "").strip()
    consulta = (
        db.session.query(Materia, func.count(func.distinct(seguimientos.c.usuario_id)).label("n_seg"))
        .outerjoin(seguimientos, seguimientos.c.materia_id == Materia.id)
        .group_by(Materia.id)
        .order_by(Materia.semestre, Materia.nombre)
    )
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(
            or_(Materia.nombre.ilike(patron), Materia.codigo.ilike(patron), Materia.carrera.ilike(patron))
        )
    return render_template("materias/lista.html", materias=consulta.all(), q=q)


@bp.route("/materias/nueva", methods=["GET", "POST"])
@login_required
def nueva_materia():
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip().upper()
        nombre = request.form.get("nombre", "").strip()
        if not codigo or not nombre:
            flash("Código y nombre son obligatorios.", "danger")
        elif Materia.query.filter_by(codigo=codigo).first():
            flash("Ya existe una materia con ese código.", "danger")
        else:
            materia = Materia(
                codigo=codigo,
                nombre=nombre,
                descripcion=request.form.get("descripcion", "").strip() or None,
                carrera=request.form.get("carrera", "").strip() or None,
                semestre=request.form.get("semestre", type=int),
            )
            materia.seguidores.append(current_user)
            db.session.add(materia)
            db.session.commit()
            flash("Materia creada. ¡Ya la sigues!", "success")
            return redirect(url_for("main.ver_materia", materia_id=materia.id))
    return render_template("materias/nueva.html")


@bp.route("/materias/<int:materia_id>")
def ver_materia(materia_id):
    materia = db.get_or_404(Materia, materia_id)
    orden = request.args.get("orden", "recientes")
    consulta = Apunte.query.filter_by(materia_id=materia.id)
    if orden == "valorados":
        consulta = (
            consulta.outerjoin(Calificacion)
            .group_by(Apunte.id)
            .order_by(func.coalesce(func.avg(Calificacion.estrellas), 0).desc())
        )
    elif orden == "descargados":
        consulta = (
            consulta.outerjoin(Descarga)
            .group_by(Apunte.id)
            .order_by(func.count(Descarga.id).desc())
        )
    else:
        consulta = consulta.order_by(Apunte.fecha_subida.desc())
    foro = [c for c in materia.comentarios if c.padre_id is None]
    return render_template(
        "materias/detalle.html", materia=materia, apuntes=consulta.all(), foro=foro, orden=orden
    )


@bp.route("/materias/<int:materia_id>/seguir", methods=["POST"])
@login_required
def seguir_materia(materia_id):
    materia = db.get_or_404(Materia, materia_id)
    if current_user.sigue(materia):
        current_user.materias_seguidas.remove(materia)
        flash(f"Dejaste de seguir {materia.nombre}.", "info")
    else:
        current_user.materias_seguidas.append(materia)
        flash(f"Ahora sigues {materia.nombre}.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("main.ver_materia", materia_id=materia.id))


# --------------------------------------------------------------------------
# Apuntes (archivos)
# --------------------------------------------------------------------------
@bp.route("/apuntes")
def buscar_apuntes():
    q = request.args.get("q", "").strip()
    etiqueta = request.args.get("etiqueta", "").strip()
    tipo = request.args.get("tipo", "").strip()
    consulta = Apunte.query.join(Materia)
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(
            or_(Apunte.titulo.ilike(patron), Apunte.descripcion.ilike(patron), Materia.nombre.ilike(patron))
        )
    if etiqueta:
        consulta = consulta.filter(Apunte.etiquetas.any(Etiqueta.nombre == etiqueta.lower()))
    if tipo:
        consulta = consulta.filter(Apunte.tipo == tipo)
    resultados = consulta.order_by(Apunte.fecha_subida.desc()).all()
    etiquetas_populares = (
        db.session.query(Etiqueta, func.count(Apunte.id))
        .join(Etiqueta.apuntes)
        .group_by(Etiqueta.id)
        .order_by(func.count(Apunte.id).desc())
        .limit(15)
        .all()
    )
    return render_template(
        "apuntes/buscar.html", apuntes=resultados, q=q, etiqueta=etiqueta, tipo=tipo,
        tipos=TIPOS_APUNTE, etiquetas_populares=etiquetas_populares,
    )


@bp.route("/apuntes/subir", methods=["GET", "POST"])
@login_required
def subir_apunte():
    materias_disponibles = Materia.query.order_by(Materia.nombre).all()
    if request.method == "POST":
        archivo = request.files.get("archivo")
        titulo = request.form.get("titulo", "").strip()
        materia = db.session.get(Materia, request.form.get("materia_id", type=int) or 0)
        permitidas = current_app.config["EXTENSIONES_PERMITIDAS"]

        error = None
        if not titulo:
            error = "El título es obligatorio."
        elif not materia:
            error = "Selecciona una materia."
        elif not archivo or not archivo.filename:
            error = "Selecciona un archivo."
        elif extension_de(archivo.filename) not in permitidas:
            error = "Tipo de archivo no permitido. Permitidos: " + ", ".join(sorted(permitidas))
        if error:
            flash(error, "danger")
            return render_template(
                "apuntes/subir.html", materias=materias_disponibles, tipos=TIPOS_APUNTE, form=request.form
            )

        contenido = archivo.read()
        hash_sha256 = hashlib.sha256(contenido).hexdigest()
        duplicado = Apunte.query.filter_by(hash_sha256=hash_sha256).first()
        etiquetas = obtener_etiquetas(request.form.get("etiquetas", ""))
        nombre_original = secure_filename(archivo.filename) or f"archivo.{extension_de(archivo.filename)}"
        ext = extension_de(nombre_original)
        nombre_almacenado = f"{uuid.uuid4().hex}.{ext}"
        with open(os.path.join(current_app.config["UPLOAD_FOLDER"], nombre_almacenado), "wb") as f:
            f.write(contenido)

        apunte = Apunte(
            titulo=titulo,
            descripcion=request.form.get("descripcion", "").strip() or None,
            tipo=request.form.get("tipo") if request.form.get("tipo") in TIPOS_APUNTE else "Apuntes",
            nombre_original=nombre_original,
            nombre_almacenado=nombre_almacenado,
            extension=ext,
            mimetype=archivo.mimetype,
            tamano_bytes=len(contenido),
            hash_sha256=hash_sha256,
            autor=current_user,
            materia=materia,
            etiquetas=etiquetas,
        )
        db.session.add(apunte)
        if not current_user.sigue(materia):
            current_user.materias_seguidas.append(materia)
        db.session.commit()
        if duplicado:
            flash(f"Aviso: este archivo es idéntico a «{duplicado.titulo}» ya publicado.", "warning")
        flash("¡Apunte publicado!", "success")
        return redirect(url_for("main.ver_apunte", apunte_id=apunte.id))

    preseleccion = request.args.get("materia_id", type=int)
    return render_template(
        "apuntes/subir.html", materias=materias_disponibles, tipos=TIPOS_APUNTE,
        form={"materia_id": preseleccion},
    )


@bp.route("/apuntes/<int:apunte_id>")
def ver_apunte(apunte_id):
    apunte = db.get_or_404(Apunte, apunte_id)
    mi_calificacion = apunte.calificacion_de(current_user) if current_user.is_authenticated else None
    distribucion = {i: 0 for i in range(5, 0, -1)}
    for c in apunte.calificaciones:
        distribucion[c.estrellas] += 1
    hilos = [c for c in apunte.comentarios if c.padre_id is None]
    return render_template(
        "apuntes/detalle.html", apunte=apunte, mi_calificacion=mi_calificacion,
        distribucion=distribucion, hilos=hilos,
    )


@bp.route("/apuntes/<int:apunte_id>/descargar")
@login_required
def descargar_apunte(apunte_id):
    apunte = db.get_or_404(Apunte, apunte_id)
    db.session.add(Descarga(usuario=current_user, apunte=apunte))
    db.session.commit()
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"], apunte.nombre_almacenado,
        as_attachment=True, download_name=apunte.nombre_original,
    )


@bp.route("/apuntes/<int:apunte_id>/calificar", methods=["POST"])
@login_required
def calificar_apunte(apunte_id):
    apunte = db.get_or_404(Apunte, apunte_id)
    estrellas = request.form.get("estrellas", type=int)
    if apunte.autor_id == current_user.id:
        flash("No puedes calificar tu propio apunte.", "warning")
    elif estrellas not in range(1, 6):
        flash("La calificación debe ser de 1 a 5 estrellas.", "danger")
    else:
        calificacion = apunte.calificacion_de(current_user)
        if calificacion:
            calificacion.estrellas = estrellas
        else:
            db.session.add(Calificacion(usuario=current_user, apunte=apunte, estrellas=estrellas))
        db.session.commit()
        flash(f"Calificaste con {estrellas} ★", "success")
    return redirect(url_for("main.ver_apunte", apunte_id=apunte.id))


@bp.route("/apuntes/<int:apunte_id>/like", methods=["POST"])
@login_required
def like_apunte(apunte_id):
    apunte = db.get_or_404(Apunte, apunte_id)
    if current_user.le_gusta(apunte):
        current_user.apuntes_gustados.remove(apunte)
    else:
        current_user.apuntes_gustados.append(apunte)
    db.session.commit()
    return redirect(request.referrer or url_for("main.ver_apunte", apunte_id=apunte.id))


@bp.route("/apuntes/<int:apunte_id>/eliminar", methods=["POST"])
@login_required
def eliminar_apunte(apunte_id):
    apunte = db.get_or_404(Apunte, apunte_id)
    if apunte.autor_id != current_user.id:
        abort(403)
    ruta = os.path.join(current_app.config["UPLOAD_FOLDER"], apunte.nombre_almacenado)
    materia_id = apunte.materia_id
    db.session.delete(apunte)
    db.session.commit()
    if os.path.exists(ruta):
        os.remove(ruta)
    flash("Apunte eliminado.", "info")
    return redirect(url_for("main.ver_materia", materia_id=materia_id))


# --------------------------------------------------------------------------
# Foro de comentarios (por apunte o por materia)
# --------------------------------------------------------------------------
@bp.route("/comentar", methods=["POST"])
@login_required
def comentar():
    contenido = request.form.get("contenido", "").strip()
    apunte_id = request.form.get("apunte_id", type=int)
    materia_id = request.form.get("materia_id", type=int)
    padre_id = request.form.get("padre_id", type=int)

    if apunte_id:
        destino = db.get_or_404(Apunte, apunte_id)
        volver = url_for("main.ver_apunte", apunte_id=apunte_id)
    elif materia_id:
        destino = db.get_or_404(Materia, materia_id)
        volver = url_for("main.ver_materia", materia_id=materia_id) + "#foro"
    else:
        abort(400)

    if not contenido:
        flash("El comentario no puede estar vacío.", "warning")
        return redirect(volver)

    padre = None
    if padre_id:
        padre = db.get_or_404(Comentario, padre_id)
        if padre.apunte_id != apunte_id or padre.materia_id != materia_id:
            abort(400)

    comentario = Comentario(contenido=contenido[:2000], autor=current_user, padre=padre)
    if isinstance(destino, Apunte):
        comentario.apunte = destino
    else:
        comentario.materia = destino
    db.session.add(comentario)
    db.session.commit()
    return redirect(volver)


@bp.route("/comentarios/<int:comentario_id>/eliminar", methods=["POST"])
@login_required
def eliminar_comentario(comentario_id):
    comentario = db.get_or_404(Comentario, comentario_id)
    if comentario.autor_id != current_user.id:
        abort(403)
    if comentario.apunte_id:
        volver = url_for("main.ver_apunte", apunte_id=comentario.apunte_id)
    else:
        volver = url_for("main.ver_materia", materia_id=comentario.materia_id) + "#foro"
    db.session.delete(comentario)
    db.session.commit()
    flash("Comentario eliminado.", "info")
    return redirect(volver)


# --------------------------------------------------------------------------
# Perfiles y ranking
# --------------------------------------------------------------------------
@bp.route("/usuarios/<int:usuario_id>")
def perfil(usuario_id):
    usuario = db.get_or_404(Usuario, usuario_id)
    total_descargas = (
        db.session.query(func.count(Descarga.id)).join(Apunte).filter(Apunte.autor_id == usuario.id).scalar()
    )
    total_likes = (
        db.session.query(func.count()).select_from(likes)
        .join(Apunte, Apunte.id == likes.c.apunte_id)
        .filter(Apunte.autor_id == usuario.id).scalar()
    )
    return render_template(
        "usuarios/perfil.html", usuario=usuario, total_descargas=total_descargas, total_likes=total_likes
    )


@bp.route("/perfil/editar", methods=["GET", "POST"])
@login_required
def editar_perfil():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if not nombre:
            flash("El nombre es obligatorio.", "danger")
        else:
            current_user.nombre = nombre
            current_user.carrera = request.form.get("carrera", "").strip() or None
            current_user.semestre = request.form.get("semestre", type=int)
            current_user.bio = request.form.get("bio", "").strip() or None
            current_user.ofrece_tutorias = bool(request.form.get("ofrece_tutorias"))
            db.session.commit()
            flash("Perfil actualizado.", "success")
            return redirect(url_for("main.perfil", usuario_id=current_user.id))
    return render_template("usuarios/editar.html")


@bp.route("/ranking")
def ranking():
    top = (
        db.session.query(
            Usuario,
            func.count(func.distinct(Apunte.id)).label("n_apuntes"),
            func.avg(Calificacion.estrellas).label("prom"),
            func.count(func.distinct(Calificacion.id)).label("n_calif"),
        )
        .join(Apunte, Apunte.autor_id == Usuario.id)
        .outerjoin(Calificacion, Calificacion.apunte_id == Apunte.id)
        .group_by(Usuario.id)
        .order_by(func.coalesce(func.avg(Calificacion.estrellas), 0).desc(), func.count(func.distinct(Apunte.id)).desc())
        .limit(20)
        .all()
    )
    return render_template("usuarios/ranking.html", top=top)
