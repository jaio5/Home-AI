"""El agente: las manos del companero dentro de este ordenador.

El cerebro vive en el servidor Ubuntu y desde alli no puede ver tu pantalla, ni
tocar tu volumen, ni abrir tus juegos. Esto se queda corriendo en el Windows y
hace esos recados cuando se los piden.

    servidor Ubuntu  ──POST /ejecutar──▶  agente_pc.py  ──▶  tu PC
        (cerebro)                         (este archivo)

Uso:
    set BUDDY_AGENTE_FICHA=<una cadena larga>     (en Windows)
    python agente_pc.py

Y en el servidor, la misma ficha y donde esta este agente:
    export BUDDY_AGENTE=http://192.168.3.16:8788
    export BUDDY_AGENTE_FICHA=<la misma cadena larga>


Esto abre una puerta en tu ordenador por la que entran ordenes. Cuatro
decisiones que la estrechan todo lo que se puede:

  - Sin ficha no arranca. Nada de "ya le pondre una contrasena luego": si la
    variable esta vacia, el programa se niega a empezar. Una puerta abierta y
    olvidada en la red de casa es exactamente lo que no queremos.

  - Solo la lista de herramientas.EN_EL_PC, y nada mas. No hay forma de mandar
    un comando, ni una ruta, ni un trozo de codigo: solo se puede pedir una de
    esas por su nombre. Aunque alguien se cuele, no hay "ejecuta esto".

  - Solo responde a quien traiga la ficha correcta, comparada de forma que no
    se pueda adivinar letra a letra por el tiempo que tarda en contestar.

  - Se queda en la red local. Ni se te ocurra abrirle un puerto en el router.
    Si algun dia el servidor esta fuera de casa, eso se hace por VPN.
"""

import hmac
import json
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sistema

sistema.cargar_ajustes()        # antes de herramientas, que ya lee el entorno

import herramientas             # noqa: E402

PUERTO = int(os.environ.get("BUDDY_AGENTE_PUERTO", "8788"))
FICHA = os.environ.get("BUDDY_AGENTE_FICHA", "")
MAXIMO = 64 * 1024              # ninguna peticion legitima se acerca ni de lejos


class Recados(BaseHTTPRequestHandler):
    server_version = "buddy-agente"

    def _responder(self, codigo, datos):
        crudo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def do_POST(self):
        if self.path.rstrip("/") != "/ejecutar":
            return self._responder(404, {"error": "no existe"})

        # compare_digest y no ==: comparar cadenas normalmente corta en la
        # primera letra distinta, y con eso se puede sacar la ficha letra a
        # letra midiendo lo que tarda en contestar.
        if not hmac.compare_digest(self.headers.get("X-Ficha", ""), FICHA):
            print(f"[agente] rechazado, ficha incorrecta desde {self.client_address[0]}")
            return self._responder(403, {"error": "ficha incorrecta"})

        try:
            largo = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._responder(400, {"error": "longitud invalida"})
        if largo <= 0 or largo > MAXIMO:
            return self._responder(400, {"error": "cuerpo fuera de medida"})

        try:
            peticion = json.loads(self.rfile.read(largo))
            nombre = peticion["herramienta"]
            argumentos = peticion.get("argumentos") or {}
        except Exception as e:
            return self._responder(400, {"error": f"no entiendo la peticion: {e}"})

        if nombre not in herramientas.EN_EL_PC:
            print(f"[agente] rechazado, '{nombre}' no esta en la lista")
            return self._responder(403, {"error": f"'{nombre}' no se hace aqui"})

        print(f"[agente] {nombre}({', '.join(f'{k}={v!r}' for k, v in argumentos.items())})")
        # ejecutar_local y no ejecutar: si no, al tener BUDDY_AGENTE puesto en
        # esta misma maquina se reenviaria a si mismo dando vueltas.
        resultado = herramientas.ejecutar_local(nombre, argumentos)
        self._responder(200, {"resultado": resultado})

    def do_GET(self):
        """Para comprobar a mano que llega. No dice nada util sin la ficha."""
        if self.path.rstrip("/") == "/vivo":
            return self._responder(200, {"vivo": True})
        return self._responder(404, {"error": "no existe"})

    def log_message(self, *_):
        pass                    # ya se imprime lo que interesa, y con sentido


def mi_ip():
    """La IP por la que se llega a este equipo desde la red de casa."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 1))      # no sale ningun paquete; solo elige ruta
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")

    if not FICHA:
        sys.exit(
            "Falta la ficha. Sin ella esto seria una puerta abierta en la red "
            "de casa, asi que no arranca.\n\n"
            "  Windows:  set BUDDY_AGENTE_FICHA=lo-que-sea-largo-y-dificil\n"
            "  Linux:    export BUDDY_AGENTE_FICHA=lo-que-sea-largo-y-dificil\n\n"
            "Tiene que ser la MISMA cadena en el PC y en el servidor.\n"
            "Para inventarte una:  python -c \"import secrets;print(secrets.token_urlsafe(32))\"")

    print(f"[agente] manos del companero en este PC, puerto {PUERTO}")
    print(f"[agente] en el servidor:  export BUDDY_AGENTE=http://{mi_ip()}:{PUERTO}")
    print(f"[agente] puede hacer: {', '.join(sorted(herramientas.EN_EL_PC))}")

    # El modelo de vision tarda mas de 20 s en cargarse la primera vez. Si esa
    # primera vez es cuando le preguntas que ve en la pantalla, la conversacion
    # se queda muerta esperando. Cargarlo ahora, con una imagen minuscula, lo
    # deja en 2-4 s el resto del rato.
    print("[agente] calentando el modelo de vision...")
    try:
        herramientas.precalentar_vision()
        print("[agente] listo")
    except Exception as e:
        print(f"[agente] no he podido precalentarlo ({str(e)[:60]}); "
              f"la primera mirada ira lenta")

    print("[agente] Ctrl+C para parar.")

    servidor = ThreadingHTTPServer(("0.0.0.0", PUERTO), Recados)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[agente] hasta luego")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
