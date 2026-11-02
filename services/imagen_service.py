"""Almacenamiento de imágenes.

Con CLOUDINARY_URL definida las imágenes se suben a Cloudinary (producción: el disco de
Render se borra en cada despliegue). Sin ella se guardan en static/uploads/ (solo desarrollo y pruebas).
"""
import os
import re
import uuid

from flask import current_app, url_for

FIRMAS_IMAGEN = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)
PREFIJO_LOCAL = "local:"
# Config que define la carpeta local (solo desarrollo y pruebas) de cada tipo de imagen
CLAVES_CARPETA = {"comunidad": "COMUNIDAD_UPLOAD_FOLDER", "guardarropa": "UPLOAD_FOLDER"}


def tipo_imagen(stream):
    """Detecta PNG/JPEG/WEBP por su contenido (no por el nombre que declara el usuario)."""
    cabecera = stream.read(12)
    stream.seek(0)
    for firma, ext in FIRMAS_IMAGEN:
        if cabecera.startswith(firma):
            return ext
    if cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP":
        return "webp"
    return None


def _carpeta_local(carpeta):
    configurada = current_app.config.get(CLAVES_CARPETA.get(carpeta, ""))
    return configurada or os.path.join(current_app.static_folder, "uploads", carpeta)


def id_desde_url(valor, carpeta="guardarropa"):
    """Devuelve el id interno para borrar una imagen a partir de lo que se guardó en la base de datos.

    Acepta una URL de Cloudinary, una ruta local (/static/uploads/...) o un nombre de archivo antiguo."""
    if not valor:
        return None
    if valor.startswith("http"):
        m = re.search(r"/upload/(?:v\d+/)?(.+)\.[A-Za-z0-9]+$", valor)
        return m.group(1) if m else None
    m = re.search(r"/static/uploads/([^/]+)/([^/]+)$", valor)
    if m:
        return f"{PREFIJO_LOCAL}{m.group(1)}/{m.group(2)}"
    return f"{PREFIJO_LOCAL}{carpeta}/{os.path.basename(valor)}"  # nombre de archivo de versiones anteriores


def cloudinary_activo():
    return bool(os.getenv("CLOUDINARY_URL"))


def subir_imagen(stream, ext, carpeta="comunidad"):
    """Sube la imagen y devuelve (url, id_interno). Lanza excepción si falla."""
    if cloudinary_activo():
        import cloudinary
        import cloudinary.uploader

        cloudinary.config(secure=True)  # lee CLOUDINARY_URL del entorno
        resultado = cloudinary.uploader.upload(
            stream,
            folder=f"set-match-go/{carpeta}",
            resource_type="image",
            allowed_formats=["png", "jpg", "jpeg", "webp"],
            transformation={"width": 1400, "height": 1400, "crop": "limit", "quality": "auto"},
        )
        return resultado["secure_url"], resultado["public_id"]

    destino = _carpeta_local(carpeta)
    os.makedirs(destino, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(destino, nombre), "wb") as f:
        f.write(stream.read())
    return url_for("static", filename=f"uploads/{carpeta}/{nombre}"), f"{PREFIJO_LOCAL}{carpeta}/{nombre}"


def eliminar_imagen(id_interno):
    """Borra la imagen. Nunca lanza: una imagen huérfana no debe romper el flujo."""
    if not id_interno:
        return
    try:
        if id_interno.startswith(PREFIJO_LOCAL):
            relativo = id_interno[len(PREFIJO_LOCAL):]
            carpeta, nombre = relativo.split("/", 1)
            base = _carpeta_local(carpeta)
            os.remove(os.path.join(base, os.path.basename(nombre)))
        elif cloudinary_activo():
            import cloudinary
            import cloudinary.uploader

            cloudinary.config(secure=True)
            cloudinary.uploader.destroy(id_interno, resource_type="image")
    except Exception as e:  # noqa: BLE001
        current_app.logger.warning(f"No se pudo borrar la imagen {id_interno}: {e}")
