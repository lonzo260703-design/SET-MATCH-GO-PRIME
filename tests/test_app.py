import io

import pytest

from app import create_app
from colorimetria import RespuestasInvalidas, clasificar
from extensions import db
from models import Guardarropa, TestResult, User
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
