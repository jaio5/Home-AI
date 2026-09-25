"""Recorre los estados de la cara para comprobar que responde."""
import math, serial, sys, time

p = serial.Serial('COM3', 115200, timeout=0.2); p.dtr = True
time.sleep(0.5)

def manda(l, s=0.0):
    p.write((l + "\n").encode()); p.flush()
    if s: time.sleep(s)

guion = [
    ("E R", "M N", 2.5, "reposo, neutro"),
    ("E L", "M N", 3.0, "escuchando (el aura late)"),
    ("E P", "M N", 3.5, "pensando (aura girando y puntos)"),
    ("E R", "M F", 2.5, "feliz"),
    ("E R", "M S", 2.0, "sorpresa"),
    ("E R", "M T", 2.0, "triste"),
]
for est, emo, dur, texto in guion:
    print(f"  -> {texto}")
    manda(est); manda(emo)
    time.sleep(dur)

print("  -> hablando (boca siguiendo una onda)")
manda("E H"); manda("M N")
t0 = time.time()
while time.time() - t0 < 5:
    v = int(50 + 50 * math.sin((time.time() - t0) * 9))
    manda(f"B {max(0, v)}")
    time.sleep(0.05)

manda("E R"); manda("M F")
print("\nrespuestas del reloj:", p.read(200).decode('utf-8', 'replace').strip() or "(ninguna)")
p.close()
