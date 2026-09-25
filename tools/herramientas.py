"""Lo que el compañero puede hacer de verdad en el ordenador.

Cada herramienta es una función concreta y acotada. NO hay una herramienta de
"ejecuta este comando": un modelo local interpretando voz transcrita, con
Whisper confundiendo alguna palabra de vez en cuando, y permiso para ejecutar
cualquier cosa, es un accidente esperando a ocurrir. Si algún día hace falta más
manga ancha, se añade una función nueva y acotada, no un agujero.

Para añadir una capacidad: se escribe la función, se decora con @herramienta y
se describe qué hace. La descripción es lo que lee el modelo para decidir cuándo
usarla, así que se escribe pensando en él.
"""

import base64
import io
import json
import os
import pathlib
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

import actividad
import archivos
import catalogo
import cerebro
import sistema
import spotify

# Antes de leer nada del entorno: asi secretos.env vale tanto si arrancas a mano
# como si lo lanza un servicio.
sistema.cargar_ajustes()

# --------------------------------------------------------------- registro ---
_TABLA = {}

# ---------------------------------------------------------------- reparto ---
# Que herramientas necesitan estar DELANTE del ordenador de verdad.
#
# Cuando el cerebro vive en el servidor Ubuntu, estas no las puede hacer el: no
# tiene tu pantalla, ni tus altavoces, ni tus juegos, ni tus archivos. Se le
# piden al agente que corre en el PC (agente_pc.py) y el las ejecuta alli.
#
# La lista esta aqui entera y a proposito, en vez de repartida por los
# decoradores: es la frontera entre las dos maquinas y lo unico que el servidor
# puede pedirle al PC. Conviene poder leerla de un vistazo antes de ampliarla.
EN_EL_PC = {
    "control_reproduccion", "que_suena", "ajustar_volumen",
    "que_estoy_haciendo", "ver_pantalla",
    "poner_youtube", "abrir_video_local",
    "abrir_aplicacion", "que_hay_instalado",
    "buscar_archivo", "listar_carpeta", "leer_archivo", "abrir_archivo",
}

# Donde esta el agente, y con que ficha se le habla. Sin AGENTE configurado todo
# se ejecuta aqui mismo, que es justo como funciona hoy con todo en el Windows.
#   BUDDY_AGENTE=http://192.168.3.16:8788
#   BUDDY_AGENTE_FICHA=<la misma cadena larga en las dos maquinas>
AGENTE = os.environ.get("BUDDY_AGENTE", "").strip().rstrip("/")
AGENTE_FICHA = os.environ.get("BUDDY_AGENTE_FICHA", "")
# ver_pantalla es la lenta: captura la pantalla y se la da al modelo de vision.
# Con el modelo ya cargado son 2-4 s, pero si el agente acaba de arrancar la
# primera carga se va a mas de 20. Medido aqui: 23,7 s en frio. El agente lo
# precalienta al arrancar justo para que eso no pase, y este plazo es el
# colchon por si aun asi le pilla frio.
AGENTE_PLAZO = 60


def herramienta(descripcion, parametros=None):
    """Registra una función para que el modelo pueda llamarla."""
    def envoltura(fn):
        _TABLA[fn.__name__] = {
            "fn": fn,
            "esquema": {
                "type": "function",
                "function": {
                    "name": fn.__name__,
                    "description": descripcion,
                    "parameters": {
                        "type": "object",
                        "properties": parametros or {},
                        "required": [k for k, v in (parametros or {}).items()
                                     if not v.pop("opcional", False)],
                    },
                },
            },
        }
        return fn
    return envoltura


def esquemas():
    """La lista que se le pasa al modelo."""
    return [h["esquema"] for h in _TABLA.values()]


def ejecutar_local(nombre, argumentos):
    """Llama a una herramienta AQUI y devuelve SIEMPRE un texto para el modelo.

    Nunca lanza: si algo falla, el modelo recibe el motivo y puede explicarlo o
    intentar otra cosa, que es mejor que tirar la conversación entera.
    """
    entrada = _TABLA.get(nombre)
    if entrada is None:
        return f"No existe ninguna herramienta llamada {nombre}."
    try:
        return str(entrada["fn"](**(argumentos or {})))
    except TypeError as e:
        return f"Argumentos incorrectos para {nombre}: {e}"
    except Exception as e:
        return f"{nombre} ha fallado: {e}"


def _pedir_al_agente(nombre, argumentos):
    """Le encarga al PC algo que aqui no se puede hacer."""
    cuerpo = json.dumps({"herramienta": nombre,
                         "argumentos": argumentos or {}}).encode()
    peticion = urllib.request.Request(
        f"{AGENTE}/ejecutar", data=cuerpo,
        headers={"Content-Type": "application/json",
                 "X-Ficha": AGENTE_FICHA})
    try:
        with urllib.request.urlopen(peticion, timeout=AGENTE_PLAZO) as r:
            return str(json.load(r).get("resultado", ""))
    except Exception as e:
        # El modelo lee esto y se lo cuenta al usuario. Que se entienda sin
        # saber que hay dos maquinas: lo que le pasa es que no llega al PC.
        return (f"No he podido hacerlo porque no consigo hablar con tu "
                f"ordenador ({str(e)[:70]}).")


def ejecutar(nombre, argumentos):
    """Ejecuta donde toque: aqui, o en el PC si el cerebro vive fuera."""
    if AGENTE and nombre in EN_EL_PC:
        return _pedir_al_agente(nombre, argumentos)
    return ejecutar_local(nombre, argumentos)


# ---------------------------------------------------------------- musica ---
@herramienta(
    "Controla la reproduccion de musica o video que ya esta sonando en el "
    "ordenador: pausar, reanudar, siguiente o anterior.",
    {"accion": {"type": "string", "enum": ["pausa", "sigue", "siguiente", "anterior"]}},
)
def control_reproduccion(accion):
    import asyncio
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Gestor)

    async def hazlo():
        ses = (await Gestor.request_async()).get_current_session()
        if ses is None:
            return "No hay nada reproduciendose ahora mismo."
        if accion in ("pausa", "sigue"):
            await ses.try_toggle_play_pause_async()
        elif accion == "siguiente":
            await ses.try_skip_next_async()
        elif accion == "anterior":
            await ses.try_skip_previous_async()
        else:
            return f"No se que es '{accion}'."
        return f"Hecho: {accion}."

    return asyncio.run(hazlo())


@herramienta("Dice que cancion o video esta sonando ahora mismo en el ordenador.")
def que_suena():
    import asyncio
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Gestor)

    async def mira():
        ses = (await Gestor.request_async()).get_current_session()
        if ses is None:
            return "No hay nada sonando."
        p = await ses.try_get_media_properties_async()
        return (f"Suena '{p.title}' de {p.artist}." if p.artist
                else f"Suena '{p.title}'.")

    return asyncio.run(mira())


# --------------------------------------------------------------- volumen ---
@herramienta(
    "Ajusta el volumen del ordenador a un porcentaje concreto, de 0 a 100.",
    {"porcentaje": {"type": "integer", "description": "De 0 a 100"}},
)
def ajustar_volumen(porcentaje):
    from pycaw.pycaw import AudioUtilities
    porcentaje = max(0, min(100, int(porcentaje)))
    control = AudioUtilities.GetSpeakers().EndpointVolume
    if control.GetMute():
        control.SetMute(0, None)
    control.SetMasterVolumeLevelScalar(porcentaje / 100, None)
    return f"Volumen al {porcentaje} por ciento."


# --------------------------------------------------------------- actividad ---
@herramienta(
    "Dice en que esta trabajando el usuario ahora mismo: que programa tiene "
    "delante, con que archivo o pagina, y por donde ha andado ultimamente. "
    "LLAMALA SIEMPRE, antes de contestar, cuando la peticion mencione 'esto', "
    "'aqui', 'lo que estoy haciendo', o pida ayuda sin decir con que: sin "
    "llamarla no sabes en que anda y tendrias que preguntarselo. Es instantanea "
    "y no consume nada.")
def que_estoy_haciendo():
    v = actividad.VIGIA
    return " ".join(x for x in (v.ahora(), v.resumen()) if x)


# ---------------------------------------------------------------- pantalla ---
# moondream ocupa 1,7 GB frente a los 4 de qwen2.5vl, asi que cabe en la GPU
# AL LADO del modelo de charla. Con el grande, Ollama tenia que descargar uno
# para cargar el otro y cada respuesta costaba quince segundos de recarga.
MODELO_VISION = "moondream:latest"


@herramienta(
    "Hace una captura de la pantalla y la mira de verdad, para ver el detalle: "
    "un error concreto, una imagen, el contenido de una ventana. Tarda unos "
    "segundos, asi que para saber solo en que programa esta es mejor "
    "que_estoy_haciendo. Es la UNICA forma de ver lo que hay en la pantalla: "
    "sin llamarla no tienes ni idea. Si te piden ayuda con algo que tienen "
    "delante, mira la pantalla ademas de consultar que_estoy_haciendo.",
    {"pregunta": {"type": "string", "opcional": True,
                  "description": "Que quiere saber sobre la pantalla"}},
)
def ver_pantalla(pregunta="Que se ve en esta pantalla?"):
    from PIL import ImageGrab

    captura = ImageGrab.grab()
    # Se reduce antes de enviarla: una pantalla 4K entera satura al modelo y
    # tarda una eternidad; para saber que hay, con 1280 px sobra.
    captura.thumbnail((1280, 1280))
    buf = io.BytesIO()
    captura.convert("RGB").save(buf, format="JPEG", quality=70)
    # moondream solo responde en ingles: preguntado en castellano devuelve
    # cadena vacia. Se le pregunta en su idioma y quien lo cuenta en espanol es
    # la vuelta de reporte, que reformula de todas formas.
    # moondream se atraganta con preguntas largas y devuelve cadena vacia. Con
    # una frase corta y en ingles responde siempre.
    return _pedir_vision(buf.getvalue(), "Describe what is on this screen.")


def _pedir_vision(imagen_jpeg, pregunta):
    cuerpo = {
        "model": MODELO_VISION,
        "stream": False,
        "keep_alive": "30m",
        "messages": [{
            "role": "user",
            "content": pregunta,
            "images": [base64.b64encode(imagen_jpeg).decode()],
        }],
    }
    # La direccion de Ollama la resuelve cerebro.py al arrancar, y no es
    # siempre la misma: con Ollama dentro de WSL unas veces escucha en IPv4 y
    # otras solo en IPv6. Aqui habia una copia clavada a 127.0.0.1 que dejaba
    # ciego al companero justo cuando tocaba la otra.
    req = urllib.request.Request(
        f"{cerebro.URL_BASE}/api/chat", data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["message"]["content"].strip()


def precalentar_vision():
    """Carga el modelo de vision con una imagen minuscula.

    Sin esto, la primera vez que se le pregunta por la pantalla tarda 11 s en
    vez de 4: lo que cuesta es cargar el modelo, no mirar. Se lanza en segundo
    plano al arrancar y con una imagen de 64 px, que no hace falta capturar la
    pantalla del usuario solo para reservar memoria.
    """
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 0, 0)).save(buf, format="JPEG")
    try:
        _pedir_vision(buf.getvalue(), "hola")
    except Exception:
        pass


# ---------------------------------------------------------------- youtube ---
@herramienta(
    "Busca un video, una cancion o un capitulo en YouTube y lo reproduce en el "
    "navegador. Uselo cuando pidan ver o poner algo concreto.",
    {"busqueda": {"type": "string", "description": "Que buscar en YouTube"}},
)
def poner_youtube(busqueda):
    consulta = urllib.parse.quote_plus(busqueda)
    url_busqueda = f"https://www.youtube.com/results?search_query={consulta}"
    try:
        peticion = urllib.request.Request(
            url_busqueda, headers={"User-Agent": "Mozilla/5.0 Chrome/131.0"})
        with urllib.request.urlopen(peticion, timeout=12) as r:
            html = r.read().decode("utf-8", "replace")
        # El primer identificador de video que aparece en la pagina de
        # resultados es el primer resultado. No hay API sin clave, asi que se
        # saca del HTML; si YouTube cambia el formato, se abre la busqueda y ya.
        m = re.search(r'"videoId":"([\w-]{11})"', html)
        if m:
            webbrowser.open(f"https://www.youtube.com/watch?v={m.group(1)}")
            titulo = re.search(r'"title":\{"runs":\[\{"text":"(.*?)"', html)
            return f"Reproduciendo {titulo.group(1) if titulo else busqueda} en YouTube."
    except Exception:
        pass
    webbrowser.open(url_busqueda)
    return f"He abierto la busqueda de {busqueda} en YouTube."


# ----------------------------------------------------------------- videos ---
CARPETAS_VIDEO = [
    pathlib.Path.home() / "Videos",
    pathlib.Path.home() / "Downloads",
    pathlib.Path.home() / "Desktop",
]
EXTENSIONES = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v"}


@herramienta(
    "Busca un video, una pelicula o un capitulo de serie entre los archivos del "
    "ordenador y lo abre con el reproductor por defecto.",
    {"busqueda": {"type": "string", "description": "Titulo o parte del nombre"}},
)
def abrir_video_local(busqueda):
    palabras = [p for p in re.split(r"\W+", busqueda.lower()) if len(p) > 2]
    if not palabras:
        return "No he entendido que video buscar."

    mejor, mejor_puntos = None, 0
    for carpeta in CARPETAS_VIDEO:
        if not carpeta.is_dir():
            continue
        for ruta in carpeta.rglob("*"):
            if ruta.suffix.lower() not in EXTENSIONES:
                continue
            nombre = ruta.stem.lower()
            puntos = sum(1 for p in palabras if p in nombre)
            if puntos > mejor_puntos:
                mejor, mejor_puntos = ruta, puntos

    if mejor is None:
        return (f"No he encontrado ningun video que se parezca a '{busqueda}' "
                f"en Videos, Descargas ni Escritorio.")
    import sistema
    fallo = sistema.abrir(mejor)
    if fallo:
        return f"No he podido abrir {mejor.name}: {fallo}"
    return f"Abriendo {mejor.name}."


# ------------------------------------------- aplicaciones, juegos y musica ---
@herramienta(
    "Abre una aplicacion o un juego que este instalado en el ordenador, por su "
    "nombre. Vale para programas (Spotify, Discord, Chrome, Visual Studio Code) "
    "y para juegos de Steam. No hace falta el nombre exacto.",
    {"nombre": {"type": "string", "description": "Como se llama, aunque sea a medias"}},
)
def abrir_aplicacion(nombre):
    candidatos = catalogo.buscar(nombre)
    if not candidatos:
        return (f"No tengo nada instalado que se parezca a '{nombre}'. "
                f"Solo puedo abrir lo que esta instalado en el ordenador.")

    titulo, destino, tipo = candidatos[0]
    catalogo.abrir(destino)
    # Si habia otro candidato casi igual de bueno se menciona, para que el
    # companero pueda ofrecer el otro si ha abierto el que no era.
    alternativa = ""
    if len(candidatos) > 1 and candidatos[1][0].lower() != titulo.lower():
        alternativa = f" (tambien tengo {candidatos[1][0]}, por si era ese)"
    return f"Abriendo {titulo}, que es un {tipo}.{alternativa}"


# Al preguntar "que juegos tengo", el modelo busca literalmente la palabra
# "juegos", que no es el nombre de nada. Se reconocen esos terminos genericos
# y se entienden como la categoria, que es lo que la persona queria decir.
CATEGORIAS = {
    "juego": "juego", "juegos": "juego", "game": "juego", "games": "juego",
    "aplicacion": "aplicacion", "aplicaciones": "aplicacion",
    "programa": "aplicacion", "programas": "aplicacion",
    "app": "aplicacion", "apps": "aplicacion",
}


@herramienta(
    "Dice que aplicaciones o juegos hay instalados que encajen con una "
    "busqueda. Uselo cuando pregunten que hay instalado o que juegos hay.",
    {"busqueda": {"type": "string", "opcional": True,
                  "description": "Filtro; vacio para los juegos"}},
)
def que_hay_instalado(busqueda=""):
    pedido = catalogo._plano(busqueda)
    categoria = CATEGORIAS.get(pedido)

    if categoria:
        titulos = [catalogo.catalogo()[n][0] for n in catalogo.nombres(categoria)]
        etiqueta = "Juegos" if categoria == "juego" else "Aplicaciones"
        # La lista de aplicaciones son mas de cien y no se puede leer en voz
        # alta: se dan unas cuantas y se dice cuantas hay.
        if len(titulos) > 15:
            return (f"{etiqueta} instaladas hay {len(titulos)}. Algunas: "
                    + ", ".join(titulos[:12]) + ".")
        return f"{etiqueta} instalados: " + ", ".join(titulos) + "."

    if pedido:
        hallazgos = [t for t, _, _ in catalogo.buscar(busqueda, 8)]
        if not hallazgos:
            return f"No tengo nada instalado que encaje con '{busqueda}'."
        return "Encaja con: " + ", ".join(hallazgos) + "."

    juegos = [catalogo.catalogo()[n][0] for n in catalogo.nombres("juego")]
    return "Juegos instalados: " + ", ".join(juegos) + "."


@herramienta(
    "Pone una cancion, un disco o un artista concreto en Spotify y lo empieza a "
    "reproducir. Uselo cuando pidan escuchar algo por su nombre.",
    {"busqueda": {"type": "string",
                  "description": "Cancion, disco o artista que se quiere oir"},
     "tipo": {"type": "string", "opcional": True,
              "enum": ["track", "album", "artist", "playlist"],
              "description": "Que se busca; por defecto una cancion"}},
)
def poner_en_spotify(busqueda, tipo="track"):
    return spotify.poner(busqueda, tipo if tipo in
                         ("track", "album", "artist", "playlist") else "track")


# ---------------------------------------------------------------- archivos ---
@herramienta(
    "Busca archivos por su nombre en las carpetas del usuario: escritorio, "
    "documentos, descargas, imagenes, videos, musica y los proyectos. Dice "
    "cuales ha encontrado, su tamano y donde estan.",
    {"nombre": {"type": "string", "description": "Nombre o parte del nombre"}},
)
def buscar_archivo(nombre):
    return archivos.buscar_texto(nombre)


@herramienta(
    "Dice que hay dentro de una carpeta. Sin indicar ninguna, dice a que "
    "carpetas tiene acceso.",
    {"carpeta": {"type": "string", "opcional": True,
                 "description": "Ruta o nombre de la carpeta"}},
)
def listar_carpeta(carpeta=""):
    return archivos.listar(carpeta)


@herramienta(
    "Lee el contenido de un archivo de texto y lo devuelve para poder "
    "resumirlo, explicarlo o buscar algo dentro. Vale para notas, codigo, "
    "configuraciones y listas.",
    {"nombre": {"type": "string", "description": "Nombre o ruta del archivo"}},
)
def leer_archivo(nombre):
    return archivos.leer(nombre)


@herramienta(
    "Abre un archivo o una carpeta con el programa que le corresponda.",
    {"nombre": {"type": "string", "description": "Nombre o ruta"}},
)
def abrir_archivo(nombre):
    return archivos.abrir(nombre)


# ------------------------------------------------------------ avisos ---------
_AVISOS = []


@herramienta(
    "Pone un temporizador o un aviso para dentro de un rato.",
    {"minutos": {"type": "number", "description": "Dentro de cuantos minutos"},
     "motivo": {"type": "string", "description": "Para que es el aviso"}},
)
def poner_aviso(minutos, motivo="el aviso"):
    minutos = max(0.1, float(minutos))
    cuando = time.time() + minutos * 60
    _AVISOS.append((cuando, motivo))
    return (f"Aviso puesto: te aviso en {minutos:.0f} minutos de {motivo}."
            if minutos >= 1 else f"Aviso puesto para dentro de {minutos*60:.0f} segundos.")


def avisos_vencidos():
    """Los que ya tocan. El bucle principal los consulta y los dice en voz alta."""
    ahora = time.time()
    vencidos = [m for c, m in _AVISOS if c <= ahora]
    _AVISOS[:] = [(c, m) for c, m in _AVISOS if c > ahora]
    return vencidos


# ------------------------------------------------------------- hora y fecha --
@herramienta("Dice la hora y la fecha de ahora mismo.")
def que_hora_es():
    from datetime import datetime
    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    a = datetime.now()
    return (f"Son las {a.hour} y {a.minute:02d}, {dias[a.weekday()]} "
            f"{a.day} de {meses[a.month - 1]}.")
