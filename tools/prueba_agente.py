"""Prueba del reparto servidor/PC sin necesitar dos maquinas.

Levanta el agente en este mismo ordenador y comprueba lo que de verdad importa:
que una herramienta del PC se vaya por la red, que una del servidor NO se vaya,
y que la puerta no se abra sin la ficha correcta.
"""

import importlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

PUERTO = 8899
FICHA = "ficha-de-prueba-larga-y-dificil"

os.environ["BUDDY_AGENTE_PUERTO"] = str(PUERTO)
os.environ["BUDDY_AGENTE_FICHA"] = FICHA

import herramientas                                        # noqa: E402
import agente_pc                                           # noqa: E402

fallos = []


def comprobar(que, condicion, detalle=""):
    print(f"  {'OK  ' if condicion else 'MAL '} {que}{'  ' + detalle if detalle else ''}")
    if not condicion:
        fallos.append(que)


# ---- el agente, en un hilo ------------------------------------------------
from http.server import ThreadingHTTPServer                 # noqa: E402

servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), agente_pc.Recados)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
time.sleep(0.3)


def llamar(nombre, argumentos=None, ficha=FICHA):
    cuerpo = json.dumps({"herramienta": nombre, "argumentos": argumentos or {}}).encode()
    p = urllib.request.Request(f"http://127.0.0.1:{PUERTO}/ejecutar", data=cuerpo,
                               headers={"Content-Type": "application/json",
                                        "X-Ficha": ficha})
    try:
        with urllib.request.urlopen(p, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


print("\n== la puerta ==")
codigo, _ = llamar("que_hora_es", ficha="ficha-equivocada")
comprobar("sin la ficha correcta no entra", codigo == 403)

codigo, r = llamar("que_hora_es")
comprobar("una herramienta que NO es del PC se rechaza aunque traiga ficha",
          codigo == 403, str(r))

codigo, r = llamar("que_estoy_haciendo")
comprobar("una del PC con ficha correcta se ejecuta", codigo == 200,
          str(r.get("resultado", ""))[:60])

print("\n== el reparto ==")
# Ahora el "servidor": con BUDDY_AGENTE puesto, las del PC deben salir por red.
os.environ["BUDDY_AGENTE"] = f"http://127.0.0.1:{PUERTO}"
os.environ["BUDDY_AGENTE_FICHA"] = FICHA
importlib.reload(herramientas)

comprobar("el servidor sabe donde esta el agente", bool(herramientas.AGENTE))

salidas = []
original = herramientas._pedir_al_agente
herramientas._pedir_al_agente = lambda n, a: (salidas.append(n), original(n, a))[1]

herramientas.ejecutar("que_estoy_haciendo", {})
comprobar("una del PC viaja al agente", salidas == ["que_estoy_haciendo"], str(salidas))

salidas.clear()
hora = herramientas.ejecutar("que_hora_es", {})
comprobar("una del servidor se queda aqui", salidas == [], str(salidas))
comprobar("y devuelve algo con sentido", "hora" in hora.lower() or any(c.isdigit() for c in hora),
          hora[:50])

print("\n== cuando el PC no contesta ==")
os.environ["BUDDY_AGENTE"] = "http://127.0.0.1:9"      # puerto muerto
importlib.reload(herramientas)
respuesta = herramientas.ejecutar("ver_pantalla", {})
comprobar("se explica en vez de reventar",
          "no consigo hablar con tu ordenador" in respuesta, respuesta[:70])

servidor.shutdown()
print("\nRESULTADO:", "OK" if not fallos else f"MAL -> {fallos}")
