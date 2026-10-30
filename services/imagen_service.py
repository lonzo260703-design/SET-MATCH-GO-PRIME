"""Almacenamiento de imágenes.

Con CLOUDINARY_URL definida las imágenes se suben a Cloudinary (producción: el disco de
Render se borra en cada despliegue). Sin ella se guardan en static/uploads/ (solo desarrollo y pruebas).
"""
import os
import uuid

from flask import current_app, url_for

FIRMAS_IMAGEN = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)
PREFIJO_LOCAL = "local:"


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

    destino = current_app.config.get("COMUNIDAD_UPLOAD_FOLDER") or os.path.join(
        current_app.static_folder, "uploads", carpeta
    )
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
            base = current_app.config.get("COMUNIDAD_UPLOAD_FOLDER") or os.path.join(
                current_app.static_folder, "uploads", carpeta
            )
            os.remove(os.path.join(base, os.path.basename(nombre)))
        elif cloudinary_activo():
            import cloudinary
            import cloudinary.uploader

            cloudinary.config(secure=True)
            cloudinary.uploader.destroy(id_interno, resource_type="image")
    except Exception as e:  # noqa: BLE001
        current_app.logger.warning(f"No se pudo borrar la imagen {id_interno}: {e}")
