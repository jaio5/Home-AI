"""Lo poco que de verdad cambia entre Windows y Linux.

Aqui se concentra para que el resto del codigo no tenga que preguntar en que
sistema esta. Cuando algo no existe en el sistema de turno, se dice con una
frase que el companero pueda leer en voz alta, no con una excepcion a media
conversacion.
"""

import os
import pathlib
import subprocess
import sys

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"

# Los ajustes de las dos maquinas (la ficha del agente, donde esta cada cosa)
# viven aqui. Podrian ser variables de entorno y ya, pero exportarlas a mano en
# cada terminal es justo lo que se olvida y luego cuesta media hora entender por
# que el companero no llega al PC. El archivo esta en .gitignore.
AJUSTES = pathlib.Path(__file__).parent.parent / "secretos.env"


def cargar_ajustes(ruta=AJUSTES):
    """Mete secretos.env en el entorno, SIN pisar lo que ya venga puesto.

    Ese orden importa: si alguien arranca con la variable puesta a mano o desde
    un servicio, gana la suya. El archivo es el valor por defecto, no la ley.
    """
    try:
        texto = pathlib.Path(ruta).read_text(encoding="utf-8")
    except OSError:
        return
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip().strip('"').strip("'")
        if clave and clave not in os.environ:
            os.environ[clave] = valor

# Un servidor sin pantalla no tiene escritorio al que mandarle cosas. En Linux
# se nota en que no hay DISPLAY ni WAYLAND_DISPLAY.
HAY_ESCRITORIO = WINDOWS or MAC or bool(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def abrir(ruta):
    """Abre un archivo, una carpeta o un enlace con el programa que le toque.

    os.startfile solo existe en Windows; fuera de alli hay que llamar al
    lanzador del escritorio. Devuelve None si ha ido bien, o el motivo si no.
    """
    destino = str(ruta)
    if not HAY_ESCRITORIO:
        return ("no hay escritorio en esta maquina, asi que no puedo abrir "
                "nada en pantalla")
    try:
        if WINDOWS:
            os.startfile(destino)                          # noqa: S606
        elif MAC:
            subprocess.Popen(["open", destino])
        else:
            # Popen y no run: xdg-open devuelve enseguida, pero con algunos
            # escritorios se queda colgado del proceso hijo y no queremos que
            # eso frene la conversacion.
            subprocess.Popen(["xdg-open", destino],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, AttributeError) as e:
        return str(e)
    return None


def preparar_cuda(manejadores):
    """Pone al alcance las librerias de NVIDIA que instala pip.

    ctranslate2 (el motor de faster-whisper) no las busca solo. Cada sistema lo
    necesita de una forma:

      - Windows: add_dll_directory. Devuelve un manejador, y el directorio deja
        de valer en cuanto ese objeto se recolecta; por eso hay que guardarlos
        en una lista que siga viva (nos costo un rato: cuBLAS cargaba al crear
        el modelo y desaparecia justo al transcribir).
      - Linux: LD_LIBRARY_PATH ya no sirve una vez arrancado el proceso, porque
        el cargador dinamico lo lee al principio y nada mas. Lo que si funciona
        es abrir las .so a mano: quedan cargadas y ctranslate2 las encuentra.

    Sin esto se sigue funcionando, pero en CPU, y con el modelo grande eso pasa
    de medio segundo a varios por frase.
    """
    import site

    if manejadores:
        return

    bases = []
    try:
        bases.append(site.getusersitepackages())
    except Exception:
        pass
    try:
        bases.extend(site.getsitepackages())
    except Exception:
        pass

    for base in bases:
        nvidia = pathlib.Path(base) / "nvidia"
        if not nvidia.is_dir():
            continue

        if WINDOWS:
            for carpeta in sorted(nvidia.glob("*/bin")):
                try:
                    manejadores.append(os.add_dll_directory(str(carpeta)))
                    os.environ["PATH"] = f"{carpeta}{os.pathsep}" + os.environ.get("PATH", "")
                except (OSError, AttributeError):
                    pass
        else:
            import ctypes
            # cuBLAS necesita a cuDNN ya cargado, asi que el orden importa.
            for patron in ("*/lib/libcudnn*.so*", "*/lib/libcublasLt.so*",
                           "*/lib/libcublas.so*", "*/lib/*.so*"):
                for lib in sorted(nvidia.glob(patron)):
                    try:
                        manejadores.append(ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL))
                    except OSError:
                        pass
