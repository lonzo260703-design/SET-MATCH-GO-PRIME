import os
from google import genai

# Reemplaza 'TU_NUEVA_API_KEY' por la clave recién creada en un proyecto nuevo
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

def _obtener_cliente():
    """Inicializa el cliente oficial de Gemini."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "":
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[Gemini Service Error - Init]: {e}")
        return None


def _generar_respuesta_fallback(pregunta):
    """Respuesta contextual si el servicio de IA no está disponible."""
    p = pregunta.lower()

    if any(k in p for k in ["frio", "frío", "invierno", "chamarra", "abrigo", "suéter"]):
        return (
            "Para climas fríos, te recomiendo un look en capas: usa una camiseta térmica o suéter de cuello alto, "
            "combinado con un abrigo estructurado o gabardina en tonos neutros (gris, azul marino o camel) "
            "y botas o calzado cerrado de piel."
        )
    elif any(k in p for k in ["cálido", "calido", "calor", "verano", "playa"]):
        return (
            "Para climas cálidos, elige prendas ligeras en lino o algodón fresco. Un pantalón ancho en tono beige "
            "o falda fluida junto con una camisa blanca o de tono pastel crearán un outfit elegante y fresco."
        )
    elif any(k in p for k in ["entrevista", "formal", "trabajo", "oficina"]):
        return (
            "Para un entorno profesional, opta por un blazer neutro (azul o marengo), camisa o blusa lisa, "
            "pantalón de vestir o falda a la rodilla y calzado cerrado clásico."
        )
    else:
        return (
            "Para armar un excelente outfit, la clave está en equilibrar una prenda neutra (como pantalón o falda "
            "en beige/negro/marino) con un toque de color en prendas superiores o accesorios que resalten tu piel."
        )


def generar_recomendacion_colorimetria(estacion, subtono, respuestas):
    """Genera un análisis de vestuario para la vista de resultados."""
    client = _obtener_cliente()
    if not client:
        return (
            f"Tu paleta ideal corresponde a la estación **{estacion}** (Subtono {subtono}). "
            "Te recomendamos utilizar colores armónicos cerca de tu rostro para resaltar tu luminosidad natural."
        )

    try:
        prompt = f"""
Eres Stylist AI, una asesora de imagen profesional de SET-MATCH-GO!.
El usuario obtuvo los siguientes resultados en su test de colorimetría:
- Estación: {estacion}
- Subtono: {subtono}
- Respuestas: {respuestas}

Ofrece un diagnóstico breve (máximo 180 palabras) en Markdown con:
1. **Perfil Cromático**
2. **Prendas y Colores Clave**
3. **Outfit Sugerido**
"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        print(f"[Gemini Service Error - Colorimetría]: {e}")
        return (
            f"Tu estación diagnóstica es **{estacion}** (Subtono {subtono}). "
            "Prioriza el uso de prendas en los colores principales de tu muestrario cerca de tu rostro."
        )


def responder_chat_estilista(pregunta):
    """Responde consultas en el widget del chat flotante."""
    client = _obtener_cliente()

    if not client:
        return _generar_respuesta_fallback(pregunta)

    try:
        prompt = f"""
Eres la Estilista Virtual oficial de SET-MATCH-GO!, experta en moda y teoría del color.
Responde a la siguiente consulta de manera clara, amable y concisa (máximo 3 oraciones):

"{pregunta}"
"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        print(f"[Gemini Service Error - Chat Detail]: {e}")
        return _generar_respuesta_fallback(pregunta)