import os

from flask import Flask, render_template
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Inicia sesión para continuar."
login_manager.login_message_category = "warning"
csrf = CSRFProtect()


@event.listens_for(Engine, "connect")
def _activar_claves_foraneas_sqlite(dbapi_connection, connection_record):
    """SQLite no aplica ON DELETE CASCADE salvo que se active explícitamente."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from . import models  # noqa: F401  (registra los modelos)
    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .tutorias import bp as tutorias_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(tutorias_bp)

    from .seed import registrar_comandos
    registrar_comandos(app)

    @app.template_filter("fecha")
    def formato_fecha(valor, formato="%d/%m/%Y %H:%M"):
        return valor.strftime(formato) if valor else ""

    @app.errorhandler(403)
    def prohibido(e):
        return render_template("errores/error.html", codigo=403, mensaje="No tienes permiso para hacer esto."), 403

    @app.errorhandler(404)
    def no_encontrado(e):
        return render_template("errores/error.html", codigo=404, mensaje="La página no existe."), 404

    @app.errorhandler(413)
    def muy_grande(e):
        return render_template("errores/error.html", codigo=413, mensaje="El archivo supera el límite de 20 MB."), 413

    with app.app_context():
        db.create_all()
        if app.config["AUTO_SEED"] and not models.Usuario.query.first():
            from .seed import poblar_datos_demo
            poblar_datos_demo()
            app.logger.warning("Base de datos vacía: se cargaron los datos de ejemplo (ana@uni.edu / demo123).")

    return app


@login_manager.user_loader
def cargar_usuario(user_id):
    from .models import Usuario
    return db.session.get(Usuario, int(user_id))
