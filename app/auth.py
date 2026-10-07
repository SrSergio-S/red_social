from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import db
from .models import Usuario

bp = Blueprint("auth", __name__)


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("main.inicio"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        carrera = request.form.get("carrera", "").strip()
        semestre = request.form.get("semestre", type=int)

        errores = []
        if not nombre:
            errores.append("El nombre es obligatorio.")
        if "@" not in email:
            errores.append("Ingresa un correo válido.")
        if len(password) < 6:
            errores.append("La contraseña debe tener al menos 6 caracteres.")
        if Usuario.query.filter_by(email=email).first():
            errores.append("Ese correo ya está registrado.")

        if errores:
            for e in errores:
                flash(e, "danger")
            return render_template("auth/registro.html", form=request.form)

        usuario = Usuario(nombre=nombre, email=email, carrera=carrera or None, semestre=semestre)
        usuario.set_password(password)
        db.session.add(usuario)
        db.session.commit()
        login_user(usuario)
        flash(f"¡Bienvenido/a, {usuario.nombre}! Sigue algunas materias para empezar.", "success")
        return redirect(url_for("main.materias"))

    return render_template("auth/registro.html", form={})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.inicio"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and usuario.check_password(password):
            login_user(usuario, remember=bool(request.form.get("recordar")))
            siguiente = request.args.get("next")
            if not siguiente or not siguiente.startswith("/") or siguiente.startswith("//"):
                siguiente = url_for("main.inicio")
            return redirect(siguiente)
        flash("Correo o contraseña incorrectos.", "danger")

    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))
