"""Saber en qué anda el usuario, sin gastar GPU ni salir del ordenador.

Mirar la pantalla con el modelo de visión cuesta unos cuatro segundos, así que
hacerlo cada poco para enterarse de si sigues en el mismo sitio es un
desperdicio. El título de la ventana activa cuesta microsegundos y dice casi lo
mismo: "buddy_pc.py - Visual Studio Code", "Counter-Strike 2", "Twitch - Opera".

Aquí se lleva ese registro en segundo plano. Cuando de verdad hace falta ver
algo —un error concreto, una imagen— ya está `ver_pantalla` para eso.

Todo se queda en memoria y no se escribe en ningún sitio.
"""

import collections
import ctypes
import sys
import threading
import time

# Esto es mirar por la ventana de Windows, literalmente, y solo existe alli. En
# el servidor Ubuntu no hay escritorio al que asomarse, asi que el modulo se
# carga igual pero no mira nada y lo dice.
#
# El guardia no es por gusto: ni ctypes.wintypes ni ctypes.windll existen fuera
# de Windows, y como estaban sueltos arriba bastaban para que el buddy entero no
# llegase ni a arrancar en Linux.
HAY_ESCRITORIO = sys.platform == "win32"

if HAY_ESCRITORIO:
    import ctypes.wintypes as tipos
    _u32 = ctypes.windll.user32
    _k32 = ctypes.windll.kernel32
else:
    tipos = None
    _u32 = _k32 = None

_CONSULTA_LIMITADA = 0x1000        # PROCESS_QUERY_LIMITED_INFORMATION

INTERVALO = 2.0                    # cada cuanto se mira
RECUERDO = 40                      # cuantos cambios se guardan

# Lo que muestra un titulo de ventana es tecnico; esto lo traduce a algo que se
# pueda decir en voz alta sin sonar a informe de sistema.
NOMBRES = {
    "code.exe": "Visual Studio Code", "chrome.exe": "Chrome",
    "opera.exe": "Opera GX", "opera_gx.exe": "Opera GX",
    "msedge.exe": "Edge", "firefox.exe": "Firefox",
    "spotify.exe": "Spotify", "discord.exe": "Discord",
    "steam.exe": "Steam", "steamwebhelper.exe": "Steam",
    "explorer.exe": "el explorador de archivos",
    "windowsterminal.exe": "la terminal", "cmd.exe": "la terminal",
    "powershell.exe": "la terminal", "stremio.exe": "Stremio",
    "telegram.exe": "Telegram", "idea64.exe": "IntelliJ",
    "unity.exe": "Unity", "reaper.exe": "REAPER", "blender.exe": "Blender",
}


def _ventana_activa():
    """(aplicacion, titulo) de la ventana que tiene el foco."""
    if not HAY_ESCRITORIO:
        return None, None
    ventana = _u32.GetForegroundWindow()
    if not ventana:
        return None, None

    largo = _u32.GetWindowTextLengthW(ventana)
    texto = ctypes.create_unicode_buffer(largo + 1)
    _u32.GetWindowTextW(ventana, texto, largo + 1)

    pid = tipos.DWORD()
    _u32.GetWindowThreadProcessId(ventana, ctypes.byref(pid))
    proceso = _k32.OpenProcess(_CONSULTA_LIMITADA, False, pid.value)
    ejecutable = ""
    if proceso:
        ruta = ctypes.create_unicode_buffer(512)
        tam = tipos.DWORD(512)
        if _k32.QueryFullProcessImageNameW(proceso, 0, ruta, ctypes.byref(tam)):
            ejecutable = ruta.value.rsplit("\\", 1)[-1]
        _k32.CloseHandle(proceso)
    return ejecutable, texto.value


def _bonito(ejecutable, titulo):
    app = NOMBRES.get((ejecutable or "").lower())
    if app:
        return app
    if titulo and " - " in titulo:      # "algo - Programa"
        return titulo.rsplit(" - ", 1)[-1].strip()
    return (ejecutable or "algo").replace(".exe", "")


class Vigia:
    """Anota los cambios de ventana en segundo plano."""

    def __init__(self):
        self.historia = collections.deque(maxlen=RECUERDO)
        self.actual = (None, None, time.time())
        self._parar = threading.Event()

    def arrancar(self):
        if not HAY_ESCRITORIO:
            print("[vigia] sin escritorio que mirar; no se en que andas")
            return
        threading.Thread(target=self._bucle, daemon=True).start()

    def parar(self):
        self._parar.set()

    def _bucle(self):
        while not self._parar.wait(INTERVALO):
            try:
                ejecutable, titulo = _ventana_activa()
            except Exception:
                continue
            if not ejecutable:
                continue
            app = _bonito(ejecutable, titulo)
            if (app, titulo) != self.actual[:2]:
                self.historia.append((app, titulo, time.time()))
                self.actual = (app, titulo, time.time())

    # ------------------------------------------------------------ consulta --
    def ahora(self):
        app, titulo, desde = self.actual
        if not app:
            return "No se que tienes abierto ahora mismo."
        minutos = (time.time() - desde) / 60
        # El titulo suele acabar en " - Programa", que ya se dice por separado
        detalle = titulo.rsplit(" - ", 1)[0].strip() if titulo and " - " in titulo else titulo
        texto = f"Ahora mismo tienes delante {app}"
        if detalle and detalle.lower() != app.lower():
            texto += f", concretamente '{detalle}'"
        if minutos >= 1:
            texto += f", desde hace {int(minutos)} minutos"
        return texto + "."

    def resumen(self, minutos=15):
        """Por donde ha andado ultimamente, sin repetir.

        Redactado en segunda persona a proposito: el modelo tiende a repetir el
        resultado de la herramienta tal cual, y en tercera persona sonaba a
        informe sobre alguien ausente."""
        limite = time.time() - minutos * 60
        vistos, orden = set(), []
        for app, _, cuando in reversed(self.historia):
            if cuando < limite or app in vistos:
                continue
            vistos.add(app)
            orden.append(app)
            if len(orden) >= 6:
                break
        if not orden:
            return ""
        return "En los ultimos minutos has estado en: " + ", ".join(orden) + "."


VIGIA = Vigia()
