import os
import sys

# Repo root en sys.path para importar `app` sin instalar el paquete
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
