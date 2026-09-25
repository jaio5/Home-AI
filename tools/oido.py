"""Oido: micrófono siempre abierto, transcripción local con Whisper.

SE EJECUTA COMO PROCESO APARTE, y no es por gusto: faster-whisper y winrt no
pueden convivir en el mismo proceso; en cuanto se cargan los dos, el intérprete
se cae con violación de segmento y sin mensaje alguno. Como la síntesis de voz
sí es de winrt, la única salida limpia es separarlos. De paso, si Whisper se
atraganta, el compañero sigue vivo.

    padre  --stdin-->   SORDO 1 | SORDO 0
    padre  <--stdout--  LISTO <motor> | RUIDO <n> | TXT <frase> | INFO <texto>

Nada de esto sale del ordenador. El reconocimiento de Windows se descartó
porque obliga a aceptar su política de voz, que envía el audio a Microsoft.

Cómo decide cuándo has terminado de hablar: mide el volumen en tramos de 32 ms
y compara con el ruido de fondo, que se calibra al arrancar. Cuando el volumen
sube durante un rato, empieza a guardar; cuando baja y se mantiene bajo, cierra
la frase y la transcribe. Es lo que se llama detección de actividad de voz, y
hacerla por volumen es suficiente aquí porque el micrófono está sobre la mesa,
no a tres metros.
"""

import collections
import queue
import threading
import time

import numpy as np
import sounddevice as sd

FREC = 16000                  # lo que espera Whisper
TRAMO = 512                   # 32 ms
SILENCIO_FIN = 0.75           # silencio que cierra una frase
MIN_VOZ = 0.35                # menos que esto es un ruido, no una frase
MAX_FRASE = 15.0              # tope, por si algo se queda abierto
MARGEN_RUIDO = 3.5            # cuánto tiene que superar al ruido de fondo
COLA_PREVIA = 12              # tramos guardados de ANTES de detectar la voz

# Lo que el modelo espera oir. Sesga la transcripcion hacia el castellano
# conversacional y hacia las palabras que se usan aqui; sin esto, "companero"
# acaba siendo "Kampaneru" y los nombres tecnicos se convierten en cualquier cosa.
#
# El nombre del asistente va aqui dentro, y no es un detalle: hay que decirlo
# para que le haga caso, asi que si Whisper lo transcribe mal no le hablas
# nunca. Un nombre propio corto y raro es justo lo que peor se le da a un
# transcriptor... salvo que se lo nombres antes, que es lo que hace esta pista.
import os                                                       # noqa: E402
import sistema                                                  # noqa: E402

sistema.cargar_ajustes()
_NOMBRE = (os.environ.get("BUDDY_NOMBRE") or "Nova").strip()

CONTEXTO = (f"Conversacion en espanol de Espana con {_NOMBRE}, un asistente de "
            f"voz al que se llama por su nombre: {_NOMBRE}. "
            "Se habla de musica, peliculas, series, el ordenador, la pantalla, "
            "el volumen, las luces y las camaras de casa.")


# Aqui se quedan vivos los manejadores de las librerias de NVIDIA. Si se
# recolectan, cuBLAS carga al crear el modelo y desaparece justo cuando toca
# transcribir. El porque de cada sistema esta en sistema.preparar_cuda.
_MANEJADORES = []


def _preparar_cuda():
    """ctranslate2 no busca las librerías de NVIDIA que instala pip. Se le
    indican a mano; si no están, se sigue en CPU sin más.

    Cada sistema lo necesita de una forma distinta, y eso vive en sistema.py."""
    import sistema
    sistema.preparar_cuda(_MANEJADORES)


class Oido:
    def __init__(self, tamano="small", dispositivo=None):
        self.sordo = threading.Event()      # activo mientras el compañero habla
        self.parar = threading.Event()
        self.tamano = tamano
        self.dispositivo = dispositivo
        self.modelo = None
        self.motor = "?"
        self.ruido = 0.0
        self.listo = threading.Event()
        self.avisar = lambda linea: None      # el proceso hijo lo sustituye

    # ------------------------------------------------------------- modelo --
    def cargar(self):
        from faster_whisper import WhisperModel
        _preparar_cuda()
        for disp, tipo in (("cuda", "float16"), ("cpu", "int8")):
            try:
                self.modelo = WhisperModel(self.tamano, device=disp, compute_type=tipo)
                self.motor = f"{disp}/{tipo}"
                return
            except Exception as e:
                if disp == "cpu":
                    raise
                self.avisar(f"INFO sin GPU ({str(e)[:70]}); voy por CPU")

    # ------------------------------------------------------------ captura --
    def arrancar(self):
        """El modelo se carga DENTRO del hilo que va a transcribir. Crearlo en
        un hilo y usarlo en otro es pedirle problemas al contexto de CUDA."""
        threading.Thread(target=self._escuchar, daemon=True).start()
        if not self.listo.wait(180):
            raise RuntimeError("Whisper no arrancó a tiempo")

    def _escuchar(self):
        if self.modelo is None:
            self.cargar()
        trozos = queue.Queue()

        def entrada(datos, _n, _t, estado):
            if not self.sordo.is_set():
                trozos.put(datos[:, 0].copy())

        with sd.InputStream(samplerate=FREC, blocksize=TRAMO, channels=1,
                            dtype="float32", device=self.dispositivo,
                            callback=entrada):
            self._calibrar(trozos)
            self._bucle(trozos)

    def _calibrar(self, trozos, segundos=1.2):
        """El umbral depende de la sala y del micrófono, así que se mide en vez
        de fijarlo a ojo."""
        niveles, limite = [], time.time() + segundos
        while time.time() < limite:
            try:
                niveles.append(float(np.sqrt(np.mean(trozos.get(timeout=0.5) ** 2))))
            except queue.Empty:
                break
        self.ruido = float(np.median(niveles)) if niveles else 0.002
        self.avisar(f"RUIDO {self.ruido:.5f}")
        self.listo.set()

    def _bucle(self, trozos):
        umbral = max(self.ruido * MARGEN_RUIDO, 0.006)
        buffer, hablando, ultimaVoz, inicio = [], False, 0.0, 0.0
        ultimoNivel = 0.0
        # Cuando el volumen supera el umbral, la primera silaba YA ha sonado.
        # Sin guardar los tramos anteriores, cada frase empezaba cortada y
        # Whisper adivinaba la palabra: de ahi salian la mitad de los disparates.
        previos = collections.deque(maxlen=COLA_PREVIA)
        # El ruido de fondo de una habitacion cambia: un ventilador que arranca,
        # una ventana que se abre. Se va reajustando con los tramos silenciosos.
        fondo = self.ruido

        while not self.parar.is_set():
            try:
                tramo = trozos.get(timeout=0.3)
            except queue.Empty:
                continue

            nivel = float(np.sqrt(np.mean(tramo ** 2)))
            ahora = time.time()

            # Nivel para la cara, unas diez veces por segundo. Se escala contra
            # el umbral, no en absoluto: asi vale igual en una habitacion
            # silenciosa que con el ventilador puesto.
            if ahora - ultimoNivel > 0.1:
                ultimoNivel = ahora
                self.avisar(f"NIV {min(100, int(100 * nivel / (umbral * 2.5)))}")

            if nivel > umbral:
                if not hablando:
                    hablando, inicio = True, ahora
                    buffer.extend(previos)      # rescata el arranque
                ultimaVoz = ahora
            elif not hablando:
                fondo += (nivel - fondo) * 0.01        # muy despacio
                umbral = max(fondo * MARGEN_RUIDO, 0.006)

            if not hablando:
                previos.append(tramo)
            else:
                buffer.append(tramo)
                bastante_silencio = ahora - ultimaVoz > SILENCIO_FIN
                demasiado_larga = ahora - inicio > MAX_FRASE
                if bastante_silencio or demasiado_larga:
                    duracion = ultimaVoz - inicio
                    audio = np.concatenate(buffer)
                    buffer, hablando = [], False
                    if duracion >= MIN_VOZ:
                        self._transcribir(audio)

    def _transcribir(self, audio):
        t0 = time.time()
        try:
            segmentos, _ = self.modelo.transcribe(
                audio, language="es",
                # beam_size 5 en vez de 1: explora mas alternativas antes de
                # decidir cada palabra. Cuesta decimas y acierta bastante mas.
                beam_size=5,
                initial_prompt=CONTEXTO,
                vad_filter=True,
                # Descarta lo que el propio modelo considera ruido: es lo que
                # evita los "gracias por ver el video" salidos del silencio.
                no_speech_threshold=0.5,
                condition_on_previous_text=False)
            texto = " ".join(s.text for s in segmentos).strip()
        except Exception as e:
            self.avisar(f"INFO fallo al transcribir: {e}")
            return

        # Whisper alucina muletillas con el silencio: "Gracias.", "Subtitulos
        # realizados por...". Se descartan las frases demasiado cortas.
        if len(texto) < 4 or texto.lower().strip(" .,!¡¿?") in (
                "gracias", "vale", "si", "ya", "mm", "eh", "ah"):
            return
        self.avisar(f"INFO transcrito en {time.time() - t0:.2f}s "
                    f"({len(audio) / FREC:.1f}s de audio)")
        self.avisar("TXT " + texto)


# ============================ proceso independiente =========================
def _principal():
    """Punto de entrada cuando se lanza como proceso hijo."""
    import sys

    # El padre lee esta tuberia como UTF-8; sin forzarlo aqui Windows escribiria
    # en cp1252 y cualquier frase con acentos llegaria rota.
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")

    def escribir(linea):
        sys.stdout.write(linea + "\n")
        sys.stdout.flush()

    tamano = sys.argv[1] if len(sys.argv) > 1 else "small"
    dispositivo = None
    if len(sys.argv) > 2 and sys.argv[2] != "-":
        dispositivo = int(sys.argv[2]) if sys.argv[2].isdigit() else sys.argv[2]

    o = Oido(tamano=tamano, dispositivo=dispositivo)
    o.avisar = escribir

    def ordenes():
        for linea in sys.stdin:
            linea = linea.strip()
            if linea == "SORDO 1":
                o.sordo.set()
            elif linea == "SORDO 0":
                o.sordo.clear()
            elif linea == "FIN":
                o.parar.set()
                return
    threading.Thread(target=ordenes, daemon=True).start()

    try:
        o.arrancar()
        escribir(f"LISTO {o.motor}")
    except Exception as e:
        escribir(f"INFO no arranco: {e}")
        return
    o.parar.wait()


if __name__ == "__main__":
    _principal()
