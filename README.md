# SET-MATCH-GO! — Asesoría Inteligente & Moda

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.0+-black?style=flat-square&logo=flask)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-blue?style=flat-square&logo=postgresql)
![Gemini AI](https://img.shields.io/badge/Gemini_AI-Google-orange?style=flat-square&logo=google)
![Deployment](https://img.shields.io/badge/Render-Deployed-brightgreen?style=flat-square&logo=render)

**SET-MATCH-GO!** es una plataforma web e interactiva de asesoría de imagen y estilismo personal. Ayuda a los usuarios a descubrir su paleta cromática ideal mediante un test de colorimetría basado en estaciones, interactuar con un **Estilista IA**, gestionar un **Guardarropa Digital** y explorar combinaciones cromáticas en tiempo real.

---

## Características Principales

* **Test de Colorimetría Interactivo:** Algoritmo que clasifica la paleta personal según la teoría de las 4 estaciones (Primavera, Verano, Otoño, Invierno).
* **Estilista IA (Google Gemini):** Chatbot inteligente entrenado para brindar consejos de estilismo, combinaciones y etiquetas de outfit según la estación del usuario.
* **Guardarropa Digital:** Permite a los usuarios registrados subir, categorizar y gestionar sus prendas personales.
* **Rueda de Armonías & Probador Virtual:** Herramienta visual interactiva con maniquíes estilizados para probar armonías complementarias, análogas y triádicas en tiempo real.
* **Autenticación & Seguridad:** Registro/Login con verificación por correo electrónico (Flask-Mail), hashing seguro de contraseñas (Werkzeug) y protección CSRF.
* **Diseño Responsive & Cyber Glassmorphism:** Interfaz moderna adaptada a dispositivos móviles y de escritorio.

---

## Tecnologías Utilizadas

* **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF, Flask-Mail.
* **Frontend:** HTML5, CSS3 (Glassmorphism, CSS Grid/Flexbox), JavaScript ES6+ (Canvas de partículas, ScrollSpy).
* **IA / Integraciones:** API Google Gemini AI.
* **Base de Datos:** SQLite (Desarrollo local) / PostgreSQL (Producción).
* **Servidor de Producción:** Gunicorn.

---
