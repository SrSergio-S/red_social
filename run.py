"""Punto de entrada que usa Gunicorn dentro del contenedor (ver Dockerfile).

La app se inicia con:  docker compose up --build -d
"""
from app import create_app

app = create_app()
