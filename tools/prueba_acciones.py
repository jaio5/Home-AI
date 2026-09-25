import sys
sys.coinit_flags = 0
for f in (sys.stdout, sys.stderr):
    if hasattr(f, "reconfigure"): f.reconfigure(encoding="utf-8", errors="replace")
import asyncio, time
import buddy_pc as B, conversacion, herramientas
from cerebro import Cerebro

class Muda:
    def estado(self, e): pass
    def emocion(self, m): pass
    def boca(self, v): pass
    def ensordecer(self, _): pass
class VozMuda:
    async def sintetizar(self, t):
        import numpy as np; return np.zeros(800, dtype=np.float32), 24000

PETICIONES = sys.argv[1:] or [
    "Que juegos tengo instalados?",
    "Pon Extremoduro en Spotify",
    "Abre el Discord",
    "Que hora es?",
]

async def main():
    cerebro = Cerebro(B.MODELO, B.CARACTER, B.EJEMPLOS,
                      herramientas=herramientas.esquemas())
    for p in PETICIONES:
        t0 = time.time()
        r = await conversacion.responder(cerebro, VozMuda(), Muda(), Muda(),
                                         [{"role": "user", "content": p}])
        print(f'  "{p}"  ({time.time()-t0:.1f}s)\n      {r[:150]}\n')

asyncio.run(main())
