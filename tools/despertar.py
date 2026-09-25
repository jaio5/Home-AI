"""Cuándo atender y cuándo callarse.

Sin esto el compañero contesta a todo lo que oye, y eso en una habitación con
una tele puesta es insufrible: en las pruebas se pasó un rato entero
respondiendo a "gracias por ver el vídeo" y a un "¡oh!" que salía de un vídeo
de YouTube. Tiene que hacer falta llamarle.

    dormido  ──dices su nombre──▶  despierto  ──"adiós"──▶  dormido
                                       │  ▲
                                       └──┘ mientras habléis, sin repetir
                                            el nombre cada frase

Y se duerme solo tras un rato callado, que si no basta con despistarse una vez
para que vuelva a comentar la televisión toda la tarde.

Lo verdaderamente difícil aquí no es la lógica, son las erratas. Whisper no
transcribe un nombre propio corto de forma fiable: "Nova" sale como "nova",
"noba", "no va", "Nueva". Si se compara la cadena exacta, el compañero no te
hace caso nunca y no hay forma de saber por qué. Por eso se compara con
tolerancia, y por eso el nombre se le mete también a Whisper como pista (ver
CONTEXTO en oido.py), que es lo que de verdad arregla el problema de raíz.
"""


import os
import re
import time
import unicodedata

import sistema

sistema.cargar_ajustes()

# El nombre se cambia en secretos.env:  BUDDY_NOMBRE=Nova
NOMBRE = (os.environ.get("BUDDY_NOMBRE") or "Nova").strip()

# Cuánto aguanta despierto sin oír nada. Minuto y medio es bastante para
# encadenar preguntas sin repetir el nombre, y poco para que se quede
# escuchando la tele si te vas.
ESPERA = float(os.environ.get("BUDDY_ESPERA_DORMIR") or 90)

# Cuántas letras puede tener mal y seguir valiendo, según lo largo que sea el
# nombre. Se cuenta por distancia de edición y no por porcentaje de parecido:
# probando con porcentajes, "Noba" por "Nova" daba 0,75 y se quedaba fuera por
# poco, que es exactamente la errata que hay que perdonar. En letras se dice
# mucho mejor lo que se quiere: una mal en un nombre normal, dos si es largo.
def _erratas_permitidas(largo):
    if largo >= 7:
        return 2
    if largo >= 4:
        return 1
    return 0        # un nombre de tres letras ya se parece a demasiadas cosas

DESPEDIDAS = (
    "adios", "hasta luego", "hasta ahora", "hasta manana", "hasta pronto",
    "nos vemos", "chao", "ciao", "buenas noches", "me voy", "dejalo",
    "ya esta", "gracias adios", "hasta otra",
)

# "Nova, ..." / "oye Nova" / "¿Nova?" — se quita del principio para que al
# modelo le llegue la pregunta y no el vocativo.
_ARRANQUE = re.compile(r"^(oye|eh|hola|vale|venga)\b[\s,]*", re.I)


def plano(texto):
    """Sin acentos, sin signos y en minúsculas, que es como hay que comparar
    algo que ha pasado por un transcriptor."""
    limpio = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^\w\s]", " ", limpio.lower())
    return " ".join(limpio.split())


def _distancia(a, b):
    """Cuantas letras hay que cambiar, quitar o poner para pasar de a a b."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:      # atajo: ya se pasa de largo
        return 99
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(anterior[j] + 1,        # quitar
                              actual[j - 1] + 1,      # poner
                              anterior[j - 1] + (ca != cb)))   # cambiar
        anterior = actual
    return anterior[-1]


class Vigilia:
    """Lleva la cuenta de si ahora mismo toca atender."""

    def __init__(self, nombre=None, espera=ESPERA):
        self.nombre = (nombre or NOMBRE).strip()
        self.plano = plano(self.nombre)
        self.espera = espera
        self.desde = 0.0            # cuándo se le habló por última vez
        self.despierto = False

    # ------------------------------------------------------------- nombre --
    def _donde_esta_el_nombre(self, palabras):
        """En qué posición aparece su nombre, o None.

        Se mira palabra a palabra y nada más. Hubo aquí una regla que además
        juntaba palabras contiguas, pensando en que Whisper puede partir el
        nombre ("Nova" -> "no va"). Se quitó porque hacía justo lo contrario de
        lo que se busca: con ella, "no va a venir nadie" le despertaba. Una
        frase corriente que le saca de su silencio es mucho peor que perder
        alguna llamada, y de que el nombre llegue entero ya se encarga la pista
        que lleva Whisper.
        """
        objetivo = self.plano
        margen = _erratas_permitidas(len(objetivo))
        for i, p in enumerate(palabras):
            if p == objetivo or _distancia(p, objetivo) <= margen:
                return i, 1
        return None

    def le_llaman(self, frase):
        return self._donde_esta_el_nombre(plano(frase).split()) is not None

    def _sin_el_nombre(self, frase):
        """La frase quitándole el vocativo, para pasársela al modelo."""
        palabras = plano(frase).split()
        donde = self._donde_esta_el_nombre(palabras)
        if donde is None:
            return frase.strip()
        i, largo = donde
        # Se reconstruye desde el texto plano: recortar el original por índices
        # es mucho más frágil de lo que parece en cuanto hay signos.
        resto = " ".join(palabras[:i] + palabras[i + largo:])
        return _ARRANQUE.sub("", resto).strip()

    # --------------------------------------------------------- despedidas --
    def se_despiden(self, frase):
        p = plano(frase)
        if not p:
            return False
        for d in DESPEDIDAS:
            # Al principio o al final: "adios" vale, "no me digas adios" también,
            # pero no queremos que "adiosito a los problemas" cuente por estar
            # la palabra suelta en mitad de una frase larga.
            if p == d or p.startswith(d + " ") or p.endswith(" " + d):
                return True
        return False

    # ------------------------------------------------------------- estado --
    def dormir(self):
        self.despierto = False

    def despertar(self):
        self.despierto = True
        self.desde = time.time()

    def se_ha_aburrido(self):
        """True si lleva demasiado rato despierto sin que le digan nada."""
        return (self.despierto and self.espera > 0
                and time.time() - self.desde > self.espera)

    # ---------------------------------------------------------------- oir --
    def oye(self, frase):
        """Qué hacer con lo que se acaba de oír.

        Devuelve (accion, texto):
            "nada"      no va con él; texto vacío
            "saluda"    le han llamado y ya está; hay que contestar algo corto
            "atiende"   hay que responder a `texto`
            "despide"   se despiden; hay que contestar algo corto y dormirse
        """
        limpia = frase.strip()
        if not limpia:
            return "nada", ""

        llamado = self.le_llaman(limpia)

        if not self.despierto:
            if not llamado:
                return "nada", ""
            self.despertar()
            resto = self._sin_el_nombre(limpia)
            # "Nova" a secas es una llamada; "Nova, qué hora es" ya es
            # una pregunta y sería absurdo contestar "dime" y hacerte repetir.
            if len(resto) < 3:
                return "saluda", ""
            return "atiende", resto

        # Ya despierto
        self.desde = time.time()
        if self.se_despiden(limpia):
            self.dormir()
            return "despide", ""
        return "atiende", self._sin_el_nombre(limpia) if llamado else limpia
