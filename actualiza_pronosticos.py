"""
Baja de Open-Meteo los pronósticos de todos los sitios (7 modelos + super-ensamble,
DIAS_PUBLICADOS días hacia atrás y hacia adelante) y los guarda como parquet en la
carpeta indicada. Lo corre la GitHub Action .github/workflows/pronosticos.yml cada
hora y publica el resultado en la rama "datos", que es lo que lee la app.

Con ~70 sitios no conviene una consulta por sitio: se piden en lotes (Open-Meteo acepta
varias coordenadas en una misma consulta). Los 7 modelos se piden en cada estación y el
super-ensamble una vez por nodo (ver F.NODO), que es lo que cuida la cuota gratuita.

    python actualiza_pronosticos.py salida/
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import fuentes as F

POR_LOTE = 8             # puntos por consulta (una respuesta del ensamble IFS de 8 puntos pesa ~4 MB)
EN_PARALELO = 2          # lotes de modelos a la vez
PAUSA_ENSAMBLE_S = 60    # un lote de ensamble (8 nodos × 143 miembros) roza el límite de 600 consultas por minuto
PRESUPUESTO_S = 20 * 60  # pasado este tiempo se publica lo que haya (el job corta a los 40 min)


def en_lotes(ids, funcion, inicio, nombre, pausa=0):
    """{id: resultado} de funcion(puntos) aplicada por lotes a los sitios 'ids', con una segunda
    pasada para los lotes que fallaron. Con pausa > 0 los lotes van de a uno, separados por 'pausa'
    segundos. Devuelve también los ids que quedaron sin respuesta."""
    hechos, pendientes = {}, list(ids)

    def uno(lote):
        if time.monotonic() - inicio > PRESUPUESTO_S:
            return lote, None, "sin tiempo"
        try:
            return lote, funcion([(F.SITIO[i]["lat"], F.SITIO[i]["lon"]) for i in lote]), None
        except F.OpenMeteoError as ex:
            return lote, None, str(ex)

    for pasada in (1, 2):
        if not pendientes:
            break
        if pasada == 2:
            time.sleep(60)
        lotes = [pendientes[k:k + POR_LOTE] for k in range(0, len(pendientes), POR_LOTE)]
        if pausa:
            resultados = []
            for k, lote in enumerate(lotes):
                if k:
                    time.sleep(pausa)
                resultados.append(uno(lote))
        else:
            with ThreadPoolExecutor(max_workers=EN_PARALELO) as pool:
                resultados = list(pool.map(uno, lotes))
        pendientes = []
        for lote, res, err in resultados:
            nombres = ", ".join(F.SITIO[i]["nombre"] for i in lote)
            if res is None:
                pendientes.extend(lote)
                print(f"falla [{nombre} {pasada}] {nombres}: {err[:160]}")
            else:
                hechos.update(zip(lote, res))
                print(f"ok    [{nombre} {pasada}] {nombres}")
    return hechos, pendientes


def main(carpeta):
    inicio = time.monotonic()
    pasado = futuro = F.DIAS_PUBLICADOS
    det, sin_det = en_lotes([s["id"] for s in F.SITIOS], lambda p: F.deterministas(p, pasado, futuro),
                            inicio, "modelos")
    nodos = sorted(set(F.NODO.values()))
    ens, sin_ens = en_lotes(nodos, lambda p: F.ensamble(p, pasado, futuro), inicio, "ensamble",
                            pausa=PAUSA_ENSAMBLE_S)

    # un sitio sin ensamble se publica igual, solo con los 7 modelos (sin banda ni miembros de lluvia)
    por_sitio = {sid: F.resumen_pronostico(d, ens.get(F.NODO[sid], {})) for sid, d in det.items()}
    if not por_sitio:
        sys.exit("Ningún sitio respondió; se mantiene la copia publicada anterior.")
    F.guarda_pronosticos(por_sitio, carpeta, datetime.now(timezone.utc).isoformat(timespec="seconds"), F.NODO)
    avisos = [f"sin modelos: {', '.join(F.SITIO[i]['nombre'] for i in sin_det)}" if sin_det else "",
              f"sin ensamble en los nodos: {', '.join(F.SITIO[i]['nombre'] for i in sin_ens)}" if sin_ens else ""]
    print(f"Guardado en {carpeta}: {len(por_sitio)} sitios, {len(ens)}/{len(nodos)} nodos de ensamble, "
          f"en {time.monotonic() - inicio:.0f} s" + "".join(f" ({a})" for a in avisos if a))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "salida")
