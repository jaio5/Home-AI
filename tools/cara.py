"""La cara: el unico sitio desde donde se le habla a la pantalla.

Protocolo, una linea por mensaje:
    E R|L|P|H    estado: Reposo, escuchando, Pensando, Hablando
    M N|F|S|T|E  emocion: Neutro, Feliz, Sorpresa, Triste, Enfadado
    B 0..100     apertura de la boca
    N 0..100     nivel del microfono, para que reaccione mientras le hablas

La pantalla devuelve "C T" cuando le tocan la cara.

Hay dos caminos y el de arriba es identico por los dos:

  - Cable USB. Lo de siempre, y lo mejor mientras desarrollas.
  - Red. Aqui mandamos NOSOTROS el papel raro: el servidor ESCUCHA y es el
    ESP32 quien llama. Asi la placa puede coger la IP que le de el router sin
    que nadie la apunte, y cuando reinicias el servidor vuelve a llamar ella
    sola. Al reves habria que perseguirle la IP cada vez.

Con la red, la cara puede estar en cualquier sitio de la casa y el cerebro en
un servidor Ubuntu.
"""

import socket
import threading
import time

REPOSO, ESCUCHANDO, PENSANDO, HABLANDO = "R", "L", "P", "H"
NEUTRO, FELIZ, SORPRESA, TRISTE, ENFADADO = "N", "F", "S", "T", "E"

PUERTO_RED = 8787


# ============================== transportes =================================

class _Serie:
    """Por el cable USB."""

    def __init__(self, puerto, baudios=115200):
        import serial                     # solo si de verdad se usa el cable
        self.ser = serial.Serial(puerto, baudios, timeout=0.1)
        self.ser.dtr = True
        time.sleep(0.3)
        self.donde = puerto

    def escribir(self, linea):
        self.ser.write((linea + "\n").encode())

    def cerrar(self):
        self.ser.close()


class _Red:
    """Escucha y espera a que la cara llame.

    Acepta una cara cada vez. Si se va y vuelve (se reinicia, se queda sin WiFi)
    la siguiente conexion sustituye a la anterior sin que nadie se entere.
    """

    def __init__(self, puerto=PUERTO_RED):
        self.puerto = puerto
        self.donde = f"puerto {puerto}"
        self._cliente = None
        self._cerrando = False

        self._oreja = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._oreja.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._oreja.bind(("0.0.0.0", puerto))
        self._oreja.listen(1)

        threading.Thread(target=self._aceptar, daemon=True).start()

    def _aceptar(self):
        while not self._cerrando:
            try:
                sock, origen = self._oreja.accept()
            except OSError:
                return
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # Escribir NUNCA puede bloquear la conversacion: ver escribir().
            sock.settimeout(0.25)
            anterior, self._cliente = self._cliente, sock
            if anterior:
                try:
                    anterior.close()
                except OSError:
                    pass
            print(f"[cara] conectada desde {origen[0]}")
            threading.Thread(target=self._vaciar, args=(sock,), daemon=True).start()

    def _vaciar(self, sock):
        """Lee y tira lo que manda la cara (ahora mismo, solo el toque).

        Aunque no lo usemos hay que leerlo: si nadie vacia lo que llega, el
        buffer del sistema se llena y acaba atascando el sentido contrario, que
        es el que de verdad importa.
        """
        while not self._cerrando:
            try:
                if not sock.recv(256):
                    break
            except socket.timeout:
                continue
            except OSError:
                break
        if self._cliente is sock:
            self._cliente = None
            print("[cara] se ha ido")

    def escribir(self, linea):
        sock = self._cliente
        if not sock:
            return
        try:
            sock.sendall((linea + "\n").encode())
        except socket.timeout:
            # La boca manda unos 30 mensajes por segundo y son de usar y tirar:
            # perder uno no se ve. Quedarse esperando a una cara atascada si se
            # oye, porque frena el hilo que esta reproduciendo la voz.
            pass
        except OSError:
            self._cliente = None
            raise

    def cerrar(self):
        self._cerrando = True
        for s in (self._cliente, self._oreja):
            if s:
                try:
                    s.close()
                except OSError:
                    pass


def _elegir(destino):
    """Cable o red, mirando que pinta tiene lo que nos han dado.

    "COM3", "/dev/ttyACM0"  -> cable
    "red", "8787", ":8787"  -> red
    """
    texto = str(destino).strip()
    if texto.lower() in ("red", "wifi", "") or texto.lstrip(":").isdigit():
        puerto = int(texto.lstrip(":")) if texto.lstrip(":").isdigit() else PUERTO_RED
        return _Red(puerto)
    return _Serie(texto)


# ================================= cara =====================================

class Cara:
    """Lo unico que ve el resto del programa. Por dentro da igual el camino."""

    def __init__(self, destino="red"):
        self.canal = None
        self._fallo_avisado = False
        try:
            self.canal = _elegir(destino)
            print(f"[cara] escuchando en {self.canal.donde}"
                  if isinstance(self.canal, _Red)
                  else f"[cara] conectada a {self.canal.donde}")
        except Exception as e:
            print(f"[cara] sin pantalla ({e}); sigo solo con voz")

    def _manda(self, linea):
        if not self.canal:
            return
        try:
            self.canal.escribir(linea)
        except Exception as e:
            # Un cable que se suelta a media conversacion no puede pasar
            # desapercibido, pero tampoco llenar la consola en cada fotograma.
            if not self._fallo_avisado:
                print(f"[cara] se ha perdido la conexion ({e})")
                self._fallo_avisado = True
            if isinstance(self.canal, _Serie):
                self.canal = None          # el cable no vuelve solo; la red si

    def estado(self, e):
        self._manda(f"E {e}")

    def emocion(self, m):
        self._manda(f"M {m}")

    def boca(self, apertura):
        self._manda(f"B {int(min(100, max(0, apertura)))}")

    def nivel(self, v):
        """Lo alto que esta hablando quien tiene delante, de 0 a 100."""
        self._manda(f"N {int(min(100, max(0, v)))}")

    def cerrar(self):
        if self.canal:
            try:
                self.canal.cerrar()
            except Exception:
                pass
