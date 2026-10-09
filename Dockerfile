# Imagen de ApuntesU (Flask + SQLite) lista para producción con Gunicorn.
#
#   docker build -t apuntesu .
#   docker run -p 5000:5000 -v apuntesu_datos:/app/instance apuntesu
#
# o simplemente:  docker compose up --build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Dependencias primero: así Docker reutiliza esta capa si solo cambia el código
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn

# 2) Código de la app y datos guardados (datos/ se carga la primera vez que arranca)
COPY . .

# 3) Usuario sin privilegios (uid 1000, el mismo del usuario normal en Linux y Codespaces)
RUN useradd --uid 1000 --create-home apuntesu \
    && mkdir -p /app/instance \
    && chown -R apuntesu:apuntesu /app
USER apuntesu

# La base de datos y los archivos subidos viven en /app/instance: monta ahí un volumen para no perderlos
VOLUME ["/app/instance"]
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=4)"

# Un proceso con varios hilos: SQLite trabaja mejor con un solo proceso escritor y así la
# carga inicial de datos ocurre una sola vez.
CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "120", "--access-logfile", "-"]
