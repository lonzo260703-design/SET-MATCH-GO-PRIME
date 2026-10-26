import os
from google import genai
from google.genai import types

# Obtiene la clave cargada desde el .env
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

SYSTEM_INSTRUCTION = """
Eres la Asistente Virtual y Estilista Inteligente de la marca "SET-MATCH-GO!".
Tu objetivo es dar consejos sobre moda, teoría del color, combinación de prendas y estilo personal.
Sé siempre amable, concisa, elegante y entusiasta.
Proporciona respuestas cortas (máximo 2 párrafos) y directas a la duda del usuario.
"""

def generar_recomendacion_colorimetria(estacion, subtono, respuestas):
    """Genera recomendaciones de ropa tras completar el test."""
    if not client:
        return f"Tu estación ideal es {estacion}. Te favorecen los tonos armónicos con tu subtono {subtono}."

    prompt = f"""
    Un usuario realizó el test de colorimetría en SET-MATCH-GO! con estos resultados:
    - Estación calculada: {estacion}
    - Subtono: {subtono}
    - Respuestas: {respuestas}

    Escribe un breve análisis (2 párrafos pequeños):
    1. Explicación de por qué le benefician ciertos colores.
    2. Da 3 combinaciones de ropa específicas (ej. "Blazer azul marino con camisa blanca").
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7
            )
        )
        return response.text
    except Exception as e:
        return f"Tu estación ideal es {estacion}. Te favorecen los tonos armónicos con tu subtono {subtono}."

def responder_chat_estilista(pregunta_usuario):
    """Responde preguntas en el chat flotante de la web."""
    if not client:
        return "Servicio de IA no configurado."

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=pregunta_usuario,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7
            )
        )
        return response.text
    except Exception as e:
        return "Lo siento, en este momento no pude procesar tu consulta. Intenta de nuevo en un momento."