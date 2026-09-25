"""Compañero de IA: el servidor oye, piensa y habla; la pantalla pone la cara.

    micrófono ──▶ Whisper ──▶ modelo local ──▶ voz neuronal ──▶ altavoz
                 (proceso        (Ollama)                          │
                  aparte)                                          ▼
                                                    cara animada, por USB o WiFi

El micrófono y los altavoces van SIEMPRE en la máquina que ejecuta esto. La
placa de la cara no lleva audio —ni micro, ni altavoz, ni códec, y el único
conector que saca pines son GND, 3V3, TX y RX—, así que es cara y táctil, nada
más. Lo que gana con el WiFi es poder estar en otra habitación.

Lo que sale del ordenador y lo que no: el audio de tu micrófono se transcribe
aquí con Whisper y el modelo corre en local, así que nada de lo que dices se va
a ninguna parte. Solo el TEXTO de las respuestas viaja, y únicamente para que
Microsoft lo convierta en voz; si no hay internet, se usa una voz local.

Uso:
    python buddy_pc.py            # espera a que la cara llame por WiFi
    python buddy_pc.py COM3       # cara por cable USB
    python buddy_pc.py 8787       # por WiFi, en otro puerto
"""

import asyncio
import queue
import random
import re
import sys
import time

import actividad
import cara as C
import conversacion
import despertar
import herramientas
from cara import Cara
from cerebro import Cerebro
import voz as voz_mod
from oido_remoto import OidoRemoto
from voz import Voz

# La consola de Windows usa cp1252 por defecto y revienta con cualquier acento
# o caracter de dibujo. Ademas el proceso hijo del oido escribe por una tuberia
# que el padre lee como UTF-8: si no se fuerza aqui, no coinciden.
# comtypes (que usa pycaw para el volumen) inicializa COM en apartamento STA y
# winrt necesita MTA. Hay que forzarlo ANTES de importar nada de eso.
sys.coinit_flags = 0          # COINIT_MULTITHREADED

for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(encoding="utf-8", errors="replace")

CARA = sys.argv[1] if len(sys.argv) > 1 else "red"
MODELO = "qwen3:8b"                     # ya descargado y muy bueno en español
# Tiene que ser una voz es-ES: las multilingües y las es-MX o es-AR hablan
# español perfecto pero con acento que no es de aquí. Solo hay tres castellanas:
# ElviraNeural, AlvaroNeural y XimenaNeural.
VOZ_NEURONAL = "es-ES-ElviraNeural"     # castellana; Alvaro es la masculina
RITMO_VOZ = "+12%"                      # de serie lee con cadencia de locutora
TONO_VOZ = "+6Hz"
VOZ_LOCAL = voz_mod.VOZ_RESPALDO        # Piper, cuando no hay internet
# large-v3-turbo acierta mucho mas que small y apenas tarda mas; en la 3060
# ocupa ~1,6 GB y convive con el modelo de charla sin apreturas.
TAMANO_WHISPER = "large-v3-turbo"

# Siempre el fifine. Windows pone por defecto el microfono de la webcam, que
# esta lejos y suena fatal, y con el las transcripciones eran ilegibles. Si no
# esta conectado se para con un aviso en vez de tirar de otro en silencio:
# escuchar mal sin decirlo es peor que no arrancar.
MICROFONO = "fifine"
MEMORIA = 12                            # turnos que recuerda

# Lo que contesta al llamarle y al despedirse. Van variadas porque oir siempre
# exactamente lo mismo cansa enseguida, y van fijas (sin pasar por el modelo)
# porque dos segundos de espera en un "dime" se notan muchisimo.
ATIENDE = ("Dime.", "Que pasa?", "Aqui estoy.", "Dime, que necesitas?",
           "Te escucho.", "Que quieres?")
DESPEDIDAS = ("Hasta luego.", "Nos vemos.", "Adios, aqui sigo.",
              "Venga, hasta ahora.", "Hasta luego, llamame cuando quieras.")

# Dos lecciones aprendidas a base de probarlo:
#   - Todo en afirmativo. Al prohibirle expresamente decir que era un reloj,
#     contestaba "no soy un reloj" en cada frase: nombrar lo que no quieres es
#     la forma más rápida de que no hable de otra cosa.
#   - Sin el nombre del usuario en tercera persona. Con él puesto, acababa
#     respondiendo "soy Javier" y confundiéndose con quien le hablaba.
CARACTER = (
    f"Te llamas {despertar.NOMBRE}. "
    "Eres la inteligencia artificial que vive en este ordenador. "
    "Te asomas al mundo por una pantalla pequena y redonda que hay sobre la "
    "mesa, y esa pantalla es tu cara. "
    "Hablas espanol de Espana y tratas de tu a tu interlocutor. "
    "Lo que dices se lee en voz alta: texto corrido, sin listas, sin markdown, "
    "sin emojis y sin acciones entre asteriscos. "
    # Sin enumerar aqui lo que sabe hacer: las herramientas ya van declaradas
    # aparte, y al listarlas tambien en el texto el modelo acababa recitandolas
    # ("tengo que ir a ver que pasa en la pantalla") en vez de responder.
    "Puedes actuar sobre el ordenador. Cuando te pidan algo que puedas hacer, "
    "hazlo y cuenta en una sola frase lo que ha pasado. Si la herramienta te "
    "devuelve un dato concreto, una hora, un titulo o un numero, dilo. "
    "Cuando ya sepas en que programa esta trabajando, aprovechalo para "
    "responder algo util sobre ese programa."
)

# El tono va por ejemplos, no por adjetivos. Descrito con palabras ("eres
# cálido, directo, con humor seco"), el modelo acababa recitando esa misma lista
# en sus respuestas, como si le hubieran preguntado por su currículum.
EJEMPLOS = [
    {"role": "user", "content": "Que eres?"},
    {"role": "assistant", "content": f"{despertar.NOMBRE}, la inteligencia artificial "
                                     "de tu ordenador. Esa pantallita redonda de la "
                                     "mesa es mi cara."},
    {"role": "user", "content": "Estoy cansado."},
    {"role": "assistant", "content": "Pues cierra el portatil y vete a dar una vuelta. "
                                     "Aqui sigo cuando vuelvas."},
    {"role": "user", "content": "Cuanto pesa la Luna?"},
    {"role": "assistant", "content": "Unos setenta y tres trillones de toneladas. "
                                     "Un numero que no significa nada hasta que lo "
                                     "comparas: es la ochentava parte de la Tierra."},
]

# Con \b para que solo cuente la risa de verdad: sin los limites de palabra,
# "ja" salta con trabajar, dejar, mejor, caja... y ponia cara de contento en
# media conversacion.
ALEGRIA = re.compile(r"!|\b(ja+ja+|jeje|genial|estupendo|me encanta)\b", re.I)

# Frases que senalan algo que la persona tiene delante sin nombrarlo. Aqui NO se
# deja a criterio del modelo: si dice "ayudame con esto", el contexto se le da
# hecho. Confiando en que llamara a la herramienta, la mitad de las veces
# contestaba "dime que estas haciendo", que es justo lo que no queremos.
SENALA = re.compile(
    r"\b(esto|esta cosa|aqui|aquí|ayudame|ayúdame|ayuda|"
    r"echa(le)? un (ojo|vistazo)|que estoy haciendo|qué estoy haciendo|"
    r"lo que estoy|no me funciona|no funciona|que hago|qué hago|"
    r"no se que|no sé qué)\b", re.I)


async def preparar_cerebro():
    cerebro = Cerebro(MODELO, CARACTER, EJEMPLOS, memoria=MEMORIA,
                      herramientas=herramientas.esquemas())

    disponible, mensaje = await asyncio.to_thread(cerebro.revisar)
    print(f"[cerebro] {mensaje}")
    if not disponible:
        return None

    print("[cerebro] calentando el modelo...")
    try:
        await asyncio.to_thread(cerebro.pensar, [{"role": "user", "content": "hola"}])
    except Exception as e:
        print(f"[cerebro] no responde: {e}")
        return None
    print("[cerebro] listo")
    return cerebro


def elegir_microfono():
    """Devuelve el indice del microfono exigido, o para el programa."""
    import sounddevice as sd
    entradas = [(i, d) for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0]

    for i, d in entradas:
        if MICROFONO in d["name"].lower():
            print(f"[oido] microfono: {d['name'].strip()}")
            return i

    disponibles = "\n".join(f"    - {d['name'].strip()}" for _, d in entradas)
    raise SystemExit(
        f"\nNo encuentro ningun microfono que se llame '{MICROFONO}'.\n"
        f"Conectalo y vuelve a arrancar. Microfonos que veo ahora:\n{disponibles}\n"
        f"\n(Si quieres usar otro, cambia MICROFONO en buddy_pc.py.)")


async def preparar_oido():
    print("[oido] arrancando el proceso de escucha...")
    oido = OidoRemoto(tamano=TAMANO_WHISPER, dispositivo=elegir_microfono())
    await asyncio.to_thread(oido.esperar)
    print(f"[oido] Whisper '{TAMANO_WHISPER}' en {oido.motor}, "
          f"ruido de fondo {oido.ruido:.4f}")
    return oido


async def latido(cara, oido, estado_actual):
    """Le recuerda a la cara que seguimos aqui y le pasa el nivel del microfono.

    Sin esto la cara se dormia: solo recibia mensajes al cambiar de estado, y
    entre pregunta y pregunta pasan minutos.
    """
    ultimo_estado = 0.0
    while True:
        try:
            cara.nivel(oido.nivel)
            ahora = time.time()
            if ahora - ultimo_estado > 2.0:
                ultimo_estado = ahora
                cara.estado(estado_actual())
        except Exception:
            pass
        await asyncio.sleep(0.1)


class _Cronometro:
    """Envuelve la cara solo para anotar cuando empieza a hablar.

    El tiempo total de un turno incluye lo que tarda en DECIR la respuesta, que
    puede ser diez segundos y no es latencia. Lo que se percibe es cuanto tarda
    en abrir la boca.
    """

    def __init__(self, cara):
        self.cara, self.primera = cara, None
        self.t0 = time.time()

    def estado(self, e):
        if e == C.HABLANDO and self.primera is None:
            self.primera = time.time() - self.t0
        self.cara.estado(e)

    def emocion(self, m):
        self.cara.emocion(m)

    def boca(self, v):
        self.cara.boca(v)


async def turno(cerebro, voz, cara, oido, historial, frase):
    print(f"[tu]  {frase}")
    cara.estado(C.PENSANDO)

    # Si la frase senala algo sin nombrarlo, se le adjunta en que programa
    # anda: cuesta microsegundos y es informacion util.
    #
    # Se probo a mirar TAMBIEN la pantalla en estos casos y no compensa: son
    # cuatro segundos cuando el modelo de vision esta cargado y casi un minuto
    # cuando no. Para ver la pantalla ya esta la herramienta, que el modelo
    # llama solo cuando le preguntan por lo que hay en ella.
    contenido = frase
    if SENALA.search(frase):
        contexto = herramientas.que_estoy_haciendo()
        contenido = f"[Contexto: {contexto}]\n{frase}"
        print(f"[ctx]  {contexto}")

    historial.append({"role": "user", "content": contenido})

    crono = _Cronometro(cara)
    respuesta = await conversacion.responder(cerebro, voz, crono, oido, historial)

    if not respuesta:
        cara.emocion(C.TRISTE)
        return

    espera = f"{crono.primera:.1f}s" if crono.primera else "?"
    print(f"[buddy] (empieza a hablar en {espera}) {respuesta}")
    historial.append({"role": "assistant", "content": respuesta})
    cara.emocion(C.FELIZ if ALEGRIA.search(respuesta) else C.NEUTRO)


async def main():
    print(__doc__.split("Uso:")[0].strip(), "\n")

    cerebro = await preparar_cerebro()
    if cerebro is None:
        return

    # Empieza a mirar en que anda desde ya, para que cuando le preguntes ya
    # tenga historial en vez de estrenarse en ese momento.
    actividad.VIGIA.arrancar()

    cara = Cara(CARA)
    cara.emocion(C.NEUTRO)
    cara.estado(C.REPOSO)
    voz = Voz(VOZ_NEURONAL, VOZ_LOCAL, RITMO_VOZ, TONO_VOZ)

    # moondream ocupa 1,7 GB y cabe junto al modelo de charla y a Whisper
    # (9,3 de 12 GB). Precalentarlo evita que la primera mirada cueste un minuto.
    asyncio.create_task(asyncio.to_thread(herramientas.precalentar_vision))

    oido = await preparar_oido()
    vigilia = despertar.Vigilia()
    # Dormido: la cara en reposo. Es el mismo estado que usa cuando no hay nadie
    # al otro lado, y funciona igual de bien aqui: se le nota que no esta atento.
    estado = {"valor": C.REPOSO}
    cara.estado(C.REPOSO)
    vigilante = asyncio.create_task(latido(cara, oido, lambda: estado["valor"]))
    print(f"\nLlamale por su nombre ({vigilia.nombre}) para empezar, y dile "
          f"adios para terminar.\nCtrl+C para salir.\n")

    historial = []
    try:
        while True:
            for motivo in herramientas.avisos_vencidos():
                estado["valor"] = C.HABLANDO
                await turno(cerebro, voz, cara, oido, historial,
                            f"(Ha vencido el aviso de {motivo}. Avisame en una frase.)")
                # Un aviso le despierta: si te acaba de hablar, lo natural es
                # poder contestarle sin volver a llamarle por su nombre.
                vigilia.despertar()
                estado["valor"] = C.ESCUCHANDO
                cara.estado(C.ESCUCHANDO)

            if vigilia.se_ha_aburrido():
                vigilia.dormir()
                print(f"[{vigilia.nombre}] se duerme; llamale por su nombre")
                estado["valor"] = C.REPOSO
                cara.estado(C.REPOSO)

            try:
                frase = oido.frases.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            accion, texto = vigilia.oye(frase)

            if accion == "nada":
                # Se oye pero no va con el. Se deja constancia para poder
                # entender por que no contesta, que si no parece averiado.
                print(f"[ignorado] {frase}")
                continue

            if accion == "saluda":
                estado["valor"] = C.HABLANDO
                cara.emocion(C.FELIZ)
                await conversacion.decir_suelto(
                    random.choice(ATIENDE), voz, cara, oido)
            elif accion == "despide":
                estado["valor"] = C.HABLANDO
                cara.emocion(C.FELIZ)
                await conversacion.decir_suelto(
                    random.choice(DESPEDIDAS), voz, cara, oido)
                historial.clear()          # la proxima charla empieza limpia
                print(f"[{vigilia.nombre}] hasta luego")
                cara.emocion(C.NEUTRO)
                estado["valor"] = C.REPOSO
                cara.estado(C.REPOSO)
                oido.vaciar()
                continue
            else:
                estado["valor"] = C.PENSANDO
                await turno(cerebro, voz, cara, oido, historial, texto)

            estado["valor"] = C.ESCUCHANDO
            cara.estado(C.ESCUCHANDO)
            oido.vaciar()          # descarta lo colado mientras respondia
    finally:
        vigilante.cancel()
        oido.cerrar()
        cara.cerrar()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nhasta luego")
