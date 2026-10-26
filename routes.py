import re
from urllib.parse import urljoin, urlparse

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from colorimetria import PERFILES, RespuestasInvalidas, clasificar
from extensions import db
from extensions import csrf  # O la forma en que instancies csrf_protect en tu app
from models import TestResult, User
from services.email_service import (
    enviar_correo_confirmacion,
    enviar_correo_recuperacion,
    verificar_token,
)
from services.gemini_service import generar_recomendacion_colorimetria, responder_chat_estilista

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LIMITE_PREGUNTAS_INVITADO = 3


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

    # ---------- COLECCIONES ----------
    @app.route("/colecciones")
    def colecciones():
        estacion = request.args.get("estacion")
        return render_template("colecciones.html", estacion=estacion)

    # ---------- TEORÍA Y HERRAMIENTAS DE COLOR ----------
    @app.route("/colorwheel")
    def colorwheel():
        return render_template("colorwheel.html")

    # ---------- AUTENTICACIÓN Y RECUPERACIÓN ----------
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
                usuario = User(nombre=nombre, email=email, is_confirmed=False)
                usuario.set_password(password)
                db.session.add(usuario)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    errores.append("Ya existe una cuenta con ese correo.")
                else:
                    try:
                        enviar_correo_confirmacion(usuario.email, usuario.nombre)
                        flash(
                            f"¡Cuenta creada con éxito, {usuario.nombre}! Revisa tu correo para activar tu cuenta antes de iniciar sesión.",
                            "info",
                        )
                    except Exception:
                        flash(
                            "Tu cuenta fue creada, pero ocurrió un problema al enviar el correo de verificación.",
                            "warning",
                        )

                    return redirect(url_for("login"))

            for e in errores:
                flash(e, "error")
            return render_template("auth.html", modo="register", nombre=nombre, email=email), 400

        return render_template("auth.html", modo="register")

    @app.route("/confirmar/<token>")
    def confirmar_cuenta(token):
        email = verificar_token(token, salt="email-confirm-salt", max_age=86400)
        if not email:
            flash("El enlace de confirmación es inválido o ha expirado.", "error")
            return redirect(url_for("login"))

        usuario = db.session.scalar(select(User).filter_by(email=email))
        if usuario:
            if usuario.is_confirmed:
                flash("Tu cuenta ya había sido confirmada previamente.", "info")
            else:
                usuario.is_confirmed = True
                db.session.commit()
                flash("¡Tu cuenta ha sido activada con éxito!", "success")

        return redirect(url_for("index"))

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
                return render_template("auth.html", modo="login", email=email, next_url=next_url), 401

            if not usuario.is_confirmed:
                flash("Por favor, confirma tu correo electrónico antes de iniciar sesión.", "warning")
                return render_template("auth.html", modo="login", email=email, next_url=next_url), 403

            login_user(usuario)
            flash(f"Hola de nuevo, {usuario.nombre}.", "success")
            return redirect(next_url if _url_segura(next_url) else url_for("index"))

        return render_template("auth.html", modo="login", next_url=next_url)

    @app.route("/olvide-password", methods=["GET", "POST"])
    def olvide_password():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            usuario = db.session.scalar(select(User).filter_by(email=email))
            if usuario:
                try:
                    enviar_correo_recuperacion(usuario.email, usuario.nombre)
                except Exception:
                    flash("Ocurrió un error al intentar enviar el correo de recuperación.", "error")
                    return redirect(url_for("olvide_password"))

            flash(
                "Si el correo está registrado, recibirás un enlace de recuperación en tu bandeja de entrada.",
                "info",
            )
            return redirect(url_for("login"))

        return render_template("olvide_password.html")

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def resetear_password(token):
        email = verificar_token(token, salt="password-reset-salt", max_age=900)
        if not email:
            flash("El enlace para restablecer la contraseña es inválido o ha expirado.", "error")
            return redirect(url_for("login"))

        if request.method == "POST":
            password = request.form.get("password", "")
            confirmar = request.form.get("confirmar", "")

            if len(password) < 8 or password != confirmar:
                flash("Las contraseñas deben tener al menos 8 caracteres y coincidir.", "error")
                return render_template("reset_password.html", token=token)

            usuario = db.session.scalar(select(User).filter_by(email=email))
            if usuario:
                usuario.set_password(password)
                db.session.commit()
                flash("Tu contraseña ha sido actualizada correctamente.", "success")
                return redirect(url_for("login"))

        return render_template("reset_password.html", token=token)

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        session.pop("ultimo_resultado", None)
        flash("Cerraste sesión correctamente.", "success")
        return redirect(url_for("index"))

    # ---------- PERFIL DE USUARIO Y CONFIGURACIÓN ----------
    @app.route("/perfil", methods=["GET", "POST"])
    @login_required
    def perfil():
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            color_ojos = request.form.get("color_ojos", "").strip()
            color_cabello = request.form.get("color_cabello", "").strip()
            biografia = request.form.get("biografia", "").strip()

            if 2 <= len(nombre) <= 80:
                current_user.nombre = nombre
                current_user.color_ojos = color_ojos
                current_user.color_cabello = color_cabello
                current_user.biografia = biografia

                db.session.commit()
                flash("Perfil actualizado correctamente.", "success")
                return redirect(url_for("perfil"))
            else:
                flash("El nombre debe tener entre 2 y 80 caracteres.", "error")

        return render_template("perfil.html")

    # ---------- TEST DE COLORIMETRÍA ----------
    @app.route("/test", methods=["GET", "POST"])
    def test():
        if request.method == "POST":
            try:
                # 1. Procesar respuestas reales del formulario p1..p7 con colorimetria.py
                resultado = clasificar(request.form)
                
                # 2. Guardar el diagnóstico inmediatamente en la sesión
                session["ultimo_resultado"] = resultado
                session.modified = True
                
                # 3. Mostrar la pantalla con la animación del orbe
                return render_template("procesando.html")
            except RespuestasInvalidas as e:
                flash(str(e), "error")
                return redirect(url_for("test"))

        return render_template("test.html")

    @app.route("/resultado")
    def resultado():
        datos = session.get("ultimo_resultado")
        if not datos:
            flash("Primero realiza el test de colorimetría.", "info")
            return redirect(url_for("test"))

        # Si aún no hemos generado la recomendación personalizada con Gemini IA, la creamos aquí
        if "recomendacion_ia" not in datos:
            try:
                recomendacion_ia = generar_recomendacion_colorimetria(
                    datos.get("estacion", "Verano"),
                    datos.get("subtono", "frio"),
                    datos.get("respuestas", {})
                )
                datos["recomendacion_ia"] = recomendacion_ia
            except Exception as e:
                print(f"Error llamando a Gemini IA: {e}")
                datos["recomendacion_ia"] = (
                    "Tu paleta ha sido procesada exitosamente. "
                    "Te recomendamos favorecer las prendas que potencien el contraste y la temperatura natural de tu rostro."
                )

            # Persistir los datos completos en la sesión
            session["ultimo_resultado"] = datos
            session.modified = True

            # Si el usuario inició sesión, guardar en el historial de la base de datos
            if current_user.is_authenticated:
                try:
                    db.session.add(
                        TestResult(
                            user_id=current_user.id,
                            respuestas=datos.get("respuestas", {}),
                            subtono=datos.get("subtono", ""),
                            estacion=datos.get("estacion", ""),
                        )
                    )
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()

        return render_template(
            "resultado.html",
            estacion=datos.get("estacion", ""),
            subtono=datos.get("subtono", ""),
            descripcion=datos.get("descripcion", ""),
            paleta=datos.get("paleta", []),
            recomendacion_ia=datos.get("recomendacion_ia", ""),
        )

    @app.route("/api/generar-diagnostico", methods=["POST"])
    def generar_diagnostico_api():
        datos_pendientes = session.get("pendiente_ia")
        if not datos_pendientes:
            return jsonify({"success": False, "error": "No hay test pendiente"}), 400

        # Llamar a Gemini IA en segundo plano mientras corre el orbe
        try:
            recomendacion = generar_recomendacion_colorimetria(
                datos_pendientes.get("estacion", "Verano"),
                datos_pendientes.get("subtono", "Frío"),
                datos_pendientes.get("respuestas", {})
            )
            datos_pendientes["recomendacion_ia"] = recomendacion
        except Exception as e:
            print(f"Error generando con Gemini: {e}")
            datos_pendientes["recomendacion_ia"] = (
                "Para tu paleta de Verano Frío, prioriza tonos pasteles deslavados como azul sereno, "
                "rosa cuarzo y lavanda. Combínalos con acentos neutros en gris marengo o blanco roto."
            )

        # Mover los datos a la sesión final
        session["ultimo_resultado"] = datos_pendientes
        session.pop("pendiente_ia", None)
        session.modified = True

        # Guardar en base de datos si el usuario inició sesión
        if current_user.is_authenticated:
            try:
                db.session.add(
                    TestResult(
                        user_id=current_user.id,
                        respuestas=datos_pendientes.get("respuestas", {}),
                        subtono=datos_pendientes.get("subtono", ""),
                        estacion=datos_pendientes.get("estacion", ""),
                    )
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()

        return jsonify({"success": True})

    # ---------- API CHAT FLOTANTE DE IA ----------
    @app.route("/api/chat-ia", methods=["POST"])
    @csrf.exempt  # <--- EVITA EL REDIRECCIONAMIENTO 302
    def chat_ia():
        data = request.get_json() or {}
        pregunta = data.get("pregunta", "").strip()

        if not pregunta:
            return jsonify({"error": "La pregunta no puede estar vacía"}), 400

        if not current_user.is_authenticated:
            preguntas_realizadas = session.get("preguntas_ia_count", 0)

            if preguntas_realizadas >= LIMITE_PREGUNTAS_INVITADO:
                return jsonify({
                    "limite_alcanzado": True,
                    "mensaje": f"Has alcanzado el límite de {LIMITE_PREGUNTAS_INVITADO} consultas gratuitas. ¡Inicia sesión para chatear sin restricciones!"
                }), 403

            session["preguntas_ia_count"] = preguntas_realizadas + 1

        respuesta = responder_chat_estilista(pregunta)

        preguntas_restantes = None
        if not current_user.is_authenticated:
            preguntas_restantes = LIMITE_PREGUNTAS_INVITADO - session["preguntas_ia_count"]

        return jsonify({
            "respuesta": respuesta,
            "preguntas_restantes": preguntas_restantes,
            "limite_alcanzado": False
        })
    
    # ---------- HISTORIAL ----------
    @app.route("/historial")
    @login_required
    def historial():
        resultados = current_user.resultados.all()
        return render_template("historial.html", resultados=resultados, perfiles=PERFILES)

    @app.route("/historial/eliminar/<int:id>", methods=["POST"])
    @login_required
    def eliminar_historial(id):
        resultado = db.session.scalar(
            select(TestResult).filter_by(id=id, user_id=current_user.id)
        )
        if resultado:
            db.session.delete(resultado)
            db.session.commit()
            flash("Registro eliminado del historial.", "success")
        return redirect(url_for("historial"))