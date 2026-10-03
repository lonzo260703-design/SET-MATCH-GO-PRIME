import pytest

from app import create_app
from colorimetria import RespuestasInvalidas, clasificar
from extensions import db
from models import TestResult, User

RESPUESTAS_CALIDO = {"p1": "calido", "p2": "calido", "p3": "frio"}


@pytest.fixture
def app():
    app = create_app("testing")
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def registrar(client, email="ana@example.com", password="secreta123"):
    return client.post(
        "/registro",
        data={"nombre": "Ana", "email": email, "password": password, "confirmar": password},
    )


# ---------- colorimetría ----------
def test_clasifica_calido_frio_y_neutro():
    assert clasificar(RESPUESTAS_CALIDO)["subtono"] == "calido"
    assert clasificar({"p1": "frio", "p2": "frio", "p3": "calido"})["subtono"] == "frio"
    assert clasificar({"p1": "calido", "p2": "frio", "p3": "neutro"})["subtono"] == "neutro"


def test_respuestas_incompletas_o_invalidas():
    with pytest.raises(RespuestasInvalidas):
        clasificar({"p1": "calido", "p2": "calido"})
    with pytest.raises(RespuestasInvalidas):
        clasificar({"p1": "calido", "p2": "calido", "p3": "x"})


# ---------- autenticación ----------
def test_registro_guarda_hash_y_abre_sesion(client, app):
    r = registrar(client)
    assert r.status_code == 302
    with app.app_context():
        u = db.session.scalar(db.select(User).filter_by(email="ana@example.com"))
        assert u is not None
        assert u.password_hash != "secreta123"
        assert u.check_password("secreta123")
    assert client.get("/historial").status_code == 200


def test_registro_valida_datos(client, app):
    r = client.post(
        "/registro",
        data={"nombre": "A", "email": "malcorreo", "password": "123", "confirmar": "456"},
    )
    assert r.status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0


def test_registro_correo_duplicado(client):
    registrar(client)
    client.post("/logout")
    assert registrar(client).status_code == 400


def test_login_correcto_e_incorrecto(client):
    registrar(client)
    client.post("/logout")
    assert client.post("/login", data={"email": "ana@example.com", "password": "mala"}).status_code == 401
    ok = client.post("/login", data={"email": "ANA@example.com", "password": "secreta123"})
    assert ok.status_code == 302


def test_login_no_redirige_a_sitios_externos(client):
    registrar(client)
    client.post("/logout")
    r = client.post(
        "/login",
        data={"email": "ana@example.com", "password": "secreta123", "next": "https://evil.com"},
    )
    assert r.headers["Location"] == "/"


def test_historial_requiere_login(client):
    r = client.get("/historial")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


# ---------- test de colorimetría ----------
def test_usuario_anonimo_ve_resultado_pero_no_se_guarda(client, app):
    r = client.post("/test", data=RESPUESTAS_CALIDO)
    assert r.status_code == 302 and r.headers["Location"].endswith("/resultado")
    assert client.get("/resultado").status_code == 200
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(TestResult.id))) == 0


def test_usuario_autenticado_guarda_resultado(client, app):
    registrar(client)
    client.post("/test", data=RESPUESTAS_CALIDO)
    with app.app_context():
        r = db.session.scalar(db.select(TestResult))
        assert r.subtono == "calido"
        assert r.respuestas == RESPUESTAS_CALIDO
    assert b"Subtono C" in client.get("/historial").data


def test_test_incompleto_no_guarda_y_regresa(client):
    r = client.post("/test", data={"p1": "calido"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/test")


def test_resultado_sin_test_redirige(client):
    r = client.get("/resultado")
    assert r.status_code == 302 and r.headers["Location"].endswith("/test")
