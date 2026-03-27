"""Entry point do servidor web — mapa interativo de concursos."""
import argparse
from app.server import iniciar_servidor

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ConcursosIA — Servidor do mapa")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"Mapa disponível em http://localhost:{args.port}")
    iniciar_servidor(host=args.host, port=args.port, debug=args.debug)
