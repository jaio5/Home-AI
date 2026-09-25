"""Solo voces con acento de España. Con y sin retoque de prosodia."""
import asyncio, io, time
import numpy as np, sounddevice as sd, soundfile as sf
import edge_tts

FRASE = ("Pues mira, ni idea, pero suena interesante. Dame un segundo, "
         "que lo miro y te cuento. No te vayas.")

async def edge(voz, etiqueta, **extra):
    t0 = time.time(); datos = b""
    try:
        async for t in edge_tts.Communicate(FRASE, voz, **extra).stream():
            if t["type"] == "audio": datos += t["data"]
        a, f = sf.read(io.BytesIO(datos), dtype="float32")
    except Exception as e:
        print(f"  {etiqueta}: fallo ({str(e)[:50]})"); return
    if a.ndim > 1: a = a[:, 0]
    print(f"  {etiqueta}  ({len(a)/f:.1f}s, {time.time()-t0:.2f}s)")
    sd.play(a, f); sd.wait(); await asyncio.sleep(0.4)

async def piper():
    import wave
    from piper import PiperVoice
    ruta = "voces/es_ES-davefx-medium.onnx"
    try:
        v = PiperVoice.load(ruta)
    except Exception as e:
        print(f"  6. Piper local: no disponible ({str(e)[:50]})"); return
    buf = io.BytesIO()
    t0 = time.time()
    with wave.open(buf, "wb") as w: v.synthesize_wav(FRASE, w)
    buf.seek(0)
    with wave.open(buf) as w:
        frec = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)/32768
    print(f"  6. Piper local, castellano  ({len(a)/frec:.1f}s, {time.time()-t0:.2f}s)")
    sd.play(a, frec); sd.wait()

async def main():
    await edge("es-ES-ElviraNeural", "1. Elvira tal cual")
    await edge("es-ES-ElviraNeural", "2. Elvira mas viva", rate="+12%", pitch="+6Hz")
    await edge("es-ES-AlvaroNeural", "3. Alvaro tal cual")
    await edge("es-ES-AlvaroNeural", "4. Alvaro mas vivo", rate="+10%", pitch="+4Hz")
    await edge("es-ES-XimenaNeural", "5. Ximena")
    await piper()

asyncio.run(main())
