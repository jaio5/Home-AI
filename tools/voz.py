"""El que habla: sintesis neuronal con respaldo local, y la envolvente que
mueve la boca.

La voz neuronal va por los servidores de Microsoft: sale el TEXTO de las
respuestas, nunca el audio del microfono. Si no hay internet se cae sola a
Piper, que sintetiza aqui mismo sin pedirle permiso a nadie.

El respaldo era antes la voz de Windows (SAPI, via winrt). Se cambio por Piper
por dos motivos: suena bastante mejor, y sobre todo winrt solo existe en
Windows, asi que ese import de arriba impedia que esto arrancase siquiera en el
servidor Ubuntu. Piper es el mismo codigo en los dos sitios.
"""

import io
import pathlib
import wave

import edge_tts
import numpy as np
import soundfile as sf

# Junto al modulo, no relativo al directorio desde el que se lance: si no,
# arrancar el buddy desde otra carpeta se quedaba sin voz de respaldo.
VOCES = pathlib.Path(__file__).parent / "voces"
VOZ_RESPALDO = VOCES / "es_ES-davefx-medium.onnx"


class Voz:
    """Voz neuronal de Microsoft con retoque de prosodia.

    Las voces de serie leen con cadencia de locutor de megafonia: correctas y
    planas. Subiendo algo el ritmo y el tono se acercan bastante mas a como
    habla alguien de verdad. Los valores estan medidos a oido sobre frases de
    conversacion, no sacados de ningun sitio.
    """

    def __init__(self, neuronal, respaldo=VOZ_RESPALDO, ritmo="+12%", tono="+6Hz"):
        self.neuronal = neuronal
        self.respaldo = pathlib.Path(respaldo)
        self.ritmo = ritmo
        self.tono = tono
        self._aviso_dado = False
        self._piper = None          # 60 MB: se carga solo si hace falta

    async def sintetizar(self, texto):
        """(audio mono en float32, frecuencia)."""
        try:
            datos = b""
            comunicacion = edge_tts.Communicate(texto, self.neuronal,
                                                rate=self.ritmo, pitch=self.tono)
            async for trozo in comunicacion.stream():
                if trozo["type"] == "audio":
                    datos += trozo["data"]
            audio, frec = sf.read(io.BytesIO(datos), dtype="float32")
        except Exception as e:
            if not self._aviso_dado:        # una vez, no en cada frase
                print(f"[voz] la neuronal no responde ({str(e)[:60]}); uso la local")
                self._aviso_dado = True
            audio, frec = self._local(texto)

        if audio.ndim > 1:
            audio = audio[:, 0]
        return audio, frec

    def _local(self, texto):
        """Piper, aqui mismo y sin internet."""
        if self._piper is None:
            from piper import PiperVoice
            self._piper = PiperVoice.load(str(self.respaldo))

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self._piper.synthesize_wav(texto, w)
        buf.seek(0)
        with wave.open(buf) as w:
            frec = w.getframerate()
            crudo = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return crudo.astype(np.float32) / 32768.0, frec


def envolvente(audio, frec, por_segundo=30):
    """Volumen por tramos cortos, que es lo que abre y cierra la boca."""
    por_tramo = max(1, int(frec / por_segundo))
    sobra = len(audio) % por_tramo
    recorte = audio[:len(audio) - sobra] if sobra else audio
    if recorte.size == 0:
        return []

    niveles = np.sqrt((recorte.reshape(-1, por_tramo) ** 2).mean(axis=1))
    pico = float(niveles.max()) or 1.0
    # raiz cuadrada: la boca acompana tambien las silabas flojas, que en escala
    # lineal se quedarian practicamente cerradas
    return (100 * np.sqrt(niveles / pico)).clip(0, 100).astype(int).tolist()
