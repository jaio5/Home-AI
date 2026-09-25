#!/usr/bin/env bash
# Deja una maquina Ubuntu limpia lista para ser el cerebro del companero.
#
#   bash instalar_servidor.sh
#
# No toca nada que ya este puesto: se puede volver a lanzar sin miedo.

set -euo pipefail
cd "$(dirname "$0")"

echo "== paquetes del sistema =="
# libportaudio2 es el que de verdad falta siempre: sin el, sounddevice importa
# pero no ve ni el microfono ni los altavoces, y el fallo que da no lo dice.
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-pip libportaudio2 ffmpeg curl

echo
echo "== entorno de Python =="
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip -q
./.venv/bin/python -m pip install -r requirements.txt

echo
echo "== Ollama =="
if command -v ollama >/dev/null 2>&1; then
    echo "  ya estaba instalado"
else
    curl -fsSL https://ollama.com/install.sh | sh
fi
# qwen3 es el que piensa y habla; moondream el que mira la pantalla. Los dos
# tardan un rato en bajar la primera vez.
ollama pull qwen3:8b
ollama pull moondream

echo
echo "== voz local de respaldo =="
mkdir -p tools/voces
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium
for f in es_ES-davefx-medium.onnx es_ES-davefx-medium.onnx.json; do
    if [ -s "tools/voces/$f" ]; then
        echo "  $f ya esta"
    else
        curl -fL "$BASE/$f?download=true" -o "tools/voces/$f"
    fi
done

echo
echo "== comprobacion =="
./.venv/bin/python - <<'PY'
import sys, pathlib
sys.path.insert(0, "tools")
import sistema, cerebro
print("  escritorio:", sistema.HAY_ESCRITORIO, "(False esta bien en un servidor)")
print("  Ollama en :", cerebro.URL_BASE)
ok, msg = cerebro.Cerebro("qwen3:8b", "", "").revisar()
print("  ", msg[:100])
voz = pathlib.Path("tools/voces/es_ES-davefx-medium.onnx")
print("  voz local :", "ok" if voz.is_file() else "FALTA")
PY

cat <<'FIN'

Listo. Lo que queda por hacer a mano:

  1. Copia secretos.env desde el PC (lleva la ficha, tiene que ser la misma).
  2. En ese archivo, descomenta la linea BUDDY_AGENTE=http://<ip-del-pc>:8788
  3. Enchufa aqui el microfono y los altavoces: la placa no lleva audio.
  4. Arranca:   ./.venv/bin/python tools/buddy_pc.py

FIN
