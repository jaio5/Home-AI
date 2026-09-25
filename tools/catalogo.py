"""Catálogo de lo que hay instalado en este ordenador.

En vez de una lista escrita a mano, se descubre lo que existe de verdad: los
accesos directos del menú inicio y los juegos de Steam. Sigue siendo lista
blanca —solo se puede abrir lo que está instalado— pero se mantiene sola.

Se construye una vez al arrancar y se guarda en memoria: recorrer el menú
inicio son unos cientos de archivos y no hace falta hacerlo en cada frase.
"""

import os
import pathlib
import re
import unicodedata
import webbrowser

# Ni desinstaladores, ni manuales, ni notas de version: son accesos directos
# como cualquier otro y no es lo que nadie quiere abrir por voz.
DESCARTAR = re.compile(
    r"desinstalar|uninstall|readme|whatsnew|licen[cs]e|eula|manual|"
    r"documentation|help|release notes|command prompt|reset config|"
    r"factory defaults|rewire|create new project|error reporter|updater|"
    r"actualizaci|\.txt|\.pdf", re.I)

MENUS = [
    pathlib.Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    pathlib.Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
]

STEAM = [
    pathlib.Path(os.environ.get("ProgramFiles(x86)", "")) / "Steam",
    pathlib.Path(os.environ.get("ProgramFiles", "")) / "Steam",
]


def _plano(texto):
    """Sin tildes ni mayúsculas, para comparar lo que se dice con lo que hay."""
    limpio = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(limpio.lower().split())


# ------------------------------------------------------------ aplicaciones ---
def _aplicaciones():
    encontradas = {}
    for menu in MENUS:
        if not menu.is_dir():
            continue
        for atajo in menu.rglob("*.lnk"):
            nombre = atajo.stem
            if DESCARTAR.search(nombre) or DESCARTAR.search(str(atajo)):
                continue
            encontradas.setdefault(_plano(nombre), (nombre, str(atajo), "aplicacion"))
    return encontradas


# ------------------------------------------------------------------ juegos ---
def _bibliotecas_steam():
    """Steam reparte los juegos entre varios discos; las rutas están en un
    archivo de configuración suyo."""
    rutas = []
    for base in STEAM:
        apps = base / "steamapps"
        if not apps.is_dir():
            continue
        rutas.append(apps)
        vdf = apps / "libraryfolders.vdf"
        if vdf.is_file():
            texto = vdf.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'"path"\s+"(.+?)"', texto):
                otra = pathlib.Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
                if otra.is_dir():
                    rutas.append(otra)
    return list(dict.fromkeys(rutas))


def _juegos():
    encontrados = {}
    for apps in _bibliotecas_steam():
        for manifiesto in apps.glob("appmanifest_*.acf"):
            texto = manifiesto.read_text(encoding="utf-8", errors="replace")
            ident = re.search(r'"appid"\s+"(\d+)"', texto)
            nombre = re.search(r'"name"\s+"(.+?)"', texto)
            if not (ident and nombre):
                continue
            titulo = nombre.group(1)
            # No es un juego, es el paquete de librerías que Steam instala solo
            if "redistributable" in titulo.lower():
                continue
            encontrados.setdefault(
                _plano(titulo),
                (titulo, f"steam://rungameid/{ident.group(1)}", "juego"))
    return encontrados


# ---------------------------------------------------------------- catalogo ---
_CATALOGO = None


def catalogo():
    global _CATALOGO
    if _CATALOGO is None:
        _CATALOGO = {**_aplicaciones(), **_juegos()}
    return _CATALOGO


def nombres(tipo=None):
    return sorted(n for n, (_, _, t) in catalogo().items() if tipo in (None, t))


def buscar(consulta, cuantos=4):
    """Candidatos ordenados por lo bien que encajan.

    La voz nunca llega exacta: se dice "witcher" y el juego se llama "The
    Witcher 3: Wild Hunt - Complete Edition". Se puntúa por palabras que
    coinciden, premiando el prefijo y penalizando los nombres muy largos, que
    de otro modo ganarían siempre por tener más palabras.
    """
    pedido = _plano(consulta)
    palabras = [p for p in pedido.split() if len(p) > 1]
    if not palabras:
        return []

    puntuados = []
    for clave, (titulo, destino, tipo) in catalogo().items():
        if pedido == clave:
            puntos = 100
        elif clave.startswith(pedido):
            puntos = 60
        elif pedido in clave:
            puntos = 40
        else:
            puntos = 12 * sum(1 for p in palabras if p in clave)
        if puntos:
            puntos -= len(clave.split()) * 0.5
            puntuados.append((puntos, titulo, destino, tipo))

    puntuados.sort(reverse=True)
    return [(t, d, k) for _, t, d, k in puntuados[:cuantos]]


def abrir(destino):
    if destino.startswith(("steam:", "http", "com.epicgames")):
        webbrowser.open(destino)
    else:
        import sistema
        return sistema.abrir(destino)


if __name__ == "__main__":
    import sys
    for f in (sys.stdout, sys.stderr):
        if hasattr(f, "reconfigure"):
            f.reconfigure(encoding="utf-8", errors="replace")
    c = catalogo()
    juegos = [n for n in c if c[n][2] == "juego"]
    print(f"{len(c)} entradas: {len(c) - len(juegos)} aplicaciones y {len(juegos)} juegos\n")
    for consulta in ("spotify", "witcher", "counter strike", "codigo", "discord",
                     "helldivers", "navegador"):
        print(f"  '{consulta}' -> " +
              ", ".join(f"{t} [{k}]" for t, _, k in buscar(consulta, 3)))
