import os

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(INSTANCE_DIR, "red_social.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(INSTANCE_DIR, "uploads"))
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB por archivo
    # Carpeta (dentro del proyecto, se sube a GitHub) donde se guardan los datos con `guardar-datos`
    DATOS_DIR = os.environ.get("DATOS_DIR", os.path.join(BASE_DIR, "datos"))
    # Si la base de datos está vacía al arrancar, se cargan los datos de datos/ o, si no hay, los de ejemplo
    AUTO_SEED = os.environ.get("AUTO_SEED", "1") != "0"
    EXTENSIONES_PERMITIDAS = {
        "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
        "txt", "md", "png", "jpg", "jpeg", "zip",
    }


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    AUTO_SEED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    DATOS_DIR = os.path.join(INSTANCE_DIR, "no-existe-en-pruebas")  # las pruebas no leen datos/ real
