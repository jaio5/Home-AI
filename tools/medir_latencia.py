"""Mide cuanto tarda en OIRSE la primera palabra, que es lo que se percibe."""
import asyncio, time
import buddy_pc as B, conversacion
from cerebro import Cerebro
from voz import Voz

class CaraCronometro:
    def __init__(self): self.primera = None; self.t0 = time.time()
    def estado(self, e):
        if e == "H" and self.primera is None: self.primera = time.time() - self.t0
    def emocion(self, m): pass
    def boca(self, v): pass

class OidoFalso:
    def ensordecer(self, _): pass

async def main():
    cerebro = Cerebro(B.MODELO, B.CARACTER, B.EJEMPLOS)
    voz = Voz(B.VOZ_NEURONAL, B.VOZ_LOCAL)
    hist = [{"role": "user", "content": "Cuentame por que el cielo es azul, y sin rollos."}]

    t0 = time.time()
    texto = await asyncio.to_thread(cerebro.pensar, hist)
    tp = time.time() - t0
    await voz.sintetizar(texto)
    print(f"  sin tuberia: primera palabra a los {time.time()-t0:.1f}s "
          f"(pensar {tp:.1f}s)")

    cara = CaraCronometro()
    dicho = await conversacion.responder(cerebro, voz, cara, OidoFalso(), hist)
    print(f"  con tuberia: primera palabra a los {cara.primera:.1f}s")
    print(f"\n  respuesta: {dicho[:130]}")

asyncio.run(main())
