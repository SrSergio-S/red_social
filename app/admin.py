"""Panel de administración (/admin) para ver y editar todas las tablas desde el navegador.

Solo pueden entrar los usuarios con `es_admin = True`.
"""
import os

from flask import abort, current_app, redirect, request, url_for
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.menu import MenuLink
from flask_admin.contrib.sqla import ModelView
from flask_admin.theme import Bootstrap4Theme
from flask_login import current_user
from flask_wtf import FlaskForm
from sqlalchemy import func
from wtforms import PasswordField
from wtforms.validators import Length, Optional, ValidationError

from . import db
from .models import (
    Apunte, Calificacion, Comentario, Descarga, Etiqueta, Materia, SolicitudTutoria, Usuario,
)


def _es_admin():
    return current_user.is_authenticated and current_user.es_admin


def _no_autorizado():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.url))
    abort(403)


def _borrar_archivos(apuntes):
    carpeta = current_app.config["UPLOAD_FOLDER"]
    for nombre in apuntes:
        ruta = os.path.join(carpeta, nombre)
        if os.path.exists(ruta):
            os.remove(ruta)


class FormularioAdmin(FlaskForm):
    """Formulario con el token CSRF de Flask-WTF (el mismo que usa toda la app).

    Guarda el registro que se edita en `_obj`, como hace el formulario base de Flask-Admin,
    para que la validación de campos únicos (correo, código...) no lo cuente como repetido.
    """

    def __init__(self, *args, **kwargs):
        self._obj = kwargs.get("obj")
        super().__init__(*args, **kwargs)


class InicioAdmin(AdminIndexView):
    @expose("/")
    def index(self):
        conteos = [
            ("Usuarios", Usuario.query.count(), "usuario.index_view"),
            ("Materias", Materia.query.count(), "materia.index_view"),
            ("Apuntes", Apunte.query.count(), "apunte.index_view"),
            ("Etiquetas", Etiqueta.query.count(), "etiqueta.index_view"),
            ("Calificaciones", Calificacion.query.count(), "calificacion.index_view"),
            ("Descargas", Descarga.query.count(), "descarga.index_view"),
            ("Comentarios", Comentario.query.count(), "comentario.index_view"),
            ("Tutorías", SolicitudTutoria.query.count(), "solicitudtutoria.index_view"),
        ]
        promedio = db.session.query(func.avg(Calificacion.estrellas)).scalar()
        return self.render("admin/inicio.html", conteos=conteos, promedio=promedio)

    def is_accessible(self):
        return _es_admin()

    def inaccessible_callback(self, name, **kwargs):
        return _no_autorizado()


class VistaSegura(ModelView):
    """Base de todas las vistas: acceso solo para administradores y protección CSRF."""

    form_base_class = FormularioAdmin
    page_size = 25
    can_view_details = True
    can_export = True
    export_types = ["csv"]

    def is_accessible(self):
        return _es_admin()

    def inaccessible_callback(self, name, **kwargs):
        return _no_autorizado()


class UsuarioAdmin(VistaSegura):
    column_list = ["id", "nombre", "email", "carrera", "semestre", "ofrece_tutorias", "es_admin", "fecha_registro"]
    column_searchable_list = ["nombre", "email", "carrera"]
    column_filters = ["carrera", "semestre", "ofrece_tutorias", "es_admin"]
    column_editable_list = ["ofrece_tutorias", "es_admin"]
    column_exclude_list = ["password_hash"]
    column_details_exclude_list = ["password_hash"]
    column_export_exclude_list = ["password_hash"]
    form_columns = [
        "nombre", "email", "nueva_contrasena", "carrera", "semestre", "bio",
        "ofrece_tutorias", "es_admin", "materias_seguidas",
    ]
    form_extra_fields = {
        "nueva_contrasena": PasswordField(
            "Nueva contraseña", validators=[Optional(), Length(min=6)],
            description="Déjala vacía para conservar la actual.",
        )
    }
    column_labels = {
        "email": "Correo", "es_admin": "Administrador", "ofrece_tutorias": "Ofrece tutorías",
        "fecha_registro": "Registro", "materias_seguidas": "Materias que sigue", "bio": "Sobre mí",
    }

    def on_model_change(self, form, model, is_created):
        model.email = model.email.strip().lower()
        if form.nueva_contrasena.data:
            model.set_password(form.nueva_contrasena.data)
        elif is_created:
            raise ValidationError("Escribe una contraseña para el nuevo usuario.")

    def on_model_delete(self, model):
        if model.id == current_user.id:
            raise ValidationError("No puedes eliminar tu propia cuenta de administrador.")
        self._archivos = [a.nombre_almacenado for a in model.apuntes]

    def after_model_delete(self, model):
        _borrar_archivos(getattr(self, "_archivos", []))


class MateriaAdmin(VistaSegura):
    column_list = ["id", "codigo", "nombre", "carrera", "semestre"]
    column_searchable_list = ["codigo", "nombre", "carrera"]
    column_filters = ["carrera", "semestre"]
    column_editable_list = ["nombre", "semestre"]
    form_columns = ["codigo", "nombre", "descripcion", "carrera", "semestre", "seguidores"]
    column_labels = {"codigo": "Código", "descripcion": "Descripción"}

    def on_model_delete(self, model):
        self._archivos = [a.nombre_almacenado for a in model.apuntes]

    def after_model_delete(self, model):
        _borrar_archivos(getattr(self, "_archivos", []))


class ApunteAdmin(VistaSegura):
    can_create = False  # los archivos se suben desde la app (Subir apunte)
    column_list = ["id", "titulo", "tipo", "materia", "autor", "nombre_original", "tamano_bytes", "fecha_subida"]
    column_searchable_list = ["titulo", "descripcion", "nombre_original"]
    column_filters = ["tipo", "extension", "materia.nombre", "autor.nombre", "fecha_subida"]
    column_editable_list = ["titulo"]
    column_default_sort = ("fecha_subida", True)
    form_columns = ["titulo", "descripcion", "tipo", "materia", "autor", "etiquetas", "fecha_subida"]
    column_labels = {
        "titulo": "Título", "descripcion": "Descripción", "nombre_original": "Archivo",
        "tamano_bytes": "Tamaño (bytes)", "fecha_subida": "Subido", "hash_sha256": "SHA-256",
        "nombre_almacenado": "Nombre en disco", "mimetype": "Tipo MIME", "extension": "Extensión",
    }

    def on_model_delete(self, model):
        self._archivos = [model.nombre_almacenado]

    def after_model_delete(self, model):
        _borrar_archivos(getattr(self, "_archivos", []))


class EtiquetaAdmin(VistaSegura):
    column_list = ["id", "nombre"]
    column_searchable_list = ["nombre"]
    column_editable_list = ["nombre"]
    form_columns = ["nombre", "apuntes"]


class CalificacionAdmin(VistaSegura):
    column_list = ["id", "apunte", "usuario", "estrellas", "fecha"]
    column_filters = ["estrellas", "apunte.titulo", "usuario.nombre"]
    column_editable_list = ["estrellas"]
    column_default_sort = ("fecha", True)
    form_columns = ["apunte", "usuario", "estrellas"]
    form_choices = {"estrellas": [(str(i), "★" * i) for i in range(1, 6)]}
    column_labels = {"usuario": "Estudiante"}


class DescargaAdmin(VistaSegura):
    can_create = False
    can_edit = False
    column_list = ["id", "apunte", "usuario", "fecha"]
    column_filters = ["apunte.titulo", "usuario.nombre", "fecha"]
    column_default_sort = ("fecha", True)
    column_labels = {"usuario": "Estudiante"}


class ComentarioAdmin(VistaSegura):
    column_list = ["id", "autor", "contenido", "apunte", "materia", "padre", "fecha"]
    column_searchable_list = ["contenido"]
    column_filters = ["autor.nombre", "fecha"]
    column_default_sort = ("fecha", True)
    form_columns = ["autor", "contenido", "apunte", "materia", "padre"]
    column_labels = {"padre": "Responde a"}
    column_descriptions = {
        "apunte": "Llena SOLO uno: apunte (foro del apunte) o materia (foro de la materia).",
        "materia": "Llena SOLO uno: apunte (foro del apunte) o materia (foro de la materia).",
    }

    def on_model_change(self, form, model, is_created):
        if bool(model.apunte) == bool(model.materia):
            raise ValidationError("El comentario debe pertenecer a un apunte o a una materia (solo uno).")


class TutoriaAdmin(VistaSegura):
    column_list = ["id", "tema", "solicitante", "tutor", "materia", "estado", "modalidad", "fecha_propuesta"]
    column_searchable_list = ["tema", "mensaje"]
    column_filters = ["estado", "modalidad", "tutor.nombre", "solicitante.nombre"]
    column_editable_list = ["estado"]
    column_default_sort = ("fecha_creacion", True)
    form_columns = [
        "solicitante", "tutor", "materia", "apunte", "tema", "mensaje", "modalidad",
        "fecha_propuesta", "estado", "respuesta_tutor",
    ]
    form_choices = {
        "estado": [(e, e.capitalize()) for e in SolicitudTutoria.ESTADOS],
        "modalidad": [("virtual", "Virtual"), ("presencial", "Presencial")],
    }
    column_labels = {"fecha_propuesta": "Fecha propuesta", "respuesta_tutor": "Respuesta del tutor"}


def iniciar_admin(app):
    admin = Admin(
        app, name="ApuntesU · Admin", index_view=InicioAdmin(name="Resumen", url="/admin"),
        theme=Bootstrap4Theme(swatch="default"),
    )
    admin.add_view(UsuarioAdmin(Usuario, db, name="Usuarios"))
    admin.add_view(MateriaAdmin(Materia, db, name="Materias"))
    admin.add_view(ApunteAdmin(Apunte, db, name="Apuntes"))
    admin.add_view(EtiquetaAdmin(Etiqueta, db, name="Etiquetas"))
    admin.add_view(CalificacionAdmin(Calificacion, db, name="Calificaciones", category="Interacción"))
    admin.add_view(DescargaAdmin(Descarga, db, name="Descargas", category="Interacción"))
    admin.add_view(ComentarioAdmin(Comentario, db, name="Comentarios", category="Interacción"))
    admin.add_view(TutoriaAdmin(SolicitudTutoria, db, name="Tutorías"))
    admin.add_link(MenuLink(name="← Volver a la app", url="/"))
    return admin
