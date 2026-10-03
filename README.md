# SET-MATCH-GO!

Asistente de moda con test de colorimetría. Flask + SQLAlchemy + PostgreSQL.

## Desarrollo local
```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                              # Windows: copy .env.example .env
python app.py                                     # usa SQLite si no hay DATABASE_URL
pytest                                            # pruebas
```

## Despliegue en Render
- **Build command:** `pip install -r requirements.txt && flask --app app init-db`
- **Start command:** `gunicorn "app:create_app()"`
- **Variables:** `APP_ENV=production`, `SECRET_KEY=<clave larga>`, `DATABASE_URL=<Internal URL de PostgreSQL>`
