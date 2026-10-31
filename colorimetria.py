"""Lógica del test de colorimetría (sin dependencias de Flask)."""

PREGUNTAS = ("p1", "p2", "p3", "p4", "p5", "p6", "p7")

# Valores permitidos según la entrada de cada pregunta
VALORES_VALIDOS = {
    "p1": {"frio", "calido", "neutro"},
    "p2": {"frio", "calido", "neutro"},
    "p3": {"frio", "calido", "neutro"},
    "p4": {"frio", "calido"},
    "p5": {"frio", "calido"},
    "p6": {"frio", "calido"},
    "p7": {"alto", "suave"}
}

# Perfiles detallados por estación según la evaluación de subtono y contraste
PERFILES = {
    "Primavera": {
        "estacion": "Primavera (Subtono Cálido - Contraste Suave)",
        "descripcion": (
            "Tu piel tiene un matiz dorado o durazno y tus rasgos guardan una armonía suave. "
            "Te favorecen los tonos cálidos, brillantes y luminosos como el coral, verde menta, "
            "amarillo claro y tonos pastel cálidos."
        ),
        "paleta": ["#F59E0B", "#10B981", "#F43F5E", "#FBBF24"],
    },
    "Otoño": {
        "estacion": "Otoño (Subtono Cálido - Contraste Alto)",
        "descripcion": (
            "Tus matices son profundamente cálidos y contrastados. Te benefician las gamas "
            "tierra, terracota, mostaza, verde oliva, café profundo y accesorios dorados."
        ),
        "paleta": ["#D97706", "#B45309", "#78350F", "#047857"],
    },
    "Verano": {
        "estacion": "Verano (Subtono Frío - Contraste Suave)",
        "descripcion": (
            "Tienes un subtono frío con rasgos suaves y delicados. Luces genial con "
            "colores suaves y acartonados como el azul pastel, lila, rosa palo, lavanda y gris perla."
        ),
        "paleta": ["#60A5FA", "#C084FC", "#9CA3AF", "#F472B6"],
    },
    "Invierno": {
        "estacion": "Invierno (Subtono Frío - Contraste Alto)",
        "descripcion": (
            "Destacas por un marcado contraste entre tu piel, ojos y cabello con subtono frío. "
            "Tus mejores aliados son los colores intensos e icónicos como el blanco puro, negro, "
            "rojo rubí, azul marino y fucsia."
        ),
        "paleta": ["#1E3A8A", "#831843", "#0F172A", "#BE123C"],
    },
    "Neutro": {
        "estacion": "Paleta Neutra Equilibrada",
        "descripcion": (
            "Cuentas con un balance muy armonioso entre matices fríos y cálidos. Puedes "
            "experimentar con versatilidad en casi cualquier gama de contraste medio."
        ),
        "paleta": ["#059669", "#DC2626", "#2563EB", "#D97706"],
    },
}


def paleta_de_estacion(texto_estacion):
    """Devuelve la paleta de colores asociada al texto de estación guardado en un resultado."""
    for perfil in PERFILES.values():
        if perfil["estacion"] == texto_estacion:
            return list(perfil["paleta"])
    return []


class RespuestasInvalidas(ValueError):
    """Faltan respuestas o contienen valores no permitidos."""


def clasificar(form):
    """Recibe un mapeo (request.form o dict) con p1..p7 y devuelve el resultado."""
    respuestas = {}
    for clave in PREGUNTAS:
        valor = (form.get(clave) or "").strip()
        
        # Validar presencia y validez de la opción ingresada
        if not valor or valor not in VALORES_VALIDOS.get(clave, set()):
            raise RespuestasInvalidas("Responde todas las preguntas para obtener tu diagnóstico.")
        respuestas[clave] = valor

    # Mapeo de votos para determinar subtono (p1 a p6)
    votos_calidos = sum(1 for k in ("p1", "p2", "p3", "p4", "p5", "p6") if respuestas[k] == "calido")
    votos_frios = sum(1 for k in ("p1", "p2", "p3", "p4", "p5", "p6") if respuestas[k] == "frio")

    contraste = respuestas["p7"]  # 'alto' o 'suave'

    # Evaluación de la Estación
    if votos_calidos > votos_frios:
        subtono = "calido"
        estacion_clave = "Otoño" if contraste == "alto" else "Primavera"
    elif votos_frios > votos_calidos:
        subtono = "frio"
        estacion_clave = "Invierno" if contraste == "alto" else "Verano"
    else:
        subtono = "neutro"
        estacion_clave = "Neutro"

    perfil = PERFILES[estacion_clave]

    return {
        "subtono": subtono,
        "estacion": perfil["estacion"],
        "descripcion": perfil["descripcion"],
        "paleta": list(perfil["paleta"]),
        "respuestas": respuestas,
    }