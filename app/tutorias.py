from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import db
from .models import Apunte, Materia, SolicitudTutoria, Usuario

bp = Blueprint("tutorias", __name__, url_prefix="/tutorias")

# Transiciones de estado permitidas: (estado_actual, accion) -> (nuevo_estado, quien_puede)
TRANSICIONES = {
    ("pendiente", "aceptar"): ("aceptada", "tutor"),
    ("pendiente", "rechazar"): ("rechazada", "tutor"),
    ("pendiente", "cancelar"): ("cancelada", "solicitante"),
    ("aceptada", "completar"): ("completada", "tutor"),
    ("aceptada", "cancelar"): ("cancelada", "solicitante"),
}


@bp.route("/")
@login_required
def mis_tutorias():
    recibidas = sorted(current_user.tutorias_recibidas, key=lambda s: s.fecha_creacion, reverse=True)
    solicitadas = sorted(current_user.tutorias_solicitadas, key=lambda s: s.fecha_creacion, reverse=True)
    return render_template("tutorias/lista.html", recibidas=recibidas, solicitadas=solicitadas)


@bp.route("/solicitar/<int:tutor_id>", methods=["GET", "POST"])
@login_required
def solicitar(tutor_id):
    tutor = db.get_or_404(Usuario, tutor_id)
    apunte = db.session.get(Apunte, request.args.get("apunte_id", type=int) or 0)
    if tutor.id == current_user.id:
        flash("No puedes solicitarte una tutoría a ti mismo.", "warning")
        return redirect(url_for("main.perfil", usuario_id=tutor.id))
    if not tutor.ofrece_tutorias:
        flash(f"{tutor.nombre} no está ofreciendo tutorías por ahora.", "warning")
        return redirect(url_for("main.perfil", usuario_id=tutor.id))

    materias_tutor = sorted({a.materia for a in tutor.apuntes}, key=lambda m: m.nombre)

    if request.method == "POST":
        tema = request.form.get("tema", "").strip()
        mensaje = request.form.get("mensaje", "").strip()
        fecha_txt = request.form.get("fecha_propuesta", "").strip()
        fecha = None
        if fecha_txt:
            try:
                fecha = datetime.strptime(fecha_txt, "%Y-%m-%dT%H:%M")
            except ValueError:
                fecha = None
        if not tema or not mensaje:
            flash("Tema y mensaje son obligatorios.", "danger")
        else:
            apunte_form = db.session.get(Apunte, request.form.get("apunte_id", type=int) or 0)
            materia = db.session.get(Materia, request.form.get("materia_id", type=int) or 0)
            solicitud = SolicitudTutoria(
                solicitante=current_user,
                tutor=tutor,
                tema=tema,
                mensaje=mensaje,
                modalidad="presencial" if request.form.get("modalidad") == "presencial" else "virtual",
                fecha_propuesta=fecha,
                apunte=apunte_form if apunte_form and apunte_form.autor_id == tutor.id else None,
                materia=materia or (apunte_form.materia if apunte_form else None),
            )
            db.session.add(solicitud)
            db.session.commit()
            flash(f"Solicitud enviada a {tutor.nombre}.", "success")
            return redirect(url_for("tutorias.mis_tutorias"))

    return render_template(
        "tutorias/solicitar.html", tutor=tutor, apunte=apunte, materias=materias_tutor
    )


@bp.route("/<int:solicitud_id>/<accion>", methods=["POST"])
@login_required
def cambiar_estado(solicitud_id, accion):
    solicitud = db.get_or_404(SolicitudTutoria, solicitud_id)
    transicion = TRANSICIONES.get((solicitud.estado, accion))
    if not transicion:
        abort(400)
    nuevo_estado, rol = transicion
    autorizado = solicitud.tutor_id if rol == "tutor" else solicitud.solicitante_id
    if autorizado != current_user.id:
        abort(403)

    solicitud.estado = nuevo_estado
    respuesta = request.form.get("respuesta", "").strip()
    if respuesta and rol == "tutor":
        solicitud.respuesta_tutor = respuesta
    db.session.commit()
    flash(f"Tutoría {nuevo_estado}.", "success")
    return redirect(url_for("tutorias.mis_tutorias"))
