"""Lógica del test de colorimetría (sin dependencias de Flask)."""

PREGUNTAS = ("p1", "p2", "p3")
VALORES_VALIDOS = {"frio", "calido", "neutro"}

PERFILES = {
    "calido": {
        "estacion": "Otoño / Primavera (Subtono Cálido)",
        "descripcion": (
            "Tus tonos dorados y venas verdosas indican que te favorecen las gamas "
            "tierra, mostaza, terracota y dorados."
        ),
        "paleta": ["#D97706", "#B45309", "#78350F", "#F59E0B"],
    },
    "frio": {
        "estacion": "Invierno / Verano (Subtono Frío)",
        "descripcion": (
            "Tus rasgos destacan con colores joya, azul marino, borgoña, blanco puro, "
            "negro y accesorios plateados."
        ),
        "paleta": ["#1E3A8A", "#831843", "#0F172A", "#6B21A8"],
    },
    "neutro": {
        "estacion": "Paleta Neutra",
        "descripcion": (
            "Tienes un balance armónico entre tonos fríos y cálidos. Puedes "
            "experimentar con casi cualquier color de contraste medio."
        ),
        "paleta": ["#059669", "#DC2626", "#2563EB", "#D97706"],
    },
}


class RespuestasInvalidas(ValueError):
    """Faltan respuestas o contienen valores no permitidos."""


def clasificar(form):
    """Recibe un mapeo (request.form o dict) con p1..p3 y devuelve el resultado."""
    respuestas = {}
    for clave in PREGUNTAS:
        valor = (form.get(clave) or "").strip()
        if valor not in VALORES_VALIDOS:
            raise RespuestasInvalidas("Responde todas las preguntas para obtener tu diagnóstico.")
        respuestas[clave] = valor

    valores = list(respuestas.values())
    calido, frio = valores.count("calido"), valores.count("frio")

    if calido > frio:
        subtono = "calido"
    elif frio > calido:
        subtono = "frio"
    else:
        subtono = "neutro"

    perfil = PERFILES[subtono]
    return {
        "subtono": subtono,
        "estacion": perfil["estacion"],
        "descripcion": perfil["descripcion"],
        "paleta": list(perfil["paleta"]),
        "respuestas": respuestas,
    }
