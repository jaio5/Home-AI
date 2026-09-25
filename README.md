# Compañero de IA

Una carita en una pantalla redonda que oye, piensa y responde. El modelo corre
en local: nada de lo que dices sale de casa.

```
   ESP32 (la cara)            servidor Ubuntu               tu PC Windows
   ───────────────            ───────────────               ─────────────
   pantalla redonda   ◀─WiFi─  micro + Whisper
   táctil                      Ollama + voz        ──HTTP──▶ agente_pc.py
                               reparte el trabajo             ├ ver la pantalla
                                                              ├ Spotify, volumen
                                                              └ abrir juegos y apps
```

Las tres piezas son opcionales por separado: todo junto en el Windows también
funciona, y es como está montado por defecto.

## Lo que cada trozo puede y no puede hacer

**La placa es cara y táctil, nada más.** No lleva micrófono, ni altavoz, ni
códec de audio, y el único conector que saca pines (`P1`, SH1.0 de 4) son GND,
3V3, TX y RX. Un micro I2S necesitaría cuatro GPIO libres y solo hay dos, que
además son la consola serie. **El micrófono y los altavoces van siempre en la
máquina que ejecuta `buddy_pc.py`.** Lo que gana la placa con el WiFi es poder
estar en otra habitación.

## Arrancarlo

Los ajustes salen de **`secretos.env`** (plantilla: `secretos.env.ejemplo`), que
se lee solo. No hay que exportar variables a mano. Si aun así pones una en el
entorno, esa gana: el archivo es el valor por defecto, no la ley.

### Todo en un ordenador (lo más simple)

```
arrancar.cmd            la cara llama por WiFi
arrancar.cmd COM3       la cara va por cable USB
```

Sin `BUDDY_AGENTE` en `secretos.env` no se reparte nada y todo se ejecuta donde
estés. Por eso el montaje de siempre sigue funcionando igual.

### Cerebro en el servidor, manos en el PC

En el **Windows**, doble clic en `arrancar_agente.cmd`. Nada más: la ficha ya
está en `secretos.env`.

Hace falta **una regla de firewall**, o Windows bloquea el puerto y el servidor
no llega. Acotada a la red local, en PowerShell **como administrador**:

```powershell
New-NetFirewallRule -DisplayName 'Buddy - agente de IA (8788)' `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8788 `
  -RemoteAddress LocalSubnet -Profile Private,Domain
```

En el **servidor Ubuntu**:

```
bash instalar_servidor.sh       # paquetes, Python, Ollama y la voz local
# copia secretos.env desde el PC y descomenta la línea BUDDY_AGENTE
./.venv/bin/python tools/buddy_pc.py
```

Para que arranque solo al encender, está `companero.service` (systemd); las
instrucciones van dentro del propio archivo.

### La placa

Rellena `sketches/CaraIA/secretos.h` (copia de `secretos.ejemplo.h`) con la WiFi
y la IP del servidor, y flashea:

```
arduino-cli compile --fqbn esp32:esp32:esp32c3 --upload --port COM3 sketches/CaraIA
```

Con el SSID vacío la radio ni se enciende y va solo por cable, que es como está
ahora mismo.

## Seguridad

- **El agente no arranca sin ficha.** Una puerta abierta y olvidada en la red de
  casa es justo lo que no queremos.
- **Solo la lista `herramientas.EN_EL_PC`.** No hay forma de mandar un comando,
  una ruta ni código: solo se pide una herramienta por su nombre. Está toda
  junta en un sitio, a propósito, para poder auditarla de un vistazo.
- **Los archivos son de solo lectura** y solo tus carpetas. Los que tienen pinta
  de guardar credenciales no se leen: el compañero habla en voz alta.
- **Red local.** La regla del firewall está acotada a `LocalSubnet` a propósito.
  No le abras un puerto en el router. Si el servidor acaba fuera de casa, eso se
  hace por VPN.

### Dónde van las claves

**Todas en `secretos.env`**, que está en `.gitignore`: la ficha del agente y las
credenciales de Spotify. En `secretos.env.ejemplo`, que sí se versiona, solo
huecos. La contraseña del WiFi va en `sketches/CaraIA/secretos.h`, también
ignorado.

Como el repositorio es público y en git borrar algo después no basta —se queda
en el historial—, hay un hook que corta el commit si una clave se cuela.
Actívalo una vez por copia del repositorio:

```
git config core.hooksPath .githooks
```

Comprueba dos cosas: que no entren `secretos.env` ni `secretos.h` (ni forzados
con `git add -f`), y que ningún valor de `secretos.env` aparezca en lo que vas a
commitear. Eso último es lo que pilla el error típico: pegar la clave buena en
el archivo de ejemplo.

El refresh token de Spotify es una credencial **viva**: con él se entra a tu
cuenta sin contraseña y no caduca hasta que lo revoques, en
[spotify.com/account/apps](https://www.spotify.com/account/apps/).

## Cosas que costaron encontrar

1. **La radio del ESP32 reinicia la placa** si se enciende a la vez que el
   panel. No es pánico ni watchdog: es reset por POWERON, o sea corriente. Se
   arranca la última y a 11 dBm.
2. **Sin `setNoDelay` la cara habla con retraso.** La boca manda ~30 mensajes
   por segundo de 6 bytes y Nagle los agrupa. Hay que desactivarlo en los dos
   extremos.
3. **La dirección de Ollama no es fija.** Con Ollama dentro de WSL, quien abre
   el puerto en Windows es `wslrelay`, y según cómo arranque escucha en IPv4 o
   solo en IPv6. Clavar `127.0.0.1` deja al compañero mudo la mitad de las
   veces. `cerebro.py` prueba las dos una vez al arrancar y lo recuerda.
4. **`faster-whisper` y `winrt` no pueden convivir** en el mismo proceso: se
   caen con segfault, con GPU y con CPU. Por eso el oído va aparte.
5. **En Linux, `LD_LIBRARY_PATH` no vale** para las librerías de NVIDIA: el
   cargador dinámico lo lee al arrancar el proceso y ya. Hay que abrir las `.so`
   a mano o Whisper se cae a CPU en silencio. En Windows es `add_dll_directory`,
   y hay que **guardar los manejadores** o cuBLAS desaparece al transcribir.
6. **`qwen3` razonando en alto rompe las llamadas a herramientas**: 6 de 6
   aciertos sin pensar, 1 de 6 pensando. Va con `think: False`.
7. **Los ejemplos de tono hacen que se invente lo que hay en la pantalla.** Se
   quitan cuando toca decidir herramienta y se ponen cuando toca hablar.
8. **El modelo de visión tarda 20 s la primera vez.** Tanto `buddy_pc.py` como
   `agente_pc.py` lo precalientan al arrancar.
9. **La voz tiene que ser `es-ES`.** Las multilingües y las `es-MX` hablan
   perfecto pero con acento que no es de aquí.

## Pruebas

```
python tools/prueba_red.py       # el transporte de la cara, sin placa
python tools/prueba_agente.py    # el reparto servidor/PC y la puerta cerrada
python tools/prueba_acciones.py  # las herramientas
```
