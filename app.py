import os

import click
from flask import Flask, flash, redirect, url_for
from flask_wtf.csrf import CSRFError

from config import DEFAULT_SECRET, config_by_name
from extensions import csrf, db, login_manager


def create_app(config_name=None):
    config_name = config_name or os.getenv("APP_ENV", "development")
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    if config_name == "production" and app.config["SECRET_KEY"] == DEFAULT_SECRET:
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
        return db.session.get(User, int(user_id))

    @app.errorhandler(CSRFError)
    def csrf_error(_e):
        flash("Tu sesión del formulario expiró. Inténtalo de nuevo.", "error")
        return redirect(url_for("index"))

    from routes import register_routes

    register_routes(app)

    @app.cli.command("init-db")
    def init_db():
        """Crea las tablas en la base de datos configurada."""
        db.create_all()
        click.echo("Tablas creadas.")

    if app.config["AUTO_CREATE_DB"]:
        with app.app_context():
            db.create_all()

    return app


if __name__ == "__main__":
    create_app().run(debug=os.getenv("FLASK_DEBUG", "1") == "1")
