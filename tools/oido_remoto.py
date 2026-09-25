"""Lanza el oído como proceso aparte y habla con él por tuberías.

La separación no es capricho: faster-whisper y winrt no pueden convivir en un
mismo proceso, y la síntesis de voz es de winrt. Ver la cabecera de oido.py.
"""

import pathlib
import queue
import subprocess
import sys
import threading

AQUI = pathlib.Path(__file__).resolve().parent


class OidoRemoto:
    def __init__(self, tamano="small", dispositivo=None):
        self.frases = queue.Queue()
        self.motor = "?"
        self.ruido = 0.0
        self.nivel = 0          # 0..100, lo alto que estas hablando ahora mismo
        self.listo = threading.Event()
        self.proc = subprocess.Popen(
            [sys.executable, "-u", str(AQUI / "oido.py"), tamano,
             str(dispositivo) if dispositivo is not None else "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        threading.Thread(target=self._leer, daemon=True).start()
        threading.Thread(target=self._errores, daemon=True).start()

    def _leer(self):
        for linea in self.proc.stdout:
            linea = linea.rstrip("\n")
            if linea.startswith("TXT "):
                self.frases.put(linea[4:])
            elif linea.startswith("LISTO "):
                self.motor = linea[6:]
                self.listo.set()
            elif linea.startswith("NIV "):
                self.nivel = int(linea[4:])
            elif linea.startswith("RUIDO "):
                self.ruido = float(linea[6:])
            elif linea.startswith("INFO "):
                print(f"[oido] {linea[5:]}")

    def _errores(self):
        for linea in self.proc.stderr:
            linea = linea.strip()
            # los avisos de descarga del modelo no son errores
            if linea and "warning" not in linea.lower():
                print(f"[oido!] {linea}")

    def _orden(self, texto):
        try:
            self.proc.stdin.write(texto + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def ensordecer(self, si):
        """Mientras el compañero habla, el micrófono se ignora: si no, se oye a
        sí mismo por los altavoces y se contesta solo."""
        self._orden("SORDO 1" if si else "SORDO 0")

    def esperar(self, segundos=240):
        if not self.listo.wait(segundos):
            raise RuntimeError("el oído no arrancó a tiempo")

    def vaciar(self):
        while not self.frases.empty():
            self.frases.get_nowait()

    def cerrar(self):
        self._orden("FIN")
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
