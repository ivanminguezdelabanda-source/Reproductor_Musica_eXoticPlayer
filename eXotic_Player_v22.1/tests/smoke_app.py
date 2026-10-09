"""Prueba de arranque REAL de eXotic Player (la usa GitHub Actions en Windows).

Abre el programa de verdad (el .py o el .exe compilado), deja que haga la animación de
inicio y se cierra solo. Falla si:
  * no aparece la ventana principal,
  * hay errores en la interfaz,
  * la animación de inicio no llega a verse al menos 1,5 s (el fallo de la v21.2).

Uso:  python tests/smoke_app.py                 (con el código fuente)
      python tests/smoke_app.py --exe RUTA.exe  (con el programa compilado)
"""
import json
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    exe = None
    if "--exe" in sys.argv:
        exe = os.path.abspath(sys.argv[sys.argv.index("--exe") + 1])
    informe = os.path.join(tempfile.mkdtemp(), "informe.json")
    env = dict(os.environ, EXOTIC_SMOKE=informe, EXOTIC_SMOKE_MS="10000")
    cmd = [exe] if exe else [sys.executable, os.path.join(RAIZ, "exotic_player.py")]
    print("Arrancando:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=RAIZ if not exe else os.path.dirname(exe), env=env, timeout=120)
    if not os.path.exists(informe):
        print(f"FALLO: el programa terminó (código {proc.returncode}) sin escribir el informe")
        return 1
    with open(informe, encoding="utf-8") as f:
        datos = json.load(f)
    print(json.dumps(datos, ensure_ascii=False, indent=1)[:3000])
    fallos = []
    if not datos.get("app"):
        fallos.append("la aplicación no llegó a crearse")
    if not datos.get("ventana_visible"):
        fallos.append("la ventana principal no está visible")
    if datos.get("errores"):
        fallos.append(f"{len(datos['errores'])} error(es) en la interfaz")
    eventos = {msg: t for t, msg in datos.get("splash") or []}
    if eventos:                                  # animación activada (lo normal)
        if "app cargada, sigue la animación" not in eventos and "saltada por el usuario" not in eventos:
            fallos.append("la animación de inicio no llegó a mostrar el título")
        if "ventana creada" in eventos and "fin" in eventos and eventos["fin"] - eventos["ventana creada"] < 1.5:
            fallos.append(f"la animación duró solo {eventos['fin'] - eventos['ventana creada']:.2f} s")
    if fallos:
        print("FALLO: " + "; ".join(fallos))
        return 1
    print("OK: eXotic arranca bien")
    return 0


if __name__ == "__main__":
    sys.exit(main())
