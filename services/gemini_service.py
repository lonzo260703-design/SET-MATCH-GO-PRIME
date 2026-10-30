import os
import time
from google import genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Configurable: GEMINI_MODELS="modelo1,modelo2" (se prueban en orden)
MODELOS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash"
    ).split(",")
    if m.strip()
]


def _obtener_cliente():
    if not GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[Gemini Service Error - Init]: {e}")
        return None


def _generar_respuesta_fallback(pregunta):
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


def _generar_con_retry(client, prompt):
    # Modelos de texto con límites combinados (5 RPM y 15 RPM)
    modelos = MODELOS

    for model in modelos:
        print(f"[Gemini Service]: Probando modelo '{model}'...")
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            if response and response.text:
                print(f"[Gemini Service]: Modelo '{model}' con éxito.")
                return response.text.strip()
        except Exception as e:
            print(f"[Gemini Service]: '{model}' no disponible/saturado: {e}")

    print("[Gemini Service]: Ningún modelo disponible. Entregando respuesta local (fallback).")
    return None


def generar_recomendacion_colorimetria(estacion, subtono, respuestas):
    client = _obtener_cliente()
    if not client:
        return (
            f"Tu paleta ideal corresponde a la estación **{estacion}** (Subtono {subtono}). "
            "Te recomendamos utilizar colores armónicos cerca de tu rostro para resaltar tu luminosidad natural."
        )

    prompt = f"""
Eres Stylist AI, una asesora de imagen profesional de SET-MATCH-GO!.
El usuario obtuvo los siguientes resultados en su test de colorimetría:
- Estación: {estacion}
- Subtono: {subtono}
- Respuestas: {respuestas}

Ofrece un diagnóstico breve (máximo 180 palabras) en formato Markdown con:
1. **Perfil Cromático**
2. **Prendas y Colores Clave**
3. **Outfit Sugerido**
"""
    resultado = _generar_con_retry(client, prompt)
    if resultado:
        return resultado

    return (
        f"Tu estación diagnóstica es **{estacion}** (Subtono {subtono}). "
        "Prioriza el uso de prendas en los colores principales de tu muestrario cerca de tu rostro para dar más luz a tu piel."
    )


def responder_chat_estilista(pregunta, contexto=None):
    client = _obtener_cliente()
    if not client:
        return _generar_respuesta_fallback(pregunta)

    contexto_txt = ""
    if contexto:
        contexto_txt = (
            f"Contexto de la usuaria/o: su resultado de colorimetría es {contexto.get('estacion', '')} "
            f"(subtono {contexto.get('subtono', '')}). Personaliza el consejo a esa paleta.\n"
        )
    prompt = f"""
Eres la Estilista Virtual oficial de SET-MATCH-GO!, experta en moda y teoría del color.
{contexto_txt}Responde a la siguiente consulta de manera clara, amable y concisa (máximo 3 oraciones):

"{pregunta}"
"""
    resultado = _generar_con_retry(client, prompt)
    if resultado:
        return resultado

    return _generar_respuesta_fallback(pregunta)