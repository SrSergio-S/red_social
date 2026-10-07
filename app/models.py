"""Modelo de datos de la Red Social Universitaria.

Relaciones principales:
  * Usuario  <-> Materia      (muchos a muchos, tabla `seguimientos`)
  * Usuario  <-> Apunte       (muchos a muchos con datos extra: `Calificacion`, `Descarga`)
  * Usuario  <-> Apunte       (muchos a muchos simple: tabla `likes`)
  * Apunte   <-> Etiqueta     (muchos a muchos, tabla `apunte_etiquetas`)
  * Materia   -> Apunte       (uno a muchos)
  * Comentario pertenece a un Apunte O a una Materia (foro) y puede responder a otro Comentario
  * SolicitudTutoria relaciona a un estudiante solicitante con un tutor (creador del apunte)
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint, func
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


def ahora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Tablas de asociación (muchos a muchos "puras")
# --------------------------------------------------------------------------
seguimientos = db.Table(
    "seguimientos",
    db.Column("usuario_id", db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    db.Column("materia_id", db.Integer, db.ForeignKey("materias.id", ondelete="CASCADE"), primary_key=True),
    db.Column("fecha", db.DateTime, default=ahora, nullable=False),
)

likes = db.Table(
    "likes",
    db.Column("usuario_id", db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    db.Column("apunte_id", db.Integer, db.ForeignKey("apuntes.id", ondelete="CASCADE"), primary_key=True),
    db.Column("fecha", db.DateTime, default=ahora, nullable=False),
)

apunte_etiquetas = db.Table(
    "apunte_etiquetas",
    db.Column("apunte_id", db.Integer, db.ForeignKey("apuntes.id", ondelete="CASCADE"), primary_key=True),
    db.Column("etiqueta_id", db.Integer, db.ForeignKey("etiquetas.id", ondelete="CASCADE"), primary_key=True),
)


# --------------------------------------------------------------------------
# Entidades
# --------------------------------------------------------------------------
class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    carrera = db.Column(db.String(120))
    semestre = db.Column(db.Integer)
    bio = db.Column(db.Text)
    ofrece_tutorias = db.Column(db.Boolean, default=True, nullable=False)
    es_admin = db.Column(db.Boolean, default=False, nullable=False, server_default="0")
    fecha_registro = db.Column(db.DateTime, default=ahora, nullable=False)

    materias_seguidas = db.relationship(
        "Materia", secondary=seguimientos, back_populates="seguidores", lazy="select"
    )
    apuntes = db.relationship("Apunte", back_populates="autor", cascade="all, delete-orphan")
    apuntes_gustados = db.relationship("Apunte", secondary=likes, back_populates="usuarios_like")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def sigue(self, materia):
        return materia in self.materias_seguidas

    def le_gusta(self, apunte):
        return apunte in self.apuntes_gustados

    @property
    def reputacion(self):
        """Promedio de estrellas recibidas en todos sus apuntes."""
        promedio = (
            db.session.query(func.avg(Calificacion.estrellas))
            .join(Apunte)
            .filter(Apunte.autor_id == self.id)
            .scalar()
        )
        return round(promedio, 1) if promedio else None

    def __str__(self):
        return f"{self.nombre} <{self.email}>"


class Materia(db.Model):
    __tablename__ = "materias"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.Text)
    carrera = db.Column(db.String(120))
    semestre = db.Column(db.Integer)

    seguidores = db.relationship("Usuario", secondary=seguimientos, back_populates="materias_seguidas")
    apuntes = db.relationship("Apunte", back_populates="materia", cascade="all, delete-orphan")
    comentarios = db.relationship(
        "Comentario", back_populates="materia", cascade="all, delete-orphan",
        order_by="Comentario.fecha.desc()",
    )

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class Etiqueta(db.Model):
    __tablename__ = "etiquetas"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(40), unique=True, nullable=False)

    apuntes = db.relationship("Apunte", secondary=apunte_etiquetas, back_populates="etiquetas")

    def __str__(self):
        return self.nombre


class Apunte(db.Model):
    """Material de estudio. Guarda los metadatos del archivo subido."""

    __tablename__ = "apuntes"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    tipo = db.Column(db.String(30), default="Apuntes", nullable=False)  # Apuntes, Resumen, Examen...
    fecha_subida = db.Column(db.DateTime, default=ahora, nullable=False, index=True)

    # --- Metadatos del archivo ---
    nombre_original = db.Column(db.String(255), nullable=False)
    nombre_almacenado = db.Column(db.String(255), unique=True, nullable=False)
    extension = db.Column(db.String(10), nullable=False)
    mimetype = db.Column(db.String(120))
    tamano_bytes = db.Column(db.Integer, nullable=False)
    hash_sha256 = db.Column(db.String(64), nullable=False, index=True)

    autor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    materia_id = db.Column(db.Integer, db.ForeignKey("materias.id", ondelete="CASCADE"), nullable=False)

    autor = db.relationship("Usuario", back_populates="apuntes")
    materia = db.relationship("Materia", back_populates="apuntes")
    etiquetas = db.relationship("Etiqueta", secondary=apunte_etiquetas, back_populates="apuntes")
    usuarios_like = db.relationship("Usuario", secondary=likes, back_populates="apuntes_gustados")
    calificaciones = db.relationship("Calificacion", back_populates="apunte", cascade="all, delete-orphan")
    descargas = db.relationship("Descarga", back_populates="apunte", cascade="all, delete-orphan")
    comentarios = db.relationship(
        "Comentario", back_populates="apunte", cascade="all, delete-orphan",
        order_by="Comentario.fecha.asc()",
    )

    @property
    def promedio_estrellas(self):
        if not self.calificaciones:
            return None
        return round(sum(c.estrellas for c in self.calificaciones) / len(self.calificaciones), 1)

    @property
    def total_descargas(self):
        return len(self.descargas)

    @property
    def tamano_legible(self):
        tamano = float(self.tamano_bytes)
        for unidad in ("B", "KB", "MB", "GB"):
            if tamano < 1024:
                return f"{tamano:.0f} {unidad}" if unidad == "B" else f"{tamano:.1f} {unidad}"
            tamano /= 1024
        return f"{tamano:.1f} TB"

    def __str__(self):
        return self.titulo

    def calificacion_de(self, usuario):
        return next((c for c in self.calificaciones if c.usuario_id == usuario.id), None)


class Calificacion(db.Model):
    """Asociación Usuario-Apunte con estrellas (1 a 5). Una por usuario y apunte."""

    __tablename__ = "calificaciones"
    __table_args__ = (
        UniqueConstraint("usuario_id", "apunte_id", name="uq_calificacion_usuario_apunte"),
        CheckConstraint("estrellas BETWEEN 1 AND 5", name="ck_estrellas_rango"),
    )

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    apunte_id = db.Column(db.Integer, db.ForeignKey("apuntes.id", ondelete="CASCADE"), nullable=False)
    estrellas = db.Column(db.Integer, nullable=False)
    fecha = db.Column(db.DateTime, default=ahora, onupdate=ahora, nullable=False)

    usuario = db.relationship("Usuario")
    apunte = db.relationship("Apunte", back_populates="calificaciones")


class Descarga(db.Model):
    """Historial de descargas (asociación Usuario-Apunte con fecha)."""

    __tablename__ = "descargas"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    apunte_id = db.Column(db.Integer, db.ForeignKey("apuntes.id", ondelete="CASCADE"), nullable=False)
    fecha = db.Column(db.DateTime, default=ahora, nullable=False)

    usuario = db.relationship("Usuario")
    apunte = db.relationship("Apunte", back_populates="descargas")


class Comentario(db.Model):
    """Foro: un comentario pertenece a un apunte o a una materia (exactamente uno)."""

    __tablename__ = "comentarios"
    __table_args__ = (
        CheckConstraint(
            "(apunte_id IS NOT NULL AND materia_id IS NULL) OR "
            "(apunte_id IS NULL AND materia_id IS NOT NULL)",
            name="ck_comentario_destino",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    contenido = db.Column(db.Text, nullable=False)
    fecha = db.Column(db.DateTime, default=ahora, nullable=False)
    autor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    apunte_id = db.Column(db.Integer, db.ForeignKey("apuntes.id", ondelete="CASCADE"))
    materia_id = db.Column(db.Integer, db.ForeignKey("materias.id", ondelete="CASCADE"))
    padre_id = db.Column(db.Integer, db.ForeignKey("comentarios.id", ondelete="CASCADE"))

    autor = db.relationship("Usuario")
    apunte = db.relationship("Apunte", back_populates="comentarios")
    materia = db.relationship("Materia", back_populates="comentarios")
    respuestas = db.relationship(
        "Comentario", backref=db.backref("padre", remote_side=[id]),
        cascade="all, delete-orphan", order_by="Comentario.fecha.asc()",
    )

    def __str__(self):
        return f"{self.autor.nombre if self.autor else '?'}: {self.contenido[:40]}"


class SolicitudTutoria(db.Model):
    __tablename__ = "solicitudes_tutoria"

    ESTADOS = ("pendiente", "aceptada", "rechazada", "completada", "cancelada")

    id = db.Column(db.Integer, primary_key=True)
    solicitante_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    tutor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    materia_id = db.Column(db.Integer, db.ForeignKey("materias.id", ondelete="SET NULL"))
    apunte_id = db.Column(db.Integer, db.ForeignKey("apuntes.id", ondelete="SET NULL"))
    tema = db.Column(db.String(150), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    modalidad = db.Column(db.String(20), default="virtual", nullable=False)  # virtual / presencial
    fecha_propuesta = db.Column(db.DateTime)
    estado = db.Column(db.String(20), default="pendiente", nullable=False, index=True)
    respuesta_tutor = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=ahora, nullable=False)
    fecha_actualizacion = db.Column(db.DateTime, default=ahora, onupdate=ahora, nullable=False)

    # passive_deletes: al borrar un usuario, la BD elimina sus solicitudes (ON DELETE CASCADE)
    solicitante = db.relationship(
        "Usuario", foreign_keys=[solicitante_id],
        backref=db.backref("tutorias_solicitadas", passive_deletes=True),
    )
    tutor = db.relationship(
        "Usuario", foreign_keys=[tutor_id],
        backref=db.backref("tutorias_recibidas", passive_deletes=True),
    )
    materia = db.relationship("Materia")
    apunte = db.relationship("Apunte")
