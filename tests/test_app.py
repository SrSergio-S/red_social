import io

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.config import TestConfig
from app.models import Apunte, Calificacion, Comentario, Descarga, Materia, SolicitudTutoria, Usuario
from app.seed import poblar_datos_demo


@pytest.fixture
def app(tmp_path):
    class Cfg(TestConfig):
        UPLOAD_FOLDER = str(tmp_path / "uploads")

    app = create_app(Cfg)
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def registrar(client, nombre="Ana", email="ana@test.edu", password="secreta1"):
    return client.post("/registro", data={"nombre": nombre, "email": email, "password": password},
                       follow_redirects=True)


def login(client, email, password="secreta1"):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def logout(client):
    client.post("/logout")


def crear_materia(codigo="SIS305", nombre="Bases de Datos"):
    m = Materia(codigo=codigo, nombre=nombre)
    db.session.add(m)
    db.session.commit()
    return m


def subir(client, materia_id, titulo="Resumen SQL", contenido=b"SELECT 1;", nombre="sql.txt", etiquetas="sql, parcial1"):
    return client.post(
        "/apuntes/subir",
        data={"titulo": titulo, "materia_id": materia_id, "tipo": "Resumen", "etiquetas": etiquetas,
              "archivo": (io.BytesIO(contenido), nombre)},
        content_type="multipart/form-data", follow_redirects=True,
    )


def test_registro_y_login(client):
    r = registrar(client)
    assert "Bienvenido/a, Ana".encode() in r.data
    logout(client)
    assert "incorrectos".encode() in login(client, "ana@test.edu", "mala").data
    assert b"Novedades de tus materias" in login(client, "ana@test.edu").data


def test_seguir_materia_muchos_a_muchos(client):
    m1, m2 = crear_materia("A1", "Cálculo"), crear_materia("A2", "Física")
    registrar(client)
    client.post(f"/materias/{m1.id}/seguir")
    client.post(f"/materias/{m2.id}/seguir")
    logout(client)
    registrar(client, "Luis", "luis@test.edu")
    client.post(f"/materias/{m1.id}/seguir")

    ana = Usuario.query.filter_by(email="ana@test.edu").one()
    assert {m.codigo for m in ana.materias_seguidas} == {"A1", "A2"}
    assert len(db.session.get(Materia, m1.id).seguidores) == 2

    client.post(f"/materias/{m1.id}/seguir")  # dejar de seguir
    assert len(db.session.get(Materia, m1.id).seguidores) == 1


def test_subir_apunte_guarda_metadatos_y_descarga(client, app):
    m = crear_materia()
    registrar(client)
    r = subir(client, m.id)
    assert "¡Apunte publicado!".encode() in r.data

    a = Apunte.query.one()
    assert a.nombre_original == "sql.txt"
    assert a.extension == "txt"
    assert a.tamano_bytes == len(b"SELECT 1;")
    assert len(a.hash_sha256) == 64
    assert {e.nombre for e in a.etiquetas} == {"sql", "parcial1"}

    r = client.get(f"/apuntes/{a.id}/descargar")
    assert r.status_code == 200 and r.data == b"SELECT 1;"
    assert Descarga.query.count() == 1


def test_rechaza_extension_no_permitida(client):
    m = crear_materia()
    registrar(client)
    r = subir(client, m.id, nombre="virus.exe")
    assert b"Tipo de archivo no permitido" in r.data
    assert Apunte.query.count() == 0


def test_calificacion_unica_y_actualizable(client):
    m = crear_materia()
    registrar(client)
    subir(client, m.id)
    a = Apunte.query.one()

    r = client.post(f"/apuntes/{a.id}/calificar", data={"estrellas": 5}, follow_redirects=True)
    assert "No puedes calificar tu propio apunte".encode() in r.data

    logout(client)
    registrar(client, "Luis", "luis@test.edu")
    client.post(f"/apuntes/{a.id}/calificar", data={"estrellas": 5})
    client.post(f"/apuntes/{a.id}/calificar", data={"estrellas": 3})
    assert Calificacion.query.count() == 1
    assert db.session.get(Apunte, a.id).promedio_estrellas == 3

    with pytest.raises(IntegrityError):  # la BD impide duplicados
        db.session.add(Calificacion(usuario_id=2, apunte_id=a.id, estrellas=4))
        db.session.commit()
    db.session.rollback()


def test_like_toggle(client):
    m = crear_materia()
    registrar(client)
    subir(client, m.id)
    a = Apunte.query.one()
    client.post(f"/apuntes/{a.id}/like")
    assert len(db.session.get(Apunte, a.id).usuarios_like) == 1
    client.post(f"/apuntes/{a.id}/like")
    assert len(db.session.get(Apunte, a.id).usuarios_like) == 0


def test_foro_comentarios_y_respuestas(client):
    m = crear_materia()
    registrar(client)
    subir(client, m.id)
    a = Apunte.query.one()

    client.post("/comentar", data={"apunte_id": a.id, "contenido": "¡Genial!"})
    padre = Comentario.query.one()
    client.post("/comentar", data={"apunte_id": a.id, "padre_id": padre.id, "contenido": "Gracias"})
    client.post("/comentar", data={"materia_id": m.id, "contenido": "¿Grupo de estudio?"})

    assert len(db.session.get(Apunte, a.id).comentarios) == 2
    assert [r.contenido for r in padre.respuestas] == ["Gracias"]
    assert len(db.session.get(Materia, m.id).comentarios) == 1
    assert "¡Genial!".encode() in client.get(f"/apuntes/{a.id}").data
    assert "¿Grupo de estudio?".encode() in client.get(f"/materias/{m.id}").data


def test_flujo_tutoria(client):
    m = crear_materia()
    registrar(client)  # Ana = tutora
    subir(client, m.id)
    a = Apunte.query.one()
    logout(client)

    registrar(client, "Luis", "luis@test.edu")
    client.post(f"/tutorias/solicitar/{a.autor_id}",
                data={"tema": "JOINs", "mensaje": "Ayuda", "apunte_id": a.id, "modalidad": "virtual"})
    s = SolicitudTutoria.query.one()
    assert s.estado == "pendiente" and s.apunte_id == a.id and s.materia_id == m.id

    assert client.post(f"/tutorias/{s.id}/aceptar").status_code == 403  # Luis no es el tutor
    logout(client)

    login(client, "ana@test.edu")
    client.post(f"/tutorias/{s.id}/aceptar", data={"respuesta": "Nos vemos el lunes"})
    assert db.session.get(SolicitudTutoria, s.id).estado == "aceptada"
    client.post(f"/tutorias/{s.id}/completar")
    assert db.session.get(SolicitudTutoria, s.id).estado == "completada"
    assert client.post(f"/tutorias/{s.id}/aceptar").status_code == 400  # transición inválida


def test_solo_el_autor_elimina_y_borra_en_cascada(client, app):
    import os
    m = crear_materia()
    registrar(client)
    subir(client, m.id)
    a = Apunte.query.one()
    ruta = os.path.join(app.config["UPLOAD_FOLDER"], a.nombre_almacenado)
    client.post("/comentar", data={"apunte_id": a.id, "contenido": "hola"})
    logout(client)

    registrar(client, "Luis", "luis@test.edu")
    assert client.post(f"/apuntes/{a.id}/eliminar").status_code == 403
    logout(client)

    login(client, "ana@test.edu")
    client.post(f"/apuntes/{a.id}/eliminar")
    assert Apunte.query.count() == 0 and Comentario.query.count() == 0
    assert not os.path.exists(ruta)


def test_seed_y_paginas_publicas(client):
    poblar_datos_demo()
    assert Usuario.query.count() == 5 and Apunte.query.count() == 10
    for url in ["/", "/materias", "/apuntes", "/ranking", "/apuntes/1", "/materias/1", "/usuarios/1",
                "/apuntes?etiqueta=sql"]:
        assert client.get(url).status_code == 200, url
    login(client, "ana@uni.edu", "demo123")
    for url in ["/", "/tutorias/", "/apuntes/subir", "/perfil/editar", "/materias/nueva", "/tutorias/solicitar/2"]:
        assert client.get(url).status_code == 200, url


def test_carga_datos_demo_si_la_bd_esta_vacia(tmp_path):
    class Cfg(TestConfig):
        AUTO_SEED = True
        UPLOAD_FOLDER = str(tmp_path / "uploads")

    app = create_app(Cfg)
    with app.app_context():
        assert Usuario.query.filter_by(email="ana@uni.edu").one().check_password("demo123")
        r = app.test_client().post("/login", data={"email": "ana@uni.edu", "password": "demo123"},
                                   follow_redirects=True)
        assert b"Novedades de tus materias" in r.data
        db.session.remove()
        db.drop_all()


def test_admin_solo_para_administradores(client):
    poblar_datos_demo()
    assert client.get("/admin/").status_code == 302  # sin sesión -> login
    login(client, "luis@uni.edu", "demo123")
    assert client.get("/admin/").status_code == 403
    assert client.get("/admin/usuario/").status_code == 403
    logout(client)

    login(client, "ana@uni.edu", "demo123")
    assert b"Panel de administraci" in client.get("/admin/").data
    for vista in ["usuario", "materia", "apunte", "etiqueta", "calificacion", "descarga", "comentario",
                  "solicitudtutoria"]:
        assert client.get(f"/admin/{vista}/").status_code == 200, vista
        assert client.get(f"/admin/{vista}/details/?id=1").status_code == 200, vista
    assert client.get("/admin/usuario/edit/?id=2").status_code == 200
    assert client.get("/admin/materia/new/").status_code == 200


def test_admin_edita_y_elimina_datos(client, app):
    import os
    poblar_datos_demo()
    login(client, "ana@uni.edu", "demo123")

    m = Materia.query.filter_by(codigo="MAT101").one()
    r = client.post(f"/admin/materia/edit/?id={m.id}",
                    data={"codigo": "MAT101", "nombre": "Cálculo I", "semestre": "1"}, follow_redirects=True)
    assert r.status_code == 200
    db.session.expire_all()
    assert db.session.get(Materia, m.id).nombre == "Cálculo I"

    luis = Usuario.query.filter_by(email="luis@uni.edu").one()
    client.post(f"/admin/usuario/edit/?id={luis.id}",
                data={"nombre": "Luis P.", "email": "luis@uni.edu", "nueva_contrasena": "nueva123"})
    db.session.expire_all()
    assert db.session.get(Usuario, luis.id).check_password("nueva123")

    a = Apunte.query.first()
    ruta = os.path.join(app.config["UPLOAD_FOLDER"], a.nombre_almacenado)
    assert os.path.exists(ruta)
    client.post("/admin/apunte/delete/", data={"id": a.id})
    assert db.session.get(Apunte, a.id) is None and not os.path.exists(ruta)

    # borrar un usuario con apuntes, tutorías y comentarios no rompe la base de datos
    client.post("/admin/usuario/delete/", data={"id": luis.id})
    db.session.expire_all()
    assert db.session.get(Usuario, luis.id) is None
    assert SolicitudTutoria.query.filter(
        (SolicitudTutoria.solicitante_id == luis.id) | (SolicitudTutoria.tutor_id == luis.id)).count() == 0

    ana = Usuario.query.filter_by(email="ana@uni.edu").one()
    client.post("/admin/usuario/delete/", data={"id": ana.id})
    assert db.session.get(Usuario, ana.id) is not None  # no puede borrarse a sí misma


def test_guardar_y_cargar_datos_en_otro_computador(tmp_path):
    """Los datos guardados en datos/ aparecen al instalar el proyecto en otro computador."""
    import os

    carpeta_datos = tmp_path / "datos"

    class Computador1(TestConfig):
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(tmp_path / "pc1.db")
        UPLOAD_FOLDER = str(tmp_path / "uploads1")
        DATOS_DIR = str(carpeta_datos)

    app1 = create_app(Computador1)
    with app1.app_context():
        poblar_datos_demo()
        cliente = app1.test_client()
        login(cliente, "ana@uni.edu", "demo123")
        m = crear_materia("NUE100", "Materia nueva")
        subir(cliente, m.id, titulo="Mi apunte", contenido=b"contenido real", nombre="mio.txt")
        luis = Usuario.query.filter_by(email="luis@uni.edu").one()
        luis.nombre = "Luis Editado"
        db.session.commit()
        app1.test_cli_runner().invoke(args=["guardar-datos"])
        db.session.remove()

    assert (carpeta_datos / "datos.json").exists()
    assert len(os.listdir(carpeta_datos / "archivos")) == 11

    class Computador2(Computador1):  # base de datos nueva y vacía, misma carpeta datos/
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(tmp_path / "pc2.db")
        UPLOAD_FOLDER = str(tmp_path / "uploads2")
        AUTO_SEED = True

    app2 = create_app(Computador2)
    with app2.app_context():
        assert Usuario.query.filter_by(email="luis@uni.edu").one().nombre == "Luis Editado"
        assert Materia.query.filter_by(codigo="NUE100").one()
        apunte = Apunte.query.filter_by(titulo="Mi apunte").one()
        cliente = app2.test_client()
        login(cliente, "ana@uni.edu", "demo123")
        assert cliente.get(f"/apuntes/{apunte.id}/descargar").data == b"contenido real"
        # se puede seguir usando con normalidad (los ids nuevos no chocan)
        assert b"publicado" in subir(cliente, apunte.materia_id, titulo="Otro", nombre="otro.txt").data
        db.session.remove()
