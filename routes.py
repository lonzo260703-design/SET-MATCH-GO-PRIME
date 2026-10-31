import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from colorimetria import PERFILES, RespuestasInvalidas, clasificar, paleta_de_estacion
from extensions import db, limiter
from models import Guardarropa, Like, Publicacion, Reporte, TestResult, User
from services.email_service import (
    enviar_correo_confirmacion,
    enviar_correo_recuperacion,
    huella_password,
    verificar_token,
    verificar_token_reset,
)
from services.gemini_service import generar_recomendacion_colorimetria, responder_chat_estilista
from services.imagen_service import eliminar_imagen, subir_imagen, tipo_imagen

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LIMITE_PREGUNTAS_INVITADO = 3
MAX_PREGUNTA = 500
MAX_DESCRIPCION = 500
UMBRAL_REPORTES = 3  # reportes de personas distintas para ocultar una publicación del feed
MOTIVOS_REPORTE = {
    "inapropiado": "Contenido inapropiado",
    "spam": "Spam",
    "no_outfit": "No es un outfit",
    "otro": "Otro",
}
CATEGORIAS = {'Superior', 'Inferior', 'Abrigo', 'Calzado', 'Accesorios'}


def _url_segura(destino):
    """Evita open-redirect: solo se aceptan destinos dentro del mismo sitio."""
    if not destino:
        return False
    base = urlparse(request.host_url)
    objetivo = urlparse(urljoin(request.host_url, destino))
    return objetivo.scheme in ("http", "https") and base.netloc == objetivo.netloc


def _completar_diagnostico(datos):
    """Genera la recomendación de IA (con respaldo local), la guarda en sesión y, si hay
    usuario autenticado, persiste el resultado. Idempotente: si ya existe, no repite."""
    if "recomendacion_ia" in datos:
        return datos

    try:
        datos["recomendacion_ia"] = generar_recomendacion_colorimetria(
            datos.get("estacion", ""), datos.get("subtono", ""), datos.get("respuestas", {})
        )
    except Exception as e:
        current_app.logger.error(f"Error llamando a Gemini IA: {e}")
        datos["recomendacion_ia"] = (
            "Tu paleta ha sido procesada exitosamente. Te recomendamos favorecer las prendas "
            "que potencien el contraste y la temperatura natural de tu rostro."
        )

    session["ultimo_resultado"] = datos
    session.modified = True

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
        except Exception:
            db.session.rollback()
    return datos


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
    @limiter.limit("10 per hour", methods=["POST"])
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
                    if current_app.debug and not current_app.config.get("MAIL_USERNAME"):
                        # Desarrollo sin SMTP configurado: se confirma la cuenta para poder probar
                        usuario.is_confirmed = True
                        db.session.commit()
                        current_app.logger.warning("MAIL_USERNAME no configurado: cuenta confirmada automáticamente (solo desarrollo).")
                        flash(f"¡Cuenta creada, {usuario.nombre}! (modo desarrollo: ya puedes iniciar sesión)", "info")
                    else:
                        try:
                            enviar_correo_confirmacion(usuario.email, usuario.nombre)
                            flash(
                                f"¡Cuenta creada con éxito, {usuario.nombre}! Revisa tu correo (y la carpeta de spam) para activar tu cuenta antes de iniciar sesión.",
                                "info",
                            )
                        except Exception as e:
                            current_app.logger.error(f"No se pudo enviar el correo de confirmación a {usuario.email}: {e}")
                            flash(
                                "Tu cuenta fue creada, pero no pudimos enviar el correo de verificación. "
                                "Intenta iniciar sesión y usa «Reenviar correo de confirmación».",
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
    @limiter.limit("10 per 15 minutes", methods=["POST"])
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
                return render_template("auth.html", modo="login", email=email, next_url=next_url, sin_confirmar=True), 403

            login_user(usuario)
            flash(f"Hola de nuevo, {usuario.nombre}.", "success")
            return redirect(next_url if _url_segura(next_url) else url_for("index"))

        return render_template("auth.html", modo="login", next_url=next_url)

    @app.route("/reenviar-confirmacion", methods=["POST"])
    @limiter.limit("5 per hour")
    def reenviar_confirmacion():
        email = request.form.get("email", "").strip().lower()
        usuario = db.session.scalar(select(User).filter_by(email=email)) if email else None
        if usuario and not usuario.is_confirmed:
            try:
                enviar_correo_confirmacion(usuario.email, usuario.nombre)
            except Exception as e:
                current_app.logger.error(f"No se pudo reenviar la confirmación a {usuario.email}: {e}")
        # Respuesta uniforme para no revelar qué correos existen
        flash("Si la cuenta existe y está pendiente, te enviamos un nuevo correo de confirmación.", "info")
        return redirect(url_for("login"))

    # ---------- RECUPERACIÓN DE CONTRASEÑA ----------
    @app.route("/forgot-password", methods=["GET", "POST"])
    @limiter.limit("5 per hour", methods=["POST"])
    def forgot_password():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            identity = request.form.get("identity", "").strip()

            if identity:
                # Solo por correo: el nombre no es único y permitiría mandar correos a terceros
                usuario = db.session.scalar(select(User).filter_by(email=identity.lower()))

                if usuario:
                    try:
                        enviar_correo_recuperacion(usuario)
                    except Exception as e:
                        current_app.logger.error(f"Error al enviar correo de recuperación: {e}")

            # Respuesta uniforme por seguridad para evitar enumeración de usuarios
            flash(
                "Si la cuenta existe en nuestro sistema, recibirás un enlace de recuperación en tu correo electrónico.",
                "info",
            )
            return redirect(url_for("login"))

        return render_template("forgot_password.html")

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    @limiter.limit("10 per hour", methods=["POST"])
    def resetear_password(token):
        email, huella = verificar_token_reset(token)
        usuario = db.session.scalar(select(User).filter_by(email=email)) if email else None
        if not usuario or huella != huella_password(usuario):
            flash("El enlace para restablecer la contraseña es inválido, ya se usó o ha expirado.", "error")
            return redirect(url_for("login"))

        if request.method == "POST":
            password = request.form.get("password", "")
            confirmar = request.form.get("confirmar", "")

            if len(password) < 8 or password != confirmar:
                flash("Las contraseñas deben tener al menos 8 caracteres y coincidir.", "error")
                return render_template("reset_password.html", token=token), 400

            usuario.set_password(password)  # cambia la huella: el enlace ya no sirve
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
                resultado = clasificar(request.form)
                session["ultimo_resultado"] = resultado
                session.modified = True
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

        datos = _completar_diagnostico(datos)

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
        datos = session.get("ultimo_resultado")
        if not datos:
            return jsonify({"success": False, "error": "No hay test pendiente"}), 400

        _completar_diagnostico(datos)
        return jsonify({"success": True})

    # ---------- API CHAT FLOTANTE DE IA ----------
    @app.route("/api/chat-ia", methods=["POST"])
    @limiter.limit(lambda: "30 per hour" if current_user.is_authenticated else "10 per day")
    def chat_ia():
        data = request.get_json(silent=True) or {}
        pregunta = str(data.get("pregunta", "")).strip()[:MAX_PREGUNTA]

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

        respuesta = responder_chat_estilista(pregunta, session.get("ultimo_resultado"))

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

    # ---------- GUARDARROPA ----------
    @app.route('/guardarropa')
    @login_required
    def guardarropa():
        prendas = Guardarropa.query.filter_by(usuario_id=current_user.id).order_by(Guardarropa.fecha_creacion.desc()).all()
        return render_template('guardarropa.html', prendas=prendas)

    @app.route('/guardarropa/subir', methods=['POST'])
    @login_required
    def subir_prenda():
        if 'foto' not in request.files:
            flash('No se seleccionó ningún archivo.', 'error')
            return redirect(url_for('guardarropa'))

        file = request.files['foto']
        nombre = request.form.get('nombre', '').strip()
        categoria = request.form.get('categoria', 'Superior')

        if not file or file.filename == '':
            flash('Debes seleccionar una imagen.', 'error')
            return redirect(url_for('guardarropa'))

        if not nombre:
            flash('Debes ingresar un nombre para la prenda.', 'error')
            return redirect(url_for('guardarropa'))

        ext = tipo_imagen(file.stream)
        if ext:
            filename = f"{current_user.id}_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}.{ext}"

            upload_dir = current_app.config['UPLOAD_FOLDER']
            os.makedirs(upload_dir, exist_ok=True)
            file.save(os.path.join(upload_dir, filename))

            nueva_prenda = Guardarropa(
                usuario_id=current_user.id,
                nombre=nombre[:100],
                categoria=categoria if categoria in CATEGORIAS else 'Superior',
                imagen=filename
            )
            db.session.add(nueva_prenda)
            db.session.commit()

            flash('¡Prenda guardada en tu guardarropa!', 'success')
        else:
            flash('El archivo no es una imagen válida (PNG, JPG o WEBP).', 'error')

        return redirect(url_for('guardarropa'))

    @app.route("/guardarropa/eliminar/<int:id>", methods=["POST"])
    @login_required
    def eliminar_prenda(id):
        prenda = db.session.scalar(select(Guardarropa).filter_by(id=id, usuario_id=current_user.id))
        if not prenda:
            flash("Prenda no encontrada.", "error")
            return redirect(url_for("guardarropa"))

        ruta = os.path.join(current_app.config["UPLOAD_FOLDER"], prenda.imagen)
        db.session.delete(prenda)
        db.session.commit()
        try:
            os.remove(ruta)
        except OSError:
            pass
        flash("Prenda eliminada.", "success")
        return redirect(url_for("guardarropa"))

    # ---------- COMUNIDAD (RED SOCIAL DE ESTILO) ----------
    def _ids_ocultos():
        """Publicaciones con reportes de al menos UMBRAL_REPORTES personas distintas."""
        return (
            select(Reporte.publicacion_id)
            .group_by(Reporte.publicacion_id)
            .having(func.count(Reporte.usuario_id) >= UMBRAL_REPORTES)
        )

    @app.route("/comunidad")
    def comunidad():
        pagina = request.args.get("pagina", 1, type=int)
        consulta = select(Publicacion)
        if current_user.is_authenticated:
            # Las publicaciones ocultas por reportes solo las ve su autora o autor
            consulta = consulta.where(
                Publicacion.id.not_in(_ids_ocultos()) | (Publicacion.usuario_id == current_user.id)
            )
        else:
            consulta = consulta.where(Publicacion.id.not_in(_ids_ocultos()))
        publicaciones = db.paginate(
            consulta.order_by(Publicacion.created_at.desc(), Publicacion.id.desc()),
            page=pagina,
            per_page=9,
            error_out=False,
        )

        ids = [p.id for p in publicaciones.items]
        likes_por_pub, mis_likes, mis_reportes, en_revision = {}, set(), set(), set()
        if ids:
            likes_por_pub = dict(
                db.session.execute(
                    select(Like.publicacion_id, func.count(Like.id))
                    .where(Like.publicacion_id.in_(ids))
                    .group_by(Like.publicacion_id)
                ).all()
            )
            en_revision = set(
                db.session.scalars(select(Reporte.publicacion_id).where(Reporte.publicacion_id.in_(ids))
                                   .group_by(Reporte.publicacion_id)
                                   .having(func.count(Reporte.usuario_id) >= UMBRAL_REPORTES)).all()
            )
            if current_user.is_authenticated:
                mis_likes = set(
                    db.session.scalars(
                        select(Like.publicacion_id).where(
                            Like.usuario_id == current_user.id, Like.publicacion_id.in_(ids)
                        )
                    ).all()
                )
                mis_reportes = set(
                    db.session.scalars(
                        select(Reporte.publicacion_id).where(
                            Reporte.usuario_id == current_user.id, Reporte.publicacion_id.in_(ids)
                        )
                    ).all()
                )

        ultimo_resultado = current_user.resultados.first() if current_user.is_authenticated else None
        return render_template(
            "comunidad.html",
            publicaciones=publicaciones,
            ultimo_resultado=ultimo_resultado,
            likes_por_pub=likes_por_pub,
            mis_likes=mis_likes,
            mis_reportes=mis_reportes,
            en_revision=en_revision,
            motivos=MOTIVOS_REPORTE,
        )

    @app.route("/comunidad/publicar", methods=["POST"])
    @login_required
    @limiter.limit("10 per hour")
    def publicar_outfit():
        ultimo = current_user.resultados.first()
        if not ultimo:
            flash("Haz primero el test de colorimetría para poder publicar tu outfit.", "info")
            return redirect(url_for("test"))

        archivo = request.files.get("foto")
        descripcion = request.form.get("descripcion", "").strip()[:MAX_DESCRIPCION]

        if not archivo or archivo.filename == "":
            flash("Selecciona la foto de tu outfit.", "error")
            return redirect(url_for("comunidad"))

        ext = tipo_imagen(archivo.stream)
        if not ext:
            flash("El archivo no es una imagen válida (PNG, JPG o WEBP).", "error")
            return redirect(url_for("comunidad"))

        try:
            url, imagen_id = subir_imagen(archivo.stream, ext, "comunidad")
        except Exception as e:
            current_app.logger.error(f"Error al subir imagen de comunidad: {e}")
            flash("No pudimos subir tu foto. Inténtalo de nuevo en un momento.", "error")
            return redirect(url_for("comunidad"))

        try:
            db.session.add(
                Publicacion(
                    usuario_id=current_user.id,
                    imagen_url=url,
                    imagen_id=imagen_id,
                    descripcion=descripcion or None,
                    estacion=ultimo.estacion,
                    subtono=ultimo.subtono,
                    paleta=paleta_de_estacion(ultimo.estacion),
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            eliminar_imagen(imagen_id)
            flash("No pudimos guardar tu publicación. Inténtalo de nuevo.", "error")
            return redirect(url_for("comunidad"))

        flash("¡Tu outfit ya está en la comunidad!", "success")
        return redirect(url_for("comunidad"))

    @app.route("/comunidad/eliminar/<int:id>", methods=["POST"])
    @login_required
    def eliminar_publicacion(id):
        publicacion = db.session.scalar(select(Publicacion).filter_by(id=id, usuario_id=current_user.id))
        if not publicacion:
            flash("Publicación no encontrada.", "error")
            return redirect(url_for("comunidad"))

        imagen_id = publicacion.imagen_id
        db.session.delete(publicacion)
        db.session.commit()
        eliminar_imagen(imagen_id)
        flash("Publicación eliminada.", "success")
        return redirect(url_for("comunidad"))

    @app.route("/comunidad/like/<int:id>", methods=["POST"])
    @login_required
    @limiter.limit("120 per hour")
    def toggle_like(id):
        publicacion = db.session.get(Publicacion, id)
        if not publicacion:
            return jsonify({"error": "Publicación no encontrada"}), 404

        existente = db.session.scalar(select(Like).filter_by(publicacion_id=id, usuario_id=current_user.id))
        if existente:
            db.session.delete(existente)
            le_gusta = False
        else:
            db.session.add(Like(publicacion_id=id, usuario_id=current_user.id))
            le_gusta = True
        try:
            db.session.commit()
        except IntegrityError:  # doble clic simultáneo: el like ya existía
            db.session.rollback()
            le_gusta = True

        total = db.session.scalar(select(func.count(Like.id)).where(Like.publicacion_id == id))
        return jsonify({"liked": le_gusta, "total": total})

    @app.route("/comunidad/reportar/<int:id>", methods=["POST"])
    @login_required
    @limiter.limit("20 per hour")
    def reportar_publicacion(id):
        publicacion = db.session.get(Publicacion, id)
        motivo = request.form.get("motivo", "")
        if not publicacion:
            flash("Publicación no encontrada.", "error")
        elif publicacion.usuario_id == current_user.id:
            flash("No puedes reportar tu propia publicación.", "error")
        elif motivo not in MOTIVOS_REPORTE:
            flash("Elige un motivo para el reporte.", "error")
        else:
            try:
                db.session.add(Reporte(publicacion_id=id, usuario_id=current_user.id, motivo=motivo))
                db.session.commit()
                flash("Gracias, recibimos tu reporte.", "success")
            except IntegrityError:
                db.session.rollback()
                flash("Ya habías reportado esta publicación.", "info")
        return redirect(request.referrer if request.referrer and _url_segura(request.referrer) else url_for("comunidad"))

