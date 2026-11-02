import io

import pytest

from app import create_app
from colorimetria import RespuestasInvalidas, clasificar
from extensions import db
from models import Guardarropa, Like, Publicacion, Reporte, TestResult, User
from services import gemini_service

CALIDO = {"p1": "calido", "p2": "calido", "p3": "calido", "p4": "calido", "p5": "frio", "p6": "frio", "p7": "suave"}
FRIO = {"p1": "frio", "p2": "frio", "p3": "frio", "p4": "frio", "p5": "calido", "p6": "calido", "p7": "alto"}
NEUTRO = {"p1": "calido", "p2": "neutro", "p3": "neutro", "p4": "calido", "p5": "frio", "p6": "frio", "p7": "alto"}


@pytest.fixture(autouse=True)
def sin_gemini(monkeypatch):
    """Las pruebas nunca llaman a la API real."""
    monkeypatch.setattr(gemini_service, "GEMINI_API_KEY", "")


@pytest.fixture
def app(tmp_path):
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    app.config["COMUNIDAD_UPLOAD_FOLDER"] = str(tmp_path / "comunidad")
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def crear_usuario(app, email="ana@example.com", password="secreta123", confirmado=True):
    with app.app_context():
        u = User(nombre="Ana", email=email, is_confirmed=confirmado)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()


def iniciar_sesion(client, app, email="ana@example.com", password="secreta123"):
    crear_usuario(app, email, password)
    return client.post("/login", data={"email": email, "password": password})


# ---------- colorimetría ----------
def test_clasifica_calido_frio_y_neutro():
    assert clasificar(CALIDO)["subtono"] == "calido"
    assert clasificar(FRIO)["subtono"] == "frio"
    assert clasificar(NEUTRO)["subtono"] == "neutro"


def test_respuestas_incompletas_o_invalidas():
    with pytest.raises(RespuestasInvalidas):
        clasificar({"p1": "calido", "p2": "calido"})
    with pytest.raises(RespuestasInvalidas):
        clasificar({**CALIDO, "p3": "x"})


# ---------- autenticación ----------
def test_registro_guarda_hash_y_exige_confirmacion(client, app):
    r = client.post(
        "/registro",
        data={"nombre": "Ana", "email": "ana@example.com", "password": "secreta123", "confirmar": "secreta123"},
    )
    assert r.status_code == 302
    with app.app_context():
        u = db.session.scalar(db.select(User).filter_by(email="ana@example.com"))
        assert u.password_hash != "secreta123" and u.check_password("secreta123")
        assert u.is_confirmed is False
    # sin confirmar no puede entrar
    r = client.post("/login", data={"email": "ana@example.com", "password": "secreta123"})
    assert r.status_code == 403


def test_registro_valida_datos(client, app):
    r = client.post(
        "/registro",
        data={"nombre": "A", "email": "malcorreo", "password": "123", "confirmar": "456"},
    )
    assert r.status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0


def test_registro_correo_duplicado(client, app):
    crear_usuario(app)
    r = client.post(
        "/registro",
        data={"nombre": "Ana", "email": "ana@example.com", "password": "secreta123", "confirmar": "secreta123"},
    )
    assert r.status_code == 400


def test_login_correcto_e_incorrecto(client, app):
    crear_usuario(app)
    assert client.post("/login", data={"email": "ana@example.com", "password": "mala"}).status_code == 401
    ok = client.post("/login", data={"email": "ANA@example.com", "password": "secreta123"})
    assert ok.status_code == 302


def test_login_no_redirige_a_sitios_externos(client, app):
    crear_usuario(app)
    r = client.post(
        "/login",
        data={"email": "ana@example.com", "password": "secreta123", "next": "https://evil.com"},
    )
    assert r.headers["Location"] == "/"


def test_historial_requiere_login(client):
    r = client.get("/historial")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


# ---------- test de colorimetría ----------
def test_anonimo_completa_flujo_sin_guardar(client, app):
    assert client.post("/test", data=CALIDO).status_code == 200  # pantalla "procesando"
    assert client.post("/api/generar-diagnostico").json["success"] is True
    assert client.get("/resultado").status_code == 200
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(TestResult.id))) == 0


def test_autenticado_guarda_una_sola_vez(client, app):
    iniciar_sesion(client, app)
    client.post("/test", data=CALIDO)
    client.post("/api/generar-diagnostico")
    client.post("/api/generar-diagnostico")  # repetido: no duplica
    client.get("/resultado")  # tampoco duplica
    with app.app_context():
        filas = db.session.scalars(db.select(TestResult)).all()
        assert len(filas) == 1
        assert filas[0].subtono == "calido" and filas[0].respuestas == CALIDO
    assert b"Primavera" in client.get("/historial").data


def test_resultado_directo_sin_api_tambien_funciona(client):
    client.post("/test", data=FRIO)
    assert client.get("/resultado").status_code == 200


def test_api_diagnostico_sin_test_devuelve_400(client):
    assert client.post("/api/generar-diagnostico").status_code == 400


def test_test_incompleto_regresa(client):
    r = client.post("/test", data={"p1": "calido"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/test")


def test_resultado_sin_test_redirige(client):
    r = client.get("/resultado")
    assert r.status_code == 302 and r.headers["Location"].endswith("/test")


# ---------- chat ----------
def test_chat_invitado_limitado_a_3(client):
    for _ in range(3):
        assert client.post("/api/chat-ia", json={"pregunta": "¿qué me pongo?"}).status_code == 200
    r = client.post("/api/chat-ia", json={"pregunta": "otra"})
    assert r.status_code == 403 and r.json["limite_alcanzado"]


def test_chat_pregunta_vacia(client):
    assert client.post("/api/chat-ia", json={"pregunta": " "}).status_code == 400


# ---------- guardarropa ----------
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_guardarropa_subir_y_eliminar(client, app):
    iniciar_sesion(client, app)
    r = client.post(
        "/guardarropa/subir",
        data={"nombre": "Camisa", "categoria": "Superior", "foto": (io.BytesIO(PNG), "camisa.png")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 302
    with app.app_context():
        prenda = db.session.scalar(db.select(Guardarropa))
        assert prenda is not None
        pid = prenda.id
    assert client.post(f"/guardarropa/eliminar/{pid}").status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(Guardarropa)) is None


def test_no_puede_eliminar_prenda_ajena(client, app):
    crear_usuario(app, "otra@example.com")
    with app.app_context():
        otra = db.session.scalar(db.select(User).filter_by(email="otra@example.com"))
        db.session.add(Guardarropa(usuario_id=otra.id, nombre="X", categoria="Superior", imagen="x.png"))
        db.session.commit()
        pid = db.session.scalar(db.select(Guardarropa)).id
    iniciar_sesion(client, app)
    client.post(f"/guardarropa/eliminar/{pid}")
    with app.app_context():
        assert db.session.scalar(db.select(Guardarropa)) is not None


# ---------- seguridad ----------
def test_api_exige_csrf(app):
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    r = c.post("/api/chat-ia", json={"pregunta": "hola"})
    assert r.status_code in (302, 400)  # CSRFError redirige con aviso
    r = c.post("/api/generar-diagnostico")
    assert r.status_code in (302, 400)


def test_reset_password_token_de_un_solo_uso(client, app):
    from services.email_service import generar_token_reset

    crear_usuario(app)
    with app.test_request_context():
        with app.app_context():
            usuario = db.session.scalar(db.select(User))
            token = generar_token_reset(usuario)
    assert client.get(f"/reset-password/{token}").status_code == 200
    r = client.post(f"/reset-password/{token}", data={"password": "nuevaclave1", "confirmar": "nuevaclave1"})
    assert r.status_code == 302
    # el mismo enlace ya no sirve
    r = client.get(f"/reset-password/{token}")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert client.post("/login", data={"email": "ana@example.com", "password": "nuevaclave1"}).status_code == 302


def test_reset_token_manipulado_rechazado(client):
    assert client.get("/reset-password/token-falso").status_code == 302


def test_subida_rechaza_archivo_no_imagen(client, app):
    iniciar_sesion(client, app)
    falso = b"<?php echo 1; ?>"
    client.post(
        "/guardarropa/subir",
        data={"nombre": "Malo", "categoria": "Superior", "foto": (io.BytesIO(falso), "malo.png")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        assert db.session.scalar(db.select(Guardarropa)) is None


def test_chat_trunca_preguntas_largas(client, monkeypatch):
    recibido = {}

    def falso(pregunta, contexto=None):
        recibido["q"] = pregunta
        return "ok"

    import routes

    monkeypatch.setattr(routes, "responder_chat_estilista", falso)
    client.post("/api/chat-ia", json={"pregunta": "a" * 5000})
    assert len(recibido["q"]) == 500


def test_limite_de_intentos_de_login(monkeypatch, tmp_path):
    from config import TestingConfig

    monkeypatch.setattr(TestingConfig, "RATELIMIT_ENABLED", True)
    app = create_app("testing")
    try:
        crear_usuario(app)
        c = app.test_client()
        codigos = [c.post("/login", data={"email": "ana@example.com", "password": "mala"}).status_code for _ in range(12)]
        assert codigos[:10] == [401] * 10
        assert 429 in codigos[10:] or 303 in codigos[10:]
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_cabeceras_de_seguridad(client):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


# ---------- confirmación de correo ----------
def test_fallo_de_correo_avisa_y_permite_reenviar(client, app, monkeypatch):
    import routes

    def falla(*a, **k):
        raise RuntimeError("SMTP caído")

    monkeypatch.setattr(routes, "enviar_correo_confirmacion", falla)
    r = client.post(
        "/registro",
        data={"nombre": "Ana", "email": "ana@example.com", "password": "secreta123", "confirmar": "secreta123"},
        follow_redirects=True,
    )
    assert "Reenviar correo".encode() in r.data or b"Reenviar" in r.data
    r = client.post("/login", data={"email": "ana@example.com", "password": "secreta123"})
    assert r.status_code == 403 and "Reenviar correo de confirmación".encode() in r.data


def test_reenviar_confirmacion_respuesta_uniforme(client, app, monkeypatch):
    import routes

    enviados = []
    monkeypatch.setattr(routes, "enviar_correo_confirmacion", lambda e, n: enviados.append(e))
    crear_usuario(app, "pendiente@example.com", confirmado=False)
    crear_usuario(app, "listo@example.com")
    for correo in ("pendiente@example.com", "listo@example.com", "noexiste@example.com"):
        assert client.post("/reenviar-confirmacion", data={"email": correo}).status_code == 302
    assert enviados == ["pendiente@example.com"]


# ---------- comunidad ----------
def publicar(client, nombre="outfit.png", contenido=PNG, descripcion="Look de oficina"):
    return client.post(
        "/comunidad/publicar",
        data={"foto": (io.BytesIO(contenido), nombre), "descripcion": descripcion},
        content_type="multipart/form-data",
    )


def usuario_con_test(client, app, email="ana@example.com"):
    iniciar_sesion(client, app, email=email)
    client.post("/test", data=CALIDO)
    client.post("/api/generar-diagnostico")


def test_feed_es_publico(client):
    r = client.get("/comunidad")
    assert r.status_code == 200 and "Aún no hay publicaciones".encode() in r.data


def test_publicar_requiere_login(client):
    r = publicar(client)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_publicar_requiere_haber_hecho_el_test(client, app):
    iniciar_sesion(client, app)
    r = publicar(client)
    assert r.status_code == 302 and r.headers["Location"].endswith("/test")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Publicacion.id))) == 0


def test_publicar_adjunta_colorimetria_y_aparece_en_el_feed(client, app):
    usuario_con_test(client, app)
    assert publicar(client).status_code == 302
    with app.app_context():
        p = db.session.scalar(db.select(Publicacion))
        assert p.subtono == "calido" and "Primavera" in p.estacion
        assert len(p.paleta) == 4 and p.descripcion == "Look de oficina"
    html = client.get("/comunidad").data.decode()
    assert "Look de oficina" in html and "Primavera" in html and "Ana" in html


def test_publicar_rechaza_archivos_que_no_son_imagen(client, app):
    usuario_con_test(client, app)
    publicar(client, nombre="falso.png", contenido=b"<?php echo 1; ?>")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Publicacion.id))) == 0


def test_descripcion_se_recorta_y_se_escapa(client, app):
    usuario_con_test(client, app)
    publicar(client, descripcion="<script>alert(1)</script>" + "a" * 900)
    with app.app_context():
        assert len(db.session.scalar(db.select(Publicacion)).descripcion) == 500
    assert b"<script>alert(1)" not in client.get("/comunidad").data


def test_eliminar_propia_publicacion_borra_la_imagen(client, app):
    import os

    usuario_con_test(client, app)
    publicar(client)
    carpeta = app.config["COMUNIDAD_UPLOAD_FOLDER"]
    assert len(os.listdir(carpeta)) == 1
    with app.app_context():
        pid = db.session.scalar(db.select(Publicacion)).id
    assert client.post(f"/comunidad/eliminar/{pid}").status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(Publicacion)) is None
    assert os.listdir(carpeta) == []


def test_no_se_puede_eliminar_publicacion_ajena(client, app):
    usuario_con_test(client, app, email="ana@example.com")
    publicar(client)
    client.post("/logout")
    iniciar_sesion(client, app, email="otra@example.com")
    with app.app_context():
        pid = db.session.scalar(db.select(Publicacion)).id
    client.post(f"/comunidad/eliminar/{pid}")
    with app.app_context():
        assert db.session.scalar(db.select(Publicacion)) is not None


def test_feed_pagina_de_9_en_9(client, app):
    usuario_con_test(client, app)
    for _ in range(10):
        publicar(client)
    assert b"P\xc3\xa1gina 1 de 2" in client.get("/comunidad").data
    assert client.get("/comunidad?pagina=2").status_code == 200
    assert client.get("/comunidad?pagina=99").status_code == 200


# ---------- likes y reportes ----------
def publicacion_de_ana(app, client):
    """Ana (con test hecho) publica y devuelve el id de la publicación."""
    usuario_con_test(client, app, email="ana@example.com")
    publicar(client)
    with app.app_context():
        return db.session.scalar(db.select(Publicacion)).id


def otra_persona(app, email):
    c = app.test_client()
    iniciar_sesion(c, app, email=email)
    return c


def test_like_requiere_login(client, app):
    pid = publicacion_de_ana(app, client)
    client.post("/logout")
    r = client.post(f"/comunidad/like/{pid}")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_like_y_quitar_like(client, app):
    pid = publicacion_de_ana(app, client)
    luis = otra_persona(app, "luis@example.com")
    r = luis.post(f"/comunidad/like/{pid}")
    assert r.json == {"liked": True, "total": 1}
    r = luis.post(f"/comunidad/like/{pid}")
    assert r.json == {"liked": False, "total": 0}


def test_los_likes_de_varias_personas_se_suman_y_no_se_duplican(client, app):
    pid = publicacion_de_ana(app, client)
    luis = otra_persona(app, "luis@example.com")
    eva = otra_persona(app, "eva@example.com")
    luis.post(f"/comunidad/like/{pid}")
    assert eva.post(f"/comunidad/like/{pid}").json["total"] == 2
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Like.id))) == 2
    assert b'aria-pressed="true"' in luis.get("/comunidad").data


def test_like_a_publicacion_inexistente(client, app):
    iniciar_sesion(client, app)
    assert client.post("/comunidad/like/9999").status_code == 404


def test_reportar_una_vez_y_no_la_propia(client, app):
    pid = publicacion_de_ana(app, client)
    # la autora no puede reportarse a sí misma
    client.post(f"/comunidad/reportar/{pid}", data={"motivo": "spam"})
    luis = otra_persona(app, "luis@example.com")
    luis.post(f"/comunidad/reportar/{pid}", data={"motivo": "spam"})
    luis.post(f"/comunidad/reportar/{pid}", data={"motivo": "otro"})  # repetido
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Reporte.id))) == 1


def test_reporte_con_motivo_invalido_se_rechaza(client, app):
    pid = publicacion_de_ana(app, client)
    luis = otra_persona(app, "luis@example.com")
    luis.post(f"/comunidad/reportar/{pid}", data={"motivo": "inventado"})
    luis.post(f"/comunidad/reportar/{pid}", data={})
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Reporte.id))) == 0


def test_tres_reportes_ocultan_la_publicacion_menos_a_su_autora(client, app):
    pid = publicacion_de_ana(app, client)
    personas = [otra_persona(app, f"p{i}@example.com") for i in range(3)]
    for i, c in enumerate(personas):
        # con 2 reportes todavía se ve
        if i == 2:
            assert b"Look de oficina" in c.get("/comunidad").data
        c.post(f"/comunidad/reportar/{pid}", data={"motivo": "spam"})
    # ya no se ve para el resto ni para visitantes
    assert b"Look de oficina" not in personas[0].get("/comunidad").data
    assert b"Look de oficina" not in app.test_client().get("/comunidad").data
    # su autora sí la ve, con aviso de revisión
    html = client.get("/comunidad").data.decode()
    assert "Look de oficina" in html and "En revisión" in html


def test_eliminar_publicacion_borra_sus_likes_y_reportes(client, app):
    pid = publicacion_de_ana(app, client)
    luis = otra_persona(app, "luis@example.com")
    luis.post(f"/comunidad/like/{pid}")
    luis.post(f"/comunidad/reportar/{pid}", data={"motivo": "spam"})
    client.post(f"/comunidad/eliminar/{pid}")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Like.id))) == 0
        assert db.session.scalar(db.select(db.func.count(Reporte.id))) == 0


def test_visitante_ve_contador_de_likes_pero_no_el_boton_de_reportar(client, app):
    pid = publicacion_de_ana(app, client)
    luis = otra_persona(app, "luis@example.com")
    luis.post(f"/comunidad/like/{pid}")
    html = app.test_client().get("/comunidad").data.decode()
    assert 'class="com-like-count">1<' in html and "Reportar" not in html


# ---------- guardarropa en el servicio de imágenes ----------
def test_prenda_guarda_url_y_el_archivo(client, app):
    import os

    iniciar_sesion(client, app)
    client.post(
        "/guardarropa/subir",
        data={"nombre": "Camisa", "categoria": "Superior", "foto": (io.BytesIO(PNG), "camisa.png")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        imagen = db.session.scalar(db.select(Guardarropa)).imagen
    assert imagen.startswith("/static/uploads/guardarropa/")
    assert len(os.listdir(app.config["UPLOAD_FOLDER"])) == 1
    assert imagen.encode() in client.get("/guardarropa").data


def test_eliminar_prenda_borra_el_archivo(client, app):
    import os

    iniciar_sesion(client, app)
    client.post(
        "/guardarropa/subir",
        data={"nombre": "Camisa", "categoria": "Superior", "foto": (io.BytesIO(PNG), "camisa.png")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        pid = db.session.scalar(db.select(Guardarropa)).id
    client.post(f"/guardarropa/eliminar/{pid}")
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == []


def test_prenda_antigua_con_nombre_de_archivo_sigue_funcionando(client, app):
    import os

    iniciar_sesion(client, app)
    carpeta = app.config["UPLOAD_FOLDER"]
    open(os.path.join(carpeta, "vieja.png"), "wb").write(PNG)
    with app.app_context():
        usuario = db.session.scalar(db.select(User))
        db.session.add(Guardarropa(usuario_id=usuario.id, nombre="Vieja", categoria="Superior", imagen="vieja.png"))
        db.session.commit()
        pid = db.session.scalar(db.select(Guardarropa)).id
    assert b"uploads/guardarropa/vieja.png" in client.get("/guardarropa").data
    client.post(f"/guardarropa/eliminar/{pid}")
    assert not os.path.exists(os.path.join(carpeta, "vieja.png"))


def test_id_desde_url():
    from services.imagen_service import id_desde_url

    assert id_desde_url(
        "https://res.cloudinary.com/demo/image/upload/v1730000000/set-match-go/guardarropa/abc123.jpg"
    ) == "set-match-go/guardarropa/abc123"
    assert id_desde_url("/static/uploads/guardarropa/x.png") == "local:guardarropa/x.png"
    assert id_desde_url("x.png") == "local:guardarropa/x.png"
    assert id_desde_url("") is None

