"""Prueba del transporte de red sin la placa: un ESP32 de mentira.

Comprueba lo que de verdad importa: que la cara pueda irse y volver sin que el
servidor se entere, que es lo que va a pasar cada vez que se reinicie o se
quede sin WiFi un momento.
"""
import socket, threading, time
import cara as C
from cara import Cara

PUERTO = 8899
recibido = []

def esp32_falso(etiqueta, cuantas):
    s = socket.create_connection(("127.0.0.1", PUERTO), timeout=3)
    s.settimeout(3)
    resto = b""
    leidas = 0
    while leidas < cuantas:
        try:
            trozo = s.recv(256)
        except socket.timeout:
            break
        if not trozo:
            break
        resto += trozo
        while b"\n" in resto:
            linea, resto = resto.split(b"\n", 1)
            recibido.append((etiqueta, linea.decode().strip()))
            leidas += 1
    s.sendall(b"C T\n")          # un toque de vuelta
    s.close()

cara = Cara(str(PUERTO))
time.sleep(0.3)

# --- primera cara ---
h = threading.Thread(target=esp32_falso, args=("cara1", 3)); h.start()
time.sleep(0.4)
cara.estado(C.HABLANDO); cara.emocion(C.FELIZ); cara.boca(70)
h.join(4)

# --- se va y vuelve otra (reinicio de la placa) ---
time.sleep(0.4)
h = threading.Thread(target=esp32_falso, args=("cara2", 2)); h.start()
time.sleep(0.4)
cara.estado(C.ESCUCHANDO); cara.nivel(55)
h.join(4)

# --- sin nadie conectado: no debe petar ---
time.sleep(0.5)
cara.estado(C.REPOSO); cara.boca(0)
print("sin cara conectada: no ha petado")

cara.cerrar()
print("\nrecibido:")
for e, l in recibido:
    print(f"  {e}: {l!r}")

esperado = [("cara1","E H"),("cara1","M F"),("cara1","B 70"),
            ("cara2","E L"),("cara2","N 55")]
print("\nRESULTADO:", "OK" if recibido == esperado else f"MAL, esperaba {esperado}")
