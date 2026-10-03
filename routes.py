import re
from urllib.parse import urljoin, urlparse

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from colorimetria import PERFILES, RespuestasInvalidas, clasificar
from extensions import db
from models import TestResult, User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _url_segura(destino):
    """Evita open-redirect: solo se aceptan destinos dentro del mismo sitio."""
    if not destino:
        return False
    base = urlparse(request.host_url)
    objetivo = urlparse(urljoin(request.host_url, destino))
    return objetivo.scheme in ("http", "https") and base.netloc == objetivo.netloc


def register_routes(app):
    @app.route("/")
    def index():
        return render_template("index.html")

    # ---------- AUTENTICACIÓN ----------
    @app.route("/registro", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirmar = request.form.get("confirmar", "")

            errores = []
            if not 2 <= len(nombre) <= 80:
                errores.append("El nombre debe tener entre 2 y 80 caracteres.")
            if not EMAIL_RE.match(email) or len(email) > 120:
                errores.append("Ingresa un correo electrónico válido.")
            if len(password) < 8:
                errores.append("La contraseña debe tener al menos 8 caracteres.")
            if password != confirmar:
                errores.append("Las contraseñas no coinciden.")
            if not errores and db.session.scalar(select(User).filter_by(email=email)):
                errores.append("Ya existe una cuenta con ese correo.")

            if not errores:
                usuario = User(nombre=nombre, email=email)
                usuario.set_password(password)
                db.session.add(usuario)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    errores.append("Ya existe una cuenta con ese correo.")
                else:
                    login_user(usuario)
                    flash(f"¡Bienvenida/o, {usuario.nombre}! Tu cuenta fue creada.", "success")
                    return redirect(url_for("index"))

            for e in errores:
                flash(e, "error")
            return render_template("register.html", nombre=nombre, email=email), 400

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        next_url = request.values.get("next", "")

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            usuario = db.session.scalar(select(User).filter_by(email=email))

            if usuario is None or not usuario.check_password(password):
                flash("Correo o contraseña incorrectos.", "error")
                return render_template("login.html", email=email, next_url=next_url), 401

            login_user(usuario)
            flash(f"Hola de nuevo, {usuario.nombre}.", "success")
            return redirect(next_url if _url_segura(next_url) else url_for("index"))

        return render_template("login.html", next_url=next_url)

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        session.pop("ultimo_resultado", None)
        flash("Cerraste sesión correctamente.", "success")
        return redirect(url_for("index"))

    # ---------- TEST DE COLORIMETRÍA ----------
    @app.route("/test", methods=["GET", "POST"])
    def test():
        if request.method == "POST":
            try:
                resultado = clasificar(request.form)
            except RespuestasInvalidas as e:
                flash(str(e), "error")
                return redirect(url_for("test"))

            session["ultimo_resultado"] = resultado
            if current_user.is_authenticated:
                db.session.add(
                    TestResult(
                        user_id=current_user.id,
                        respuestas=resultado["respuestas"],
                        subtono=resultado["subtono"],
                        estacion=resultado["estacion"],
                    )
                )
                db.session.commit()
            return redirect(url_for("resultado"))  # POST -> redirect -> GET

        return render_template("test.html")

    @app.route("/resultado")
    def resultado():
        datos = session.get("ultimo_resultado")
        if not datos:
            flash("Primero realiza el test de colorimetría.", "info")
            return redirect(url_for("test"))
        return render_template(
            "resultado.html",
            estacion=datos["estacion"],
            descripcion=datos["descripcion"],
            paleta=datos["paleta"],
        )

    @app.route("/historial")
    @login_required
    def historial():
        resultados = current_user.resultados.all()
        return render_template("historial.html", resultados=resultados, perfiles=PERFILES)
