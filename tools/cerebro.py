"""El que piensa: cliente de Ollama con modelo local.

Nada de lo que se dice aqui sale del ordenador.
"""

import json
import os
import re
import socket
import urllib.request

import sistema

# Aqui abajo se lee el entorno en cuanto se importa el modulo, asi que los
# ajustes tienen que estar puestos ANTES. Es idempotente y no pisa nada.
sistema.cargar_ajustes()

# NO usar "localhost", y esto tiene historia. En Windows resuelve primero a IPv6
# (::1); si Ollama solo escucha en IPv4 la conexion se rechaza y hay que esperar
# al reintento: 2,35 s por peticion contra 0,16 s yendo a la IP directa.
#
# Pero cual de las dos es la buena no es fijo. Con Ollama dentro de WSL quien
# abre el puerto en Windows es wslrelay, y segun como haya arrancado unas veces
# escucha en IPv4 y otras solo en IPv6. Clavar cualquiera de las dos deja el
# companero mudo la mitad de las veces.
#
# Asi que se prueba UNA vez al arrancar y se recuerda. Se conserva lo importante
# —ni resolucion de nombres ni reintentos en cada peticion— sin la fragilidad.
CANDIDATOS = ("127.0.0.1", "[::1]")
PUERTO = 11434

# Cuando el cerebro viva en el servidor Ubuntu, aqui va su direccion:
#   BUDDY_OLLAMA=http://192.168.3.40:11434
_MANUAL = os.environ.get("BUDDY_OLLAMA", "").strip()


def _buscar_ollama():
    if _MANUAL:
        return _MANUAL.rstrip("/")
    for anfitrion in CANDIDATOS:
        crudo = anfitrion.strip("[]")
        familia = socket.AF_INET6 if ":" in crudo else socket.AF_INET
        s = socket.socket(familia, socket.SOCK_STREAM)
        s.settimeout(0.4)
        try:
            s.connect((crudo, PUERTO))
            return f"http://{anfitrion}:{PUERTO}"
        except OSError:
            continue
        finally:
            s.close()
    # Nadie contesta. Se devuelve el habitual para que el aviso de revisar()
    # salga con una direccion que el usuario reconozca.
    return f"http://{CANDIDATOS[0]}:{PUERTO}"


URL_BASE = _buscar_ollama()

_RAZONAMIENTO = re.compile(r"<think>.*?</think>", re.S)
# Antes habia aqui una regla que borraba todo lo que fuera entre asteriscos,
# para quitar acotaciones tipo *se rasca la cabeza*. Se cargaba tambien los
# titulos que el modelo escribe en cursiva: "Suena *Gumball*" se quedaba en
# "Suena". Borrar contenido de verdad es mucho peor que colar una acotacion,
# asi que ahora solo se quitan las marcas y el texto se queda.
_MARCAS = re.compile(r"[*_`#]")


def limpiar(texto):
    """Deja el texto listo para leerlo en voz alta."""
    texto = _RAZONAMIENTO.sub("", texto)
    texto = _MARCAS.sub("", texto)
    texto = " ".join(texto.split()).strip()

    # Al limitar los tokens la frase puede quedarse a medias; se corta en el
    # ultimo final de frase para que no se oiga un tajo.
    if texto and texto[-1] not in ".!?":
        corte = max(texto.rfind("."), texto.rfind("!"), texto.rfind("?"))
        if corte > 20:
            texto = texto[:corte + 1]
    return texto


class Cerebro:
    def __init__(self, modelo, caracter, ejemplos, memoria=12,
                 temperatura=0.8, tope_tokens=90, herramientas=None):
        self.modelo = modelo
        self.caracter = caracter
        self.ejemplos = ejemplos
        self.memoria = memoria
        self.temperatura = temperatura
        self.tope_tokens = tope_tokens
        self.herramientas = herramientas or []

    # ------------------------------------------------------------ peticion --
    def cuerpo(self, historial, en_directo, con_herramientas=True):
        # Tres tareas distintas con tres temperaturas distintas:
        #   elegir herramienta -> determinista, o se salta la llamada y se
        #     inventa la respuesta
        #   contar el resultado -> tibio, para que diga el dato en vez de hacer
        #     un chiste y dejarse el titulo dentro
        #   charlar -> creativo, que es donde tiene gracia
        contando = any(m.get("role") == "tool" for m in historial[-6:])
        if con_herramientas and self.herramientas:
            temperatura = 0.2
        elif contando:
            temperatura = 0.25
        else:
            temperatura = self.temperatura
        # Los ejemplos ensenan el TONO, y para eso hay que enseñarle respuestas
        # dichas de memoria. Eso mismo le ensena a contestar sin usar
        # herramientas: con ellos puestos se inventaba lo que habia en la
        # pantalla en vez de mirarla. Solo se ponen cuando toca hablar.
        mensajes = [{"role": "system", "content": self.caracter}]
        if not (con_herramientas and self.herramientas):
            mensajes += self.ejemplos
        mensajes += historial[-self.memoria:]

        cuerpo = {
            "model": self.modelo,
            "messages": mensajes,
            # qwen3 razona en voz alta por defecto y eso acabaria leido en alto
            "think": False,
            # sin esto Ollama descarga el modelo tras unos minutos de silencio y
            # la siguiente respuesta tarda 18 s en vez de 2
            "keep_alive": "30m",
            "stream": en_directo,
            "options": {"temperature": temperatura,
                        "num_predict": self.tope_tokens},
        }
        if con_herramientas and self.herramientas:
            cuerpo["tools"] = self.herramientas
        return cuerpo

    def _peticion(self, cuerpo):
        return urllib.request.Request(
            f"{URL_BASE}/api/chat",
            data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json"},
        )

    # -------------------------------------------------------- comprobacion --
    def revisar(self):
        """(disponible, mensaje). Se llama al arrancar, antes de nada."""
        try:
            with urllib.request.urlopen(f"{URL_BASE}/api/tags", timeout=5) as r:
                modelos = [m["name"] for m in json.load(r).get("models", [])]
        except Exception as e:
            return False, f"Ollama no responde ({e}). Arrancalo con: ollama serve"

        familia = self.modelo.split(":")[0]
        if not any(m.startswith(familia) for m in modelos):
            return False, f"falta {self.modelo}. Ejecuta: ollama pull {self.modelo}"
        return True, f"Ollama en marcha. Modelos: {', '.join(modelos)}"

    # ---------------------------------------------------------- respuestas --
    def pensar(self, historial):
        """Respuesta completa de golpe. Para calentar el modelo y para pruebas;
        en la conversacion se usa el flujo por frases."""
        req = self._peticion(self.cuerpo(historial, en_directo=False))
        with urllib.request.urlopen(req, timeout=120) as r:
            return limpiar(json.load(r)["message"]["content"])

    def trozos(self, historial, con_herramientas=True, recoger=None):
        """Generador SINCRONO de fragmentos de texto segun los va soltando el
        modelo. Quien lo consume decide como agruparlos.

        Las llamadas a herramientas no son texto: se van dejando en la lista
        `recoger` para que el turno las ejecute al terminar el flujo.
        """
        req = self._peticion(self.cuerpo(historial, True, con_herramientas))
        with urllib.request.urlopen(req, timeout=180) as r:
            for linea in r:
                if not linea.strip():
                    continue
                d = json.loads(linea)
                mensaje = d.get("message", {})
                if recoger is not None:
                    recoger.extend(mensaje.get("tool_calls") or [])
                trozo = mensaje.get("content", "")
                if trozo:
                    yield trozo
                if d.get("done"):
                    return
