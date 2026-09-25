"""Prueba de cuando atiende y cuando calla.

El grueso de los casos son erratas de transcripcion a proposito: lo que de
verdad va a pasar no es que digas mal su nombre, es que Whisper lo oiga mal.
"""

import despertar

fallos = []


def comprobar(que, condicion, detalle=""):
    print(f"  {'OK  ' if condicion else 'MAL '} {que}{'  -> ' + detalle if detalle else ''}")
    if not condicion:
        fallos.append(que)


v = despertar.Vigilia(nombre="Nova", espera=0)   # espera 0 = no se duerme sola

print("\n== dormido, no va con el ==")
for frase in ("Gracias por ver el video.", "Que hora es?", "Oh!",
              "Pon musica", "no va a venir nadie"):
    a, _ = v.oye(frase)
    comprobar(f"ignora {frase!r}", a == "nada", a)

print("\n== le llaman, con erratas de Whisper ==")
for frase, espera_texto in (
        ("Nova", ""),                       # a secas
        ("nova!", ""),                      # sin mayuscula y con signo
        ("Noba", ""),                       # una letra cambiada
        ("Nova, que hora es?", "que hora es"),
        ("Oye Nova, pon musica", "pon musica"),
        ("¿Nova?", ""),
):
    v.dormir()
    a, t = v.oye(frase)
    esperado = "saluda" if espera_texto == "" else "atiende"
    comprobar(f"{frase!r} -> {esperado}", a == esperado, a)
    if espera_texto:
        comprobar(f"   y le llega {espera_texto!r}", t == espera_texto, repr(t))

print("\n== despierto, atiende sin repetir el nombre ==")
v.dormir(); v.oye("Nova")
for frase in ("Que hora es?", "Y manana?", "Pon los Beatles"):
    a, t = v.oye(frase)
    comprobar(f"atiende {frase!r}", a == "atiende" and t == frase, f"{a}/{t!r}")

print("\n== despedidas ==")
for frase in ("Adios", "adios!", "Hasta luego", "hasta luego Nova",
              "Nos vemos", "chao", "Hasta manana"):
    v.dormir(); v.oye("Nova")
    a, _ = v.oye(frase)
    comprobar(f"{frase!r} le duerme", a == "despide" and not v.despierto, a)

print("\n== lo que NO debe tomarse por despedida ==")
v.dormir(); v.oye("Nova")
for frase in ("Dile adios de mi parte a la bateria",
              "hasta luego no me acuerdo de nada"):
    a, _ = v.oye(frase)
    # La primera lleva "adios" en medio: no cuenta. La segunda empieza por
    # "hasta luego" y si cuenta; lo importante es que la primera no.
    if frase.startswith("Dile"):
        comprobar(f"{frase[:28]!r}... sigue atendiendo", a == "atiende", a)

print("\n== se duerme solo si le dejan de hablar ==")
w = despertar.Vigilia(nombre="Nova", espera=0.4)
w.oye("Nova")
comprobar("despierto tras llamarle", w.despierto)
comprobar("y no se ha aburrido aun", not w.se_ha_aburrido())
import time; time.sleep(0.5)
comprobar("tras el plazo, se aburre", w.se_ha_aburrido())

print("\n== cambiar el nombre funciona ==")
z = despertar.Vigilia(nombre="Aira", espera=0)
comprobar("no responde al viejo", z.oye("Nova, hola")[0] == "nada")
comprobar("responde al nuevo", z.oye("Aira, que hora es")[0] == "atiende")
comprobar("y tolera la errata 'Aura'", despertar.Vigilia("Aira", 0).oye("Aura")[0] == "saluda")

print("\nRESULTADO:", "OK" if not fallos else f"MAL -> {fallos}")
