from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import JSONB
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db

# JSONB en PostgreSQL, JSON genérico en SQLite (desarrollo / pruebas)
JSON_TYPE = db.JSON().with_variant(JSONB(), "postgresql")


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    resultados = db.relationship(
        "TestResult",
        backref="usuario",
        order_by="TestResult.created_at.desc()",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class TestResult(db.Model):
    __test__ = False  # evita que pytest lo intente recolectar como prueba
    __tablename__ = "test_results"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    respuestas = db.Column(JSON_TYPE, nullable=False)
    subtono = db.Column(db.String(10), nullable=False)  # calido | frio | neutro
    estacion = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
