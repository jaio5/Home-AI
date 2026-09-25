"""Acceso a los archivos del ordenador: buscar, listar, leer y abrir.

Tres decisiones que conviene tener claras:

  - Solo lectura. Puede buscar, mirar dentro y abrir con el programa que
    corresponda, pero no escribe, no mueve y no borra nada. Un modelo local
    interpretando voz transcrita no debería tener permiso para tocar archivos;
    si algún día hace falta, se añade una función acotada y se habla.

  - Solo tus carpetas. Escritorio, Documentos, Descargas, Imágenes, Vídeos,
    Música y las carpetas de los proyectos. Ni Windows, ni Archivos de
    programa, ni AppData: ahí no hay nada que el compañero deba mirar y sí
    mucho ruido.

  - Los archivos con pinta de guardar credenciales no se leen. El compañero
    habla EN VOZ ALTA: leerle un `.env` o una clave privada a la habitación es
    justo lo que no queremos. Se dice que existe y ahí se queda.
"""

import os
import pathlib
import re
import time
import unicodedata

INICIO = pathlib.Path.home()

RAICES = [d for d in (
    INICIO / "Desktop", INICIO / "OneDrive" / "Escritorio", INICIO / "Documents",
    INICIO / "Downloads", INICIO / "Pictures", INICIO / "Videos",
    INICIO / "Music", INICIO / "esp32-buddy", INICIO / "esp32c3-reloj",
) if d.is_dir()]

# Carpetas que no aportan nada y sí muchísimo ruido y tiempo de recorrido.
SALTAR = {
    "appdata", "node_modules", ".git", "__pycache__", "venv", ".venv",
    "$recycle.bin", "system volume information", ".cache", "dist", "build",
    ".next", "target", "obj", "bin", "packages", ".gradle", ".idea",
}

# Nada de leer esto en voz alta.
SENSIBLE = re.compile(
    r"(^\.env|secrets?\.|credential|password|passwd|id_rsa|id_ed25519|"
    r"\.pem$|\.key$|\.pfx$|\.p12$|token|\.kdbx$)", re.I)

TEXTO = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".csv", ".log", ".html", ".css", ".xml", ".java", ".c",
    ".cpp", ".h", ".hpp", ".cs", ".sh", ".bat", ".ps1", ".sql", ".rs", ".go",
}

# Las carpetas de Windows tienen nombre en ingles aunque el explorador las
# muestre traducidas. Si pides "descargas" hay que ir a Downloads.
ALIAS = {
    "descargas": "Downloads", "escritorio": "Desktop", "documentos": "Documents",
    "imagenes": "Pictures", "fotos": "Pictures", "videos": "Videos",
    "musica": "Music", "download": "Downloads", "desktop": "Desktop",
}

LIMITE_SEGUNDOS = 4.0        # tope de busqueda, para no colgar la conversacion
LIMITE_CARACTERES = 3000     # lo que se le devuelve al modelo de un archivo


def _plano(texto):
    limpio = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return limpio.lower()


def _permitida(ruta):
    """Solo dentro de las raices permitidas, y sin trucos con '..'."""
    try:
        resuelta = pathlib.Path(ruta).resolve()
    except Exception:
        return None
    for raiz in RAICES:
        try:
            resuelta.relative_to(raiz.resolve())
            return resuelta
        except ValueError:
            continue
    return None


def _recorrer(raices, limite=LIMITE_SEGUNDOS):
    """Recorre con plazo. Un disco lleno tarda minutos en recorrerse entero y
    nadie va a esperar callado mientras tanto."""
    fin = time.time() + limite
    pendientes = list(raices)
    while pendientes:
        if time.time() > fin:
            return
        carpeta = pendientes.pop(0)
        try:
            with os.scandir(carpeta) as entradas:
                for e in entradas:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name.lower() not in SALTAR and not e.name.startswith("."):
                                pendientes.append(e.path)
                        else:
                            yield pathlib.Path(e.path)
                    except OSError:
                        continue
        except (PermissionError, OSError):
            continue


def buscar(nombre, cuantos=8):
    """Archivos cuyo nombre encaje, ordenados por lo bien que encajan."""
    palabras = [p for p in re.split(r"\W+", _plano(nombre)) if len(p) > 1]
    if not palabras:
        return []

    hallazgos = []
    for ruta in _recorrer(RAICES):
        nom = _plano(ruta.name)
        aciertos = sum(1 for p in palabras if p in nom)
        if not aciertos:
            continue
        puntos = aciertos * 10
        if nom.startswith(palabras[0]):
            puntos += 15
        if _plano(ruta.stem) == " ".join(palabras):
            puntos += 40
        hallazgos.append((puntos, ruta))

    hallazgos.sort(key=lambda x: (-x[0], len(str(x[1]))))
    return [r for _, r in hallazgos[:cuantos]]


def _describir(ruta):
    try:
        tam = ruta.stat().st_size
    except OSError:
        tam = 0
    if tam > 1024 * 1024:
        medida = f"{tam / 1024 / 1024:.1f} MB"
    elif tam > 1024:
        medida = f"{tam / 1024:.0f} KB"
    else:
        medida = f"{tam} bytes"
    try:
        donde = ruta.parent.relative_to(INICIO)
    except ValueError:
        donde = ruta.parent
    return f"{ruta.name} ({medida}, en {donde})"


def buscar_texto(nombre):
    encontrados = buscar(nombre)
    if not encontrados:
        return f"No he encontrado ningun archivo que se parezca a '{nombre}'."
    if len(encontrados) == 1:
        return "He encontrado " + _describir(encontrados[0]) + "."
    lista = "; ".join(_describir(r) for r in encontrados[:5])
    return f"He encontrado {len(encontrados)}: {lista}."


def _resolver_carpeta(carpeta):
    """Acepta ruta, nombre en ingles o nombre en castellano."""
    destino = _permitida(carpeta)
    if destino is not None and destino.is_dir():
        return destino

    pedido = _plano(carpeta).strip(" /\\")
    nombre = ALIAS.get(pedido, carpeta)

    for raiz in RAICES:                       # una de las carpetas principales
        if _plano(raiz.name) == _plano(nombre):
            return raiz
    for raiz in RAICES:                       # o una subcarpeta suya
        try:
            for hijo in raiz.iterdir():
                if hijo.is_dir() and _plano(hijo.name) == _plano(nombre):
                    return hijo
        except (PermissionError, OSError):
            continue
    return None


def listar(carpeta=""):
    destino = _resolver_carpeta(carpeta) if carpeta else None
    if carpeta and destino is None:
        return (f"No encuentro ninguna carpeta llamada '{carpeta}'. Puedo mirar "
                f"en: " + ", ".join(r.name for r in RAICES) + ".")
    if destino is None:
        return "Puedo mirar en: " + ", ".join(r.name for r in RAICES) + "."
    if not destino.is_dir():
        return f"'{destino.name}' no es una carpeta."

    try:
        cosas = sorted(destino.iterdir(), key=lambda r: (r.is_file(), r.name.lower()))
    except PermissionError:
        return f"No tengo permiso para mirar dentro de {destino.name}."

    carpetas = [c.name for c in cosas if c.is_dir()][:10]
    ficheros = [f.name for f in cosas if f.is_file()][:15]
    partes = []
    if carpetas:
        partes.append("carpetas: " + ", ".join(carpetas))
    if ficheros:
        partes.append("archivos: " + ", ".join(ficheros))
    if not partes:
        return f"{destino.name} esta vacia."
    return f"En {destino.name} hay " + "; ".join(partes) + "."


def leer(nombre, maximo=LIMITE_CARACTERES):
    """Contenido de un archivo de texto, buscandolo por nombre si hace falta."""
    ruta = _permitida(nombre)
    if ruta is None or not ruta.is_file():
        candidatos = buscar(nombre, cuantos=3)
        if not candidatos:
            return f"No encuentro ningun archivo llamado '{nombre}'."
        ruta = candidatos[0]

    if SENSIBLE.search(ruta.name):
        return (f"He encontrado {ruta.name}, pero tiene pinta de guardar "
                f"credenciales y no lo voy a leer en voz alta. Abrelo tu si "
                f"quieres verlo.")

    if ruta.suffix.lower() not in TEXTO:
        return (f"{ruta.name} no es un archivo de texto, asi que no puedo "
                f"leertelo. Puedo abrirlo con el programa que le corresponda.")

    try:
        contenido = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"No he podido abrir {ruta.name}: {e}"

    recortado = len(contenido) > maximo
    if recortado:
        contenido = contenido[:maximo]
    aviso = " (solo el principio, el archivo es largo)" if recortado else ""
    return f"Contenido de {ruta.name}{aviso}:\n{contenido}"


def abrir(nombre):
    ruta = _permitida(nombre)
    if ruta is None or not ruta.exists():
        candidatos = buscar(nombre, cuantos=1)
        if not candidatos:
            return f"No encuentro '{nombre}' en tus carpetas."
        ruta = candidatos[0]
    import sistema
    fallo = sistema.abrir(ruta)
    if fallo:
        return f"No he podido abrir {ruta.name}: {fallo}"
    return f"Abriendo {ruta.name}."
