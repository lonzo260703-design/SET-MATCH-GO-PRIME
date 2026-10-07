import os

import click
from flask import Flask, flash, redirect, request, url_for
from flask_wtf.csrf import CSRFError

from config import DEFAULT_SECRET, config_by_name
from extensions import csrf, db, login_manager


def create_app(config_name=None):
    config_name = config_name or os.getenv("APP_ENV", "development")
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    if config_name == "production" and app.config.get("SECRET_KEY") == DEFAULT_SECRET:
        raise RuntimeError("Define la variable de entorno SECRET_KEY en producción.")

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Inicia sesión para acceder a esa página."
    login_manager.login_message_category = "warning"

    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        flash("Tu sesión del formulario expiró o el token no es válido. Inténtalo de nuevo.", "error")
        # Redirige a la página desde donde venía el usuario, o al inicio si no se detecta referrer
        return redirect(request.referrer or url_for("index"))

    from routes import register_routes

    register_routes(app)

    @app.cli.command("init-db")
    def init_db():
        """Crea las tablas en la base de datos configurada."""
        db.create_all()
        click.echo("Tablas creadas con éxito.")

    if app.config.get("AUTO_CREATE_DB", False):
        with app.app_context():
            try:
                db.create_all()
            except Exception as e:
                app.logger.error(f"Error al crear automáticamente la base de datos: {e}")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=os.getenv("FLASK_DEBUG", "1") == "1")