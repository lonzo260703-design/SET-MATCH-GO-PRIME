# services/email_service.py
from flask import current_app, render_template_string, url_for
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer
from extensions import mail

def generar_token(email, salt):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return serializer.dumps(email, salt=salt)

def verificar_token(token, salt, max_age=86400):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = serializer.loads(token, salt=salt, max_age=max_age)
        return email
    except Exception:
        return None

def enviar_correo_confirmacion(user_email, user_nombre):
    token = generar_token(user_email, salt="email-confirm-salt")
    url_confirmacion = url_for("confirmar_cuenta", token=token, _external=True)

    msg = Message("Confirma tu cuenta — SET-MATCH-GO!", recipients=[user_email])
    msg.html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
      <h2 style="color: #2c3e50; text-align: center;">¡Bienvenido/a, {user_nombre}!</h2>
      <p style="color: #555;">Gracias por registrarte en <strong>SET-MATCH-GO!</strong>. Para activar tu cuenta y acceder a todas las funciones de IA y diagnósticos, confirma tu correo electrónico haciéndolo en el siguiente botón:</p>
      <div style="text-align: center; margin: 25px 0;">
        <a href="{url_confirmacion}" style="background-color: #e74c3c; color: white; padding: 12px 25px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Confirmar mi Cuenta</a>
      </div>
      <p style="color: #888; font-size: 0.8rem; text-align: center;">Si no creaste esta cuenta, puedes ignorar este mensaje.</p>
    </div>
    """
    mail.send(msg)

def enviar_correo_recuperacion(user_email, user_nombre):
    token = generar_token(user_email, salt="password-reset-salt")
    url_reset = url_for("resetear_password", token=token, _external=True)

    msg = Message("Restablecer Contraseña — SET-MATCH-GO!", recipients=[user_email])
    msg.html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
      <h2 style="color: #2c3e50; text-align: center;">Recuperación de Contraseña</h2>
      <p style="color: #555;">Hola {user_nombre}, recibimos una solicitud para restablecer tu contraseña. Haz clic en el botón de abajo para ingresar una nueva contraseña (este enlace expira en 15 minutos):</p>
      <div style="text-align: center; margin: 25px 0;">
        <a href="{url_reset}" style="background-color: #2c3e50; color: white; padding: 12px 25px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Restablecer Contraseña</a>
      </div>
      <p style="color: #888; font-size: 0.8rem; text-align: center;">Si no solicitaste este cambio, tu cuenta sigue segura.</p>
    </div>
    """
    mail.send(msg)