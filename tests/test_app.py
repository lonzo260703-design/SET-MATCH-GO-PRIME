import os
import io

import pytest

from app import create_app
from colorimetria import RespuestasInvalidas, clasificar
from extensions import db
from models import Guardarropa, Like, Publicacion, PrendaCatalogo, Reporte, TestResult, User
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
    app.config["CATALOGO_UPLOAD_FOLDER"] = str(tmp_path / "catalogo")
    app.config["ADMIN_EMAILS"] = {"admin@example.com"}
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
        data={"nombre": "Ana", "email": "ana@example.com", "password": "secreta123", "confirmar": "secreta123", "acepto": "1"},
    )
    assert r.status_code == 302
    with app.app_context():
        u = db.session.scalar(db.select(User).filter_by(email="ana@example.com"))
        assert u.password_hash != "secreta123" and u.check_password("secreta123")
        assert u.is_confirmed is False
    # sin confirmar no puede entrar
    r = client.post("/login", data={"email": "ana@example.com", "password": "secreta123"})
    assert r.status_code == 403


def test_registro_exige_aceptar_el_aviso_de_privacidad(client, app):
    r = client.post(
        "/registro",
        data={"nombre": "Ana", "email": "ana@example.com", "password": "secreta123", "confirmar": "secreta123"},
    )
    assert r.status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0


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
        data={"nombre": "Ana", "email": "ana@example.com", "password": "secreta123", "confirmar": "secreta123", "acepto": "1"},
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


def prenda_propia(app, email="ana@example.com", nombre="Camisa"):
    """Prenda 'subida' antes de que se quitara la subida: archivo local + fila con origen 'propia'."""
    import uuid

    carpeta = app.config["UPLOAD_FOLDER"]
    os.makedirs(carpeta, exist_ok=True)
    archivo = f"{uuid.uuid4().hex}.png"
    with open(os.path.join(carpeta, archivo), "wb") as f:
        f.write(PNG)
    with app.app_context():
        uid = db.session.scalar(db.select(User.id).filter_by(email=email))
        prenda = Guardarropa(usuario_id=uid, nombre=nombre, categoria="Superior",
                             imagen=f"/static/uploads/guardarropa/{archivo}", origen="propia")
        db.session.add(prenda)
        db.session.commit()
        return prenda.id


def test_guardarropa_eliminar_prenda_propia(client, app):
    iniciar_sesion(client, app)
    pid = prenda_propia(app)
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


def test_ya_no_se_pueden_subir_prendas_propias(client, app):
    iniciar_sesion(client, app)
    r = client.post(
        "/guardarropa/subir",
        data={"nombre": "Camisa", "categoria": "Superior", "foto": (io.BytesIO(PNG), "camisa.png")},
        content_type="multipart/form-data",
    )
    assert r.status_code in (404, 405)
    with app.app_context():
        assert db.session.scalar(db.select(Guardarropa)) is None
    assert b"foto" not in client.get("/guardarropa").data.split(b"wardrobe-grid")[0]


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
        data={"nombre": "Ana", "email": "ana@example.com", "password": "secreta123", "confirmar": "secreta123", "acepto": "1"},
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
def test_guardarropa_muestra_la_foto_de_la_prenda(client, app):
    iniciar_sesion(client, app)
    pid = prenda_propia(app)
    with app.app_context():
        imagen = db.session.get(Guardarropa, pid).imagen
    assert imagen.encode() in client.get("/guardarropa").data


def test_eliminar_prenda_borra_el_archivo(client, app):
    iniciar_sesion(client, app)
    pid = prenda_propia(app)
    assert len(os.listdir(app.config["UPLOAD_FOLDER"])) == 1
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



# ---------- Etapa 3: compartir ----------
def test_republicar_crea_copia_con_misma_foto(app, client):
    pid = publicacion_de_ana(app, client)
    bea = otra_persona(app, "bea@example.com")
    r = bea.post(f"/comunidad/republicar/{pid}", data={"descripcion": "¡Me encanta!"})
    assert r.status_code == 302
    with app.app_context():
        copia = db.session.scalar(db.select(Publicacion).where(Publicacion.original_id == pid))
        original = db.session.get(Publicacion, pid)
        assert copia.imagen_id == original.imagen_id and copia.estacion == original.estacion
        assert copia.descripcion == "¡Me encanta!"
        assert copia.usuario.email == "bea@example.com"


def test_no_se_puede_republicar_dos_veces_ni_lo_propio(app, client):
    pid = publicacion_de_ana(app, client)
    assert client.post(f"/comunidad/republicar/{pid}").status_code == 302  # Ana: propia
    bea = otra_persona(app, "bea@example.com")
    bea.post(f"/comunidad/republicar/{pid}")
    bea.post(f"/comunidad/republicar/{pid}")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Publicacion.id)).where(Publicacion.original_id == pid)) == 1
        assert db.session.scalar(db.select(db.func.count(Publicacion.id))) == 2


def test_republicar_una_republicacion_apunta_al_original(app, client):
    pid = publicacion_de_ana(app, client)
    bea = otra_persona(app, "bea@example.com")
    bea.post(f"/comunidad/republicar/{pid}")
    with app.app_context():
        copia_id = db.session.scalar(db.select(Publicacion.id).where(Publicacion.original_id == pid))
    cami = otra_persona(app, "cami@example.com")
    cami.post(f"/comunidad/republicar/{copia_id}")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Publicacion.id)).where(Publicacion.original_id == pid)) == 2


def test_republicar_requiere_login(app, client):
    pid = publicacion_de_ana(app, client)
    client.get("/logout")
    r = app.test_client().post(f"/comunidad/republicar/{pid}")
    assert r.status_code == 302 and "login" in r.headers["Location"]


def test_borrar_republicacion_no_borra_la_foto_original(app, client, monkeypatch):
    pid = publicacion_de_ana(app, client)
    bea = otra_persona(app, "bea@example.com")
    bea.post(f"/comunidad/republicar/{pid}")
    borradas = []
    monkeypatch.setattr("routes.eliminar_imagen", lambda i: borradas.append(i))
    with app.app_context():
        copia_id = db.session.scalar(db.select(Publicacion.id).where(Publicacion.original_id == pid))
    bea.post(f"/comunidad/eliminar/{copia_id}")
    assert borradas == []
    with app.app_context():
        assert db.session.get(Publicacion, pid) is not None


def test_borrar_original_borra_sus_republicaciones(app, client):
    pid = publicacion_de_ana(app, client)
    otra_persona(app, "bea@example.com").post(f"/comunidad/republicar/{pid}")
    client.post(f"/comunidad/eliminar/{pid}")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Publicacion.id))) == 0


def test_pagina_publica_con_vista_previa(app, client):
    pid = publicacion_de_ana(app, client)
    r = app.test_client().get(f"/p/{pid}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'property="og:image"' in html and "Outfit de" in html


def test_pagina_publica_404_si_no_existe(app, client):
    assert client.get("/p/9999").status_code == 404


def test_publicacion_reportada_oculta_pagina_publica_y_republicaciones(app, client):
    pid = publicacion_de_ana(app, client)
    otra_persona(app, "bea@example.com").post(f"/comunidad/republicar/{pid}")
    for i in range(3):
        otra_persona(app, f"r{i}@example.com").post(f"/comunidad/reportar/{pid}", data={"motivo": "spam"})
    anonimo = app.test_client()
    assert anonimo.get(f"/p/{pid}").status_code == 404
    assert "Outfit de" not in anonimo.get("/comunidad").get_data(as_text=True)
    assert client.get(f"/p/{pid}").status_code == 200  # su autora sí


# ---------- Etapa 4: mensajes privados ----------
def id_de(app, email):
    from models import User
    with app.app_context():
        return db.session.scalar(db.select(User.id).where(User.email == email))


def enviar_msg(c, uid, texto="Hola", **extra):
    return c.post(f"/mensajes/{uid}", data={"texto": texto, **extra})


def test_mensajes_requieren_login(app):
    c = app.test_client()
    for url in ("/mensajes", "/mensajes/1", "/mensajes/nuevo"):
        r = c.get(url)
        assert r.status_code == 302 and "login" in r.headers["Location"]
    assert c.post("/mensajes/1", data={"texto": "x"}).status_code == 302


def test_enviar_y_recibir_mensaje_marca_leido(app, client):
    iniciar_sesion(client, app, email="ana@example.com")
    bea = otra_persona(app, "bea@example.com")
    bea_id, ana_id = id_de(app, "bea@example.com"), id_de(app, "ana@example.com")
    enviar_msg(client, bea_id, "¿Qué tal tu paleta?")
    # Bea ve el contador y la bandeja
    assert 'class="msg-badge"' in bea.get("/mensajes").get_data(as_text=True)
    assert "¿Qué tal tu paleta?" in bea.get("/mensajes").get_data(as_text=True)
    # Al abrir la conversación se marca como leído
    assert "¿Qué tal tu paleta?" in bea.get(f"/mensajes/{ana_id}").get_data(as_text=True)
    assert 'class="msg-badge"' not in bea.get("/mensajes").get_data(as_text=True)


def test_mensaje_vacio_y_a_si_mismo_no_se_envian(app, client):
    iniciar_sesion(client, app, email="ana@example.com")
    otra_persona(app, "bea@example.com")
    from models import Mensaje
    enviar_msg(client, id_de(app, "bea@example.com"), "   ")
    enviar_msg(client, id_de(app, "ana@example.com"), "yo conmigo")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 0


def test_mensaje_se_recorta_a_1000_y_html_se_escapa(app, client):
    iniciar_sesion(client, app, email="ana@example.com")
    otra_persona(app, "bea@example.com")
    bea_id = id_de(app, "bea@example.com")
    enviar_msg(client, bea_id, "<script>alert(1)</script>" + "a" * 2000)
    html = client.get(f"/mensajes/{bea_id}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    from models import Mensaje
    with app.app_context():
        assert len(db.session.scalar(db.select(Mensaje.texto))) == 1000


def test_conversacion_es_privada_para_terceros(app, client):
    iniciar_sesion(client, app, email="ana@example.com")
    bea = otra_persona(app, "bea@example.com")
    cami = otra_persona(app, "cami@example.com")
    enviar_msg(client, id_de(app, "bea@example.com"), "secreto de Ana y Bea")
    ana_id = id_de(app, "ana@example.com")
    assert "secreto de Ana y Bea" not in cami.get(f"/mensajes/{ana_id}").get_data(as_text=True)
    assert "secreto de Ana y Bea" not in cami.get("/mensajes").get_data(as_text=True)


def test_enviar_outfit_en_mensaje(app, client):
    pid = publicacion_de_ana(app, client)
    bea = otra_persona(app, "bea@example.com")
    ana_id = id_de(app, "ana@example.com")
    r = bea.post(f"/mensajes/{ana_id}", data={"texto": "", "publicacion_id": pid})
    assert r.status_code == 302
    html = client.get(f"/mensajes/{id_de(app, 'bea@example.com')}").get_data(as_text=True)
    assert f"/p/{pid}" in html and "msg-outfit" in html


def test_no_se_adjunta_outfit_oculto_ajeno(app, client):
    pid = publicacion_de_ana(app, client)
    for i in range(3):
        otra_persona(app, f"r{i}@example.com").post(f"/comunidad/reportar/{pid}", data={"motivo": "spam"})
    bea = otra_persona(app, "bea@example.com")
    ana_id = id_de(app, "ana@example.com")
    bea.post(f"/mensajes/{ana_id}", data={"texto": "", "publicacion_id": pid})  # solo outfit oculto: se rechaza
    from models import Mensaje
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 0


def test_buscar_personas_por_nombre(app, client):
    iniciar_sesion(client, app, email="ana@example.com")
    otra_persona(app, "bea@example.com")
    html = client.get("/mensajes/nuevo?q=An").get_data(as_text=True)
    assert "msg-row" in html and "mensajes/%d" % id_de(app, "bea@example.com") in html
    assert "msg-row" not in client.get("/mensajes/nuevo?q=%25").get_data(as_text=True)


def test_persona_inexistente_redirige(app, client):
    iniciar_sesion(client, app, email="ana@example.com")
    assert client.get("/mensajes/9999").status_code == 302


# ---------- Etapa 5: catálogo y panel de administración ----------
DATOS_PRENDA = {
    "nombre": "Blazer azul", "categoria": "Abrigo", "estacion": "Invierno",
    "colores": "Azul marino", "precio": "1299.50", "sucursal": "Centro",
    "enlace_compra": "https://tienda.example.com/blazer",
}


def subir_a_catalogo(c, contenido=PNG, **cambios):
    datos = {**DATOS_PRENDA, **cambios, "foto": (io.BytesIO(contenido), "p.png")}
    return c.post("/admin/prenda", data=datos, content_type="multipart/form-data")


def admin(app):
    c = app.test_client()
    iniciar_sesion(c, app, email="admin@example.com")
    return c


def test_panel_admin_oculto_para_no_admins(app, client):
    assert client.get("/admin").status_code in (302, 401)  # sin sesión
    iniciar_sesion(client, app, email="ana@example.com")
    assert client.get("/admin").status_code == 404
    assert subir_a_catalogo(client).status_code == 404
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(PrendaCatalogo.id))) == 0


def test_admin_sin_confirmar_no_entra(app):
    crear_usuario(app, email="admin@example.com", confirmado=False)
    c = app.test_client()
    c.post("/login", data={"email": "admin@example.com", "password": "secreta123"})
    assert c.get("/admin").status_code in (302, 401, 404)


def test_admin_publica_y_catalogo_es_publico(app, client):
    a = admin(app)
    assert subir_a_catalogo(a).status_code == 302
    html = app.test_client().get("/colecciones").get_data(as_text=True)
    assert "Blazer azul" in html and "$1,299.50" in html and "Centro" in html
    assert "Blazer azul" not in app.test_client().get("/colecciones?estacion=Verano").get_data(as_text=True)
    assert "Blazer azul" in app.test_client().get("/colecciones?estacion=Invierno&categoria=Abrigo").get_data(as_text=True)


def test_admin_valida_datos_y_foto(app):
    a = admin(app)
    subir_a_catalogo(a, precio="abc")
    subir_a_catalogo(a, enlace_compra="javascript:alert(1)")
    subir_a_catalogo(a, categoria="Otra")
    subir_a_catalogo(a, contenido=b"no soy una imagen")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(PrendaCatalogo.id))) == 0


def test_agregar_del_catalogo_copia_a_guardarropa_sin_duplicar(app, client):
    subir_a_catalogo(admin(app))
    with app.app_context():
        pid = db.session.scalar(db.select(PrendaCatalogo.id))
    iniciar_sesion(client, app, email="ana@example.com")
    client.post(f"/colecciones/agregar/{pid}")
    client.post(f"/colecciones/agregar/{pid}")
    with app.app_context():
        filas = db.session.scalars(db.select(Guardarropa)).all()
        assert len(filas) == 1 and filas[0].nombre == "Blazer azul" and filas[0].categoria == "Abrigo"


def test_agregar_requiere_login_y_prenda_retirada_no_se_agrega(app, client):
    a = admin(app)
    subir_a_catalogo(a)
    with app.app_context():
        pid = db.session.scalar(db.select(PrendaCatalogo.id))
    r = app.test_client().post(f"/colecciones/agregar/{pid}")
    assert r.status_code == 302 and "login" in r.headers["Location"]
    a.post(f"/admin/prenda/{pid}/alternar")
    assert "Blazer azul" not in app.test_client().get("/colecciones").get_data(as_text=True)
    iniciar_sesion(client, app, email="ana@example.com")
    client.post(f"/colecciones/agregar/{pid}")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Guardarropa.id))) == 0


def test_borrar_prenda_del_guardarropa_no_rompe_la_foto_del_catalogo(app, client, monkeypatch):
    subir_a_catalogo(admin(app))
    with app.app_context():
        pid = db.session.scalar(db.select(PrendaCatalogo.id))
    iniciar_sesion(client, app, email="ana@example.com")
    client.post(f"/colecciones/agregar/{pid}")
    borradas = []
    monkeypatch.setattr("routes.eliminar_imagen", lambda i: borradas.append(i))
    with app.app_context():
        gid = db.session.scalar(db.select(Guardarropa.id))
    client.post(f"/guardarropa/eliminar/{gid}")
    assert borradas == []


def test_eliminar_del_catalogo_conserva_foto_si_alguien_la_copio(app, client, monkeypatch):
    a = admin(app)
    subir_a_catalogo(a)
    with app.app_context():
        pid = db.session.scalar(db.select(PrendaCatalogo.id))
    iniciar_sesion(client, app, email="ana@example.com")
    client.post(f"/colecciones/agregar/{pid}")
    borradas = []
    monkeypatch.setattr("routes.eliminar_imagen", lambda i: borradas.append(i))
    a.post(f"/admin/prenda/{pid}/eliminar")
    assert borradas == []
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(PrendaCatalogo.id))) == 0
        assert db.session.scalar(db.select(db.func.count(Guardarropa.id))) == 1


def test_eliminar_del_catalogo_sin_copias_borra_la_foto(app):
    a = admin(app)
    subir_a_catalogo(a)
    with app.app_context():
        pid = db.session.scalar(db.select(PrendaCatalogo.id))
    assert len(os.listdir(app.config["CATALOGO_UPLOAD_FOLDER"])) == 1
    a.post(f"/admin/prenda/{pid}/eliminar")
    assert os.listdir(app.config["CATALOGO_UPLOAD_FOLDER"]) == []


def test_admin_edita_prenda(app):
    a = admin(app)
    subir_a_catalogo(a)
    with app.app_context():
        pid = db.session.scalar(db.select(PrendaCatalogo.id))
    a.post(f"/admin/prenda/{pid}/editar", data={**DATOS_PRENDA, "nombre": "Blazer negro", "precio": ""})
    with app.app_context():
        p = db.session.get(PrendaCatalogo, pid)
        assert p.nombre == "Blazer negro" and p.precio is None


def test_panel_muestra_resumen(app):
    a = admin(app)
    subir_a_catalogo(a)
    html = a.get("/admin").get_data(as_text=True)
    assert "Panel de administración" in html and "Blazer azul" in html


def test_catalogo_antiguo_redirige_a_colecciones(client):
    r = client.get("/catalogo?estacion=Invierno")
    assert r.status_code == 301 and r.headers["Location"].endswith("/colecciones?estacion=Invierno")


def test_filtro_de_estacion_acepta_minusculas_y_sin_acentos(app):
    subir_a_catalogo(admin(app), estacion="Otoño", nombre="Botines café")
    c = app.test_client()
    assert "Botines café" in c.get("/colecciones?estacion=otono").get_data(as_text=True)
    assert "Botines café" not in c.get("/colecciones?estacion=verano").get_data(as_text=True)


# ---------- Colecciones personalizadas ----------
def _base_de(app):
    with app.app_context():
        texto = db.session.scalar(db.select(TestResult.estacion))
    return next((e for e in ("Primavera", "Verano", "Otoño", "Invierno") if texto.startswith(e)), "Neutro")


def _subir_una_por_estacion(app):
    a = admin(app)
    for e in ("Primavera", "Verano", "Otoño", "Invierno", "Neutro"):
        subir_a_catalogo(a, estacion=e, nombre=f"Prenda {e}")


def test_colecciones_ordena_y_marca_lo_que_combina(app, client):
    _subir_una_por_estacion(app)
    usuario_con_test(client, app)
    base = _base_de(app)
    html = client.get("/colecciones").get_data(as_text=True)
    assert html.count("Combina contigo") == (2 if base != "Neutro" else 1)
    assert html.index(f"Prenda {base}") < min(
        html.index(f"Prenda {e}") for e in ("Primavera", "Verano", "Otoño", "Invierno") if e != base
    )


def test_filtro_para_mi_solo_muestra_mi_estacion_y_neutro(app, client):
    _subir_una_por_estacion(app)
    usuario_con_test(client, app)
    base = _base_de(app)
    html = client.get("/colecciones?para_mi=1").get_data(as_text=True)
    assert f"Prenda {base}" in html and "Prenda Neutro" in html
    otras = [e for e in ("Primavera", "Verano", "Otoño", "Invierno") if e != base]
    assert all(f"Prenda {e}" not in html for e in otras)


def test_colecciones_sin_test_invita_a_hacerlo_y_para_mi_se_ignora(app, client):
    _subir_una_por_estacion(app)
    iniciar_sesion(client, app, email="ana@example.com")
    html = client.get("/colecciones?para_mi=1").get_data(as_text=True)
    assert "test de colorimetría" in html and "Combina contigo" not in html
    assert all(f"Prenda {e}" in html for e in ("Primavera", "Verano", "Otoño", "Invierno"))


# ---------- Moderación ----------
def _reportar(app, pid, n, motivo="spam"):
    for i in range(n):
        otra_persona(app, f"rep{i}@example.com").post(f"/comunidad/reportar/{pid}", data={"motivo": motivo})


def test_moderacion_solo_para_admins(app, client):
    iniciar_sesion(client, app, email="ana@example.com")
    assert client.get("/admin/reportes").status_code == 404
    assert client.post("/admin/reportes/1/restaurar").status_code == 404
    assert client.post("/admin/reportes/1/eliminar").status_code == 404


def test_moderacion_lista_reportadas_con_motivos(app, client):
    pid = publicacion_de_ana(app, client)
    _reportar(app, pid, 3)
    html = admin(app).get("/admin/reportes").get_data(as_text=True)
    assert "3 reportes" in html and "oculta" in html and "Spam" in html or "spam" in html.lower()


def test_admin_restaura_publicacion_oculta(app, client):
    pid = publicacion_de_ana(app, client)
    _reportar(app, pid, 3)
    anonimo = app.test_client()
    assert anonimo.get(f"/p/{pid}").status_code == 404
    admin(app).post(f"/admin/reportes/{pid}/restaurar")
    assert anonimo.get(f"/p/{pid}").status_code == 200
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Reporte.id))) == 0


def test_admin_elimina_publicacion_reportada_y_su_foto(app, client):
    pid = publicacion_de_ana(app, client)
    _reportar(app, pid, 3)
    assert len(os.listdir(app.config["COMUNIDAD_UPLOAD_FOLDER"])) == 1
    admin(app).post(f"/admin/reportes/{pid}/eliminar")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Publicacion.id))) == 0
        assert db.session.scalar(db.select(db.func.count(Reporte.id))) == 0
    assert os.listdir(app.config["COMUNIDAD_UPLOAD_FOLDER"]) == []


def test_panel_cuenta_publicaciones_reportadas(app, client):
    pid = publicacion_de_ana(app, client)
    _reportar(app, pid, 1)
    html = admin(app).get("/admin").get_data(as_text=True)
    assert "Publicaciones reportadas" in html


# ---------- Privacidad y eliminar cuenta ----------
def test_aviso_de_privacidad_es_publico(client):
    r = client.get("/privacidad")
    assert r.status_code == 200 and "Aviso de privacidad" in r.get_data(as_text=True)


def test_eliminar_cuenta_requiere_contrasena_y_confirmacion(app, client):
    iniciar_sesion(client, app, email="ana@example.com")
    client.post("/cuenta/eliminar", data={"password": "mala", "confirmacion": "ELIMINAR"})
    client.post("/cuenta/eliminar", data={"password": "secreta123", "confirmacion": "si"})
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 1


def test_eliminar_cuenta_borra_todo_lo_suyo_y_conserva_lo_ajeno(app, client):
    pid = publicacion_de_ana(app, client)            # Ana publica
    luis = otra_persona(app, "luis@example.com")
    luis.post(f"/comunidad/like/{pid}")
    luis.post(f"/comunidad/republicar/{pid}")
    luis.post(f"/mensajes/1", data={"texto": "hola", "publicacion_id": pid})
    luis.post("/test", data=CALIDO)
    luis.post("/api/generar-diagnostico")
    luis.post("/comunidad/publicar", data={"foto": (io.BytesIO(PNG), "l.png")}, content_type="multipart/form-data")
    prenda_propia(app, email="ana@example.com")
    with app.app_context():
        ana_id = db.session.scalar(db.select(User.id).filter_by(email="ana@example.com"))
    r = client.post("/cuenta/eliminar", data={"password": "secreta123", "confirmacion": "eliminar"})
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(User, ana_id) is None
        assert db.session.scalar(db.select(db.func.count(Guardarropa.id))) == 0
        assert db.session.scalar(db.select(db.func.count(Like.id))) == 0
        assert db.session.scalar(db.select(db.func.count(TestResult.id))) == 1  # solo queda el de Luis
        # queda solo la publicación propia de Luis (su republicación de Ana se fue en cascada)
        assert db.session.scalar(db.select(db.func.count(Publicacion.id))) == 1
        assert db.session.scalar(db.select(User.id).filter_by(email="luis@example.com")) is not None
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == [] or all(
        not f.endswith(".png") for f in os.listdir(app.config["UPLOAD_FOLDER"]) if os.path.isfile(os.path.join(app.config["UPLOAD_FOLDER"], f))
    )
    assert client.get("/perfil").status_code == 302  # ya no tiene sesión


def test_mensajes_de_otros_no_se_rompen_al_borrar_una_publicacion_adjunta(app, client):
    pid = publicacion_de_ana(app, client)
    luis = otra_persona(app, "luis@example.com")
    with app.app_context():
        luis_id = db.session.scalar(db.select(User.id).filter_by(email="luis@example.com"))
    client.post(f"/mensajes/{luis_id}", data={"publicacion_id": pid, "texto": "mira"})
    client.post("/cuenta/eliminar", data={"password": "secreta123", "confirmacion": "ELIMINAR"})
    assert luis.get("/mensajes").status_code == 200


def test_guardarropa_separa_colecciones_de_prendas_anteriores(app, client):
    subir_a_catalogo(admin(app))
    with app.app_context():
        cid = db.session.scalar(db.select(PrendaCatalogo.id))
    iniciar_sesion(client, app, email="ana@example.com")
    client.post(f"/colecciones/agregar/{cid}")
    prenda_propia(app, nombre="Playera vieja")
    html = client.get("/guardarropa").get_data(as_text=True)
    assert "Blazer azul" in html and "Playera vieja" in html
    assert html.index("Blazer azul") < html.index("Mis prendas anteriores") < html.index("Playera vieja")
    with app.app_context():
        origenes = {p.nombre: p.origen for p in db.session.scalars(db.select(Guardarropa))}
    assert origenes == {"Blazer azul": "coleccion", "Playera vieja": "propia"}


def test_guardarropa_sin_prendas_invita_a_colecciones(app, client):
    iniciar_sesion(client, app)
    html = client.get("/guardarropa").get_data(as_text=True)
    assert "Colecciones" in html and "Mis prendas anteriores" not in html
