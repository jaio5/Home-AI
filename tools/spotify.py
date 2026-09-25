"""Poner música concreta en Spotify.

Reutiliza la autorización que ya se hizo para el proyecto del reloj: el mismo
refresh token vale, y no tiene sentido pedirla dos veces. Si esas credenciales
no están, las herramientas de Spotify se desactivan solas y el resto sigue
funcionando.

Controlar la reproducción por la API exige cuenta Premium; leer qué suena, no.
"""

import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import sistema

sistema.cargar_ajustes()        # SECRETS se resuelve al importar, ver abajo

# Las credenciales salen de secretos.env, que esta en .gitignore y es el unico
# sitio donde deben estar:
#
#   BUDDY_SPOTIFY_CLIENT_ID=...
#   BUDDY_SPOTIFY_REFRESH_TOKEN=...
#
# Antes se leian directamente del secrets.h del proyecto del reloj, que es donde
# se autorizo en su dia. Funcionaba, pero ataba este proyecto a que el otro
# estuviera al lado —en el servidor Ubuntu no hay ningun reloj— y dejaba una
# credencial viva repartida por dos sitios. Se sigue aceptando como respaldo
# para no romper el montaje de siempre, pero manda el entorno: si esta en
# secretos.env, el .h ni se abre.
SECRETS = pathlib.Path(
    os.environ.get("BUDDY_SPOTIFY_SECRETS")
    or pathlib.Path.home() / "esp32c3-reloj" / "sketches" / "RelojSpotify" / "secrets.h")

_TOKEN = {"valor": None, "caduca": 0.0}


def _del_entorno():
    ident = os.environ.get("BUDDY_SPOTIFY_CLIENT_ID", "").strip()
    refresco = os.environ.get("BUDDY_SPOTIFY_REFRESH_TOKEN", "").strip()
    if ident and refresco and not ident.startswith("<"):
        return ident, refresco
    return None


def _del_header():
    """Respaldo: el secrets.h del reloj, donde se autorizo en su dia."""
    if not SECRETS.is_file():
        return None
    texto = SECRETS.read_text(encoding="utf-8")
    v = {m.group(1): m.group(2)
         for m in re.finditer(r'#define\s+(SPOTIFY_\w+)\s+"([^"]*)"', texto)}
    ident, refresco = v.get("SPOTIFY_CLIENT_ID"), v.get("SPOTIFY_REFRESH_TOKEN")
    if not ident or not refresco or ident.startswith("PON_AQUI"):
        return None
    return ident, refresco


def credenciales():
    return _del_entorno() or _del_header()


def disponible():
    return credenciales() is not None


def _token():
    if _TOKEN["valor"] and time.time() < _TOKEN["caduca"]:
        return _TOKEN["valor"]
    ident, refresco = credenciales()
    # Autorizado con PKCE, asi que no hay secreto: el client_id va en el cuerpo.
    datos = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": refresco,
        "client_id": ident}).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token", data=datos,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.load(r)
    _TOKEN["valor"] = d["access_token"]
    _TOKEN["caduca"] = time.time() + d.get("expires_in", 3600) - 120
    return _TOKEN["valor"]


def _api(metodo, ruta, cuerpo=None):
    req = urllib.request.Request(
        "https://api.spotify.com/v1" + ruta,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        headers={"Authorization": f"Bearer {_token()}",
                 "Content-Type": "application/json"},
        method=metodo)
    with urllib.request.urlopen(req, timeout=12) as r:
        if r.status == 204 or not r.length:
            return None
        return json.load(r)


def _dispositivo():
    """El aparato donde suena o donde puede sonar."""
    equipos = (_api("GET", "/me/player/devices") or {}).get("devices") or []
    if not equipos:
        return None
    activo = next((e for e in equipos if e.get("is_active")), None)
    # Si no hay ninguno activo se prefiere el ordenador, que es donde esta el
    # usuario; el movil podria estar en otra habitacion.
    return activo or next((e for e in equipos if e.get("type") == "Computer"),
                          equipos[0])


def poner(busqueda, tipo="track"):
    """Busca y reproduce. Devuelve un texto para que el compañero lo cuente."""
    if not disponible():
        return ("Spotify no esta configurado. Hay que autorizarlo una vez con "
                "spotify_auth.py en el proyecto del reloj.")
    try:
        consulta = urllib.parse.quote(busqueda)
        res = _api("GET", f"/search?q={consulta}&type={tipo}&limit=1&market=ES")
        elementos = (res or {}).get(f"{tipo}s", {}).get("items") or []
        if not elementos:
            return f"No he encontrado nada en Spotify que se llame '{busqueda}'."
        elegido = elementos[0]

        equipo = _dispositivo()
        if equipo is None:
            return ("No hay ningun dispositivo de Spotify disponible. Abre "
                    "Spotify en el ordenador y vuelve a pedirmelo.")

        cuerpo = ({"uris": [elegido["uri"]]} if tipo == "track"
                  else {"context_uri": elegido["uri"]})
        _api("PUT", f"/me/player/play?device_id={equipo['id']}", cuerpo)

        artistas = ", ".join(a["name"] for a in elegido.get("artists", []))
        # El nombre del equipo se lee fatal en voz alta ("JAVIE esta sonando"),
        # asi que si es este ordenador se dice asi y punto.
        donde = ("en este ordenador" if equipo.get("type") == "Computer"
                 else f"en {equipo['name']}")
        return (f"Ya suena {elegido['name']}"
                + (f" de {artistas}" if artistas else "") + f", {donde}.")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return "Spotify no me deja controlar la reproduccion: hace falta Premium."
        if e.code == 404:
            return "Spotify no tiene ningun reproductor activo ahora mismo."
        return f"Spotify ha respondido {e.code}."
    except Exception as e:
        return f"No he podido con Spotify: {e}"
