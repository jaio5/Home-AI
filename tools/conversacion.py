"""Un turno de conversacion, con las tres etapas solapadas.

El problema: pensar la respuesta entera y despues sintetizarla entera ponia la
primera palabra a casi ocho segundos, y a esa distancia no hay conversacion que
aguante.

La solucion es no esperar a nada completo. Tres etapas a la vez:

    modelo  --frases-->  sintesis  --audio-->  altavoz + labios

En cuanto el modelo cierra la primera pausa, esa frase ya se esta sintetizando;
mientras suena, se genera la siguiente. Y el PRIMER trozo se corta en la primera
coma, no en el primer punto: lo unico que importa al principio es empezar a
sonar, y una coma es una pausa perfectamente valida.
"""

import asyncio
import re

import sounddevice as sd

import cara as C
import herramientas
import voz as V
from cerebro import limpiar

FIN_DE_FRASE = re.compile(r"[.!?…]+[\s\"')\]]*")
PRIMERA_PAUSA = re.compile(r"[.!?…,;:]+\s")
MINIMO = 12                  # caracteres; por debajo no compensa cortar
MINIMO_PRIMERA = 24
FPS_BOCA = 30
ADELANTO = 2                 # frases sintetizadas por delante, como mucho


def trocear(texto, es_primera):
    """(frases completas, resto sin terminar)."""
    patron = PRIMERA_PAUSA if es_primera else FIN_DE_FRASE
    minimo = MINIMO_PRIMERA if es_primera else MINIMO
    frases, ultimo = [], 0
    for m in patron.finditer(texto):
        trozo = texto[ultimo:m.end()].strip()
        if len(trozo) >= minimo:
            frases.append(trozo)
            ultimo = m.end()
            if es_primera:
                break            # solo el primero se parte por comas
    return frases, texto[ultimo:]


async def _frases(cerebro, historial, llamadas, con_herramientas=True):
    """Frases limpias segun el modelo las va terminando.

    El generador de Ollama es sincrono y bloquea, asi que vive en un hilo y va
    dejando resultados en una cola que si es asincrona.
    """
    cola = asyncio.Queue()
    bucle = asyncio.get_running_loop()

    def leer():
        acumulado, ya_hablo = "", False
        try:
            for trozo in cerebro.trozos(historial, con_herramientas, llamadas):
                acumulado += trozo
                frases, acumulado = trocear(acumulado, not ya_hablo)
                for f in frases:
                    ya_hablo = True
                    bucle.call_soon_threadsafe(cola.put_nowait, f)
        except Exception as e:
            bucle.call_soon_threadsafe(cola.put_nowait, e)
        if acumulado.strip():
            bucle.call_soon_threadsafe(cola.put_nowait, acumulado.strip())
        bucle.call_soon_threadsafe(cola.put_nowait, None)

    tarea = bucle.run_in_executor(None, leer)
    try:
        while True:
            item = await cola.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            limpio = limpiar(item)
            if limpio:
                yield limpio
    finally:
        await tarea


async def _reproducir(audio, frec, cara):
    """Suelta el audio y va abriendo la boca al ritmo del volumen."""
    # La envolvente se calcula ANTES de arrancar el sonido: si no, la boca
    # empieza con unos milisegundos de retraso sobre la voz.
    niveles = V.envolvente(audio, frec, FPS_BOCA)
    sd.play(audio, frec)

    bucle = asyncio.get_running_loop()
    t0, paso = bucle.time(), 1 / FPS_BOCA
    for i, nivel in enumerate(niveles):
        cara.boca(nivel)
        # La boca se ata al reloj de pared, no a la velocidad del bucle: si un
        # envio tarda, se salta un valor en vez de acumular retraso.
        espera = (i + 1) * paso - (bucle.time() - t0)
        if espera > 0:
            await asyncio.sleep(espera)
    cara.boca(0)


async def _decir(cerebro, historial, voz, cara, oido, llamadas, con_herramientas):
    """Genera, sintetiza y reproduce a la vez. Devuelve lo que ha dicho."""
    audios = asyncio.Queue(maxsize=ADELANTO)
    dicho = []

    async def fabricar():
        try:
            async for frase in _frases(cerebro, historial, llamadas, con_herramientas):
                dicho.append(frase)
                await audios.put(await voz.sintetizar(frase))
        except Exception as e:
            print(f"[cerebro] error: {e}")
        finally:
            await audios.put(None)

    tarea = asyncio.create_task(fabricar())
    primera = True
    try:
        while True:
            item = await audios.get()
            if item is None:
                break
            if primera:
                cara.estado(C.HABLANDO)
                primera = False
            await _reproducir(*item, cara)
    finally:
        await tarea
    return " ".join(dicho)


async def responder(cerebro, voz, cara, oido, historial):
    """Un turno completo, con herramientas si el modelo las pide.

    El modelo puede contestar de dos maneras: hablando, o pidiendo que se haga
    algo. Cuando pide herramientas casi nunca dice nada a la vez, asi que se
    ejecutan y se le vuelve a preguntar; esa segunda vuelta ya es la que suena.
    """
    oido.ensordecer(True)                  # que no se escuche a si mismo
    try:
        llamadas = []
        dicho = await _decir(cerebro, historial, voz, cara, oido, llamadas, True)

        if llamadas:
            cara.estado(C.PENSANDO)
            historial.append({"role": "assistant", "content": dicho,
                              "tool_calls": llamadas})
            for llamada in llamadas:
                fn = llamada["function"]
                resultado = await asyncio.to_thread(
                    herramientas.ejecutar, fn["name"], fn.get("arguments"))
                print(f"[hacer] {fn['name']}({fn.get('arguments')}) -> {resultado}")
                historial.append({"role": "tool", "content": resultado})

            # En la segunda vuelta se quitan las herramientas: ya se ha hecho lo
            # que habia que hacer y solo falta contarlo. Dejandolas puestas, el
            # modelo tiende a repetir la misma llamada en bucle.
            segunda = await _decir(cerebro, historial, voz, cara, oido, [], False)
            dicho = (dicho + " " + segunda).strip() if dicho else segunda
    finally:
        sd.stop()
        await asyncio.sleep(0.3)           # cola de reverberacion del altavoz
        oido.ensordecer(False)

    return dicho
