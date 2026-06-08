import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
load_dotenv()

def main():
    print("=== TEST DE CONFIGURACIÓN Y CONECTIVIDAD DE GEMINI ===")
    
    # 1. Verificar Variables de Entorno
    api_key = os.environ.get("GEMINI_API_KEY")
    project_id = os.environ.get("GCP_PROJECT_ID")
    
    print(f"GCP_PROJECT_ID: {project_id}")
    
    if not api_key:
        print("\n[!] ERROR: La variable de entorno GEMINI_API_KEY no está configurada.")
        print("    Por favor, abre el archivo '.env' y coloca tu clave de API, o bien configúrala en tu sistema.")
        sys.exit(1)
    
    masked_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "clave corta inválida"
    print(f"GEMINI_API_KEY: Detectada ({masked_key})")
    
    # 2. Inicializar SDK de Google GenAI
    print("\nInicializando SDK google-genai...")
    try:
        from google import genai
    except ImportError:
        print("[!] ERROR: No se pudo importar 'google.genai'. ¿Está instalado el paquete 'google-genai'?")
        sys.exit(1)
        
    try:
        # Se inicializa el cliente con la clave cargada del .env
        client = genai.Client(api_key=api_key)
        
        # 3. Llamar al modelo de prueba
        print("Llamando al modelo 'gemini-2.5-flash' con un prompt de prueba...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Responde únicamente con el siguiente texto: "Conexión a Gemini exitosa. ¡Todo listo!"'
        )
        
        print("\n=== RESPUESTA OBTENIDA ===")
        print(response.text.strip())
        print("==========================\n")
        print("[+] ¡El test se ha completado con éxito! Tu API key y el SDK están funcionando correctamente.")
        
    except Exception as e:
        print("\n[!] OCURRIÓ UN ERROR AL LLAMAR A LA API:")
        print(e)
        sys.exit(1)

if __name__ == "__main__":
    main()
