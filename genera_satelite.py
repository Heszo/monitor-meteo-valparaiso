"""
Genera las imágenes satelitales fijas de los mapas: une los mosaicos de Esri World Imagery
que cubren cada recuadro de RECUADROS en una sola imagen JPEG en static/, y anota sus
esquinas en static/satelite.json. Los mapas de la app usan esas imágenes (el navegador las
baja una vez y las guarda en caché) en vez de pedir mosaicos cada vez que se mueven.

Se corre a mano, solo si cambia el recuadro o se quiere una imagen más nueva:

    python genera_satelite.py              # todas
    python genera_satelite.py contexto     # solo las nombradas; las demás quedan como están

Los mosaicos de Web Mercator ya vienen en la proyección de los mapas, así que la imagen
calza sin deformarse si se recorta en los bordes de los mosaicos (eso hace este script).
La imagen se oscurece un poco para que los nombres de las estaciones, en blanco, se lean
encima. Las imágenes que van encima de otra se guardan en WebP con los bordes que se desvanecen
(canal alfa), para que se fundan con la de abajo y no se vea el rectángulo.
"""
import io
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageEnhance

import fuentes as F

STATIC = Path(__file__).resolve().parent / "static"
# nombre: (oeste, sur, este, norte, zoom), de abajo hacia arriba. Un contexto amplio a zoom 8 (~480 m por
# píxel), para que el mapa nunca muestre bordes vacíos al alejarse; la región completa a zoom 10 (~120 m) y
# el Gran Valparaíso (de Concón a Villa Alemana), donde más se acerca la gente, a zoom 12 (~30 m), encima de
# las anteriores.
RECUADROS = {
    "contexto": (-76.0, -35.5, -68.0, -30.5, 8),
    "region": (-72.2, -34.1, -69.8, -31.9, 10),
    "gran_valparaiso": (-71.8, -33.2, -71.3, -32.85, 12),
}
BRILLO = 0.8      # < 1 oscurece
CALIDAD = 82      # JPEG y WebP
BORDE = 0.06      # fracción del lado en que se desvanecen las imágenes que van encima de otra


def mosaico(lon, lat, z):
    """(x, y) del mosaico que contiene el punto, como número real."""
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def esquina(x, y, z):
    """(lon, lat) de la esquina noroeste del mosaico (x, y)."""
    n = 2 ** z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def baja(z, x, y):
    url = F.ESRI.format(z=z, x=x, y=y)
    r = requests.get(url, headers=F.UA, timeout=60)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def desvanece(imagen):
    """La imagen con canal alfa: opaca al centro y transparente hacia los bordes (rampa suave de BORDE)."""
    w, h = imagen.size
    def rampa(n):
        d = np.minimum(np.arange(n), np.arange(n)[::-1]) / (BORDE * n)
        return np.clip(d, 0, 1) ** 2 * (3 - 2 * np.clip(d, 0, 1))  # smoothstep
    alfa = np.outer(rampa(h), rampa(w))
    imagen = imagen.convert("RGBA")
    imagen.putalpha(Image.fromarray((alfa * 255).astype(np.uint8)))
    return imagen


def genera(nombre, oeste, sur, este, norte, z, encima=True):
    x0, y0 = (math.floor(v) for v in mosaico(oeste, norte, z))
    x1, y1 = (math.floor(v) for v in mosaico(este, sur, z))
    xs, ys = range(x0, x1 + 1), range(y0, y1 + 1)
    imagen = Image.new("RGB", (256 * len(xs), 256 * len(ys)))
    with ThreadPoolExecutor(max_workers=8) as pool:
        trozos = pool.map(lambda xy: (xy, baja(z, *xy)), [(x, y) for x in xs for y in ys])
        for (x, y), trozo in trozos:
            imagen.paste(trozo, (256 * (x - x0), 256 * (y - y0)))
    imagen = ImageEnhance.Brightness(imagen).enhance(BRILLO)
    if encima:
        archivo = f"satelite_{nombre}.webp"
        desvanece(imagen).save(STATIC / archivo, quality=CALIDAD, method=6)
    else:
        archivo = f"satelite_{nombre}.jpg"
        imagen.save(STATIC / archivo, quality=CALIDAD, optimize=True, progressive=True)
    o, n = esquina(x0, y0, z)
    e, s = esquina(x1 + 1, y1 + 1, z)
    print(f"{archivo}: {imagen.width} × {imagen.height} px, {len(xs) * len(ys)} mosaicos, "
          f"{(STATIC / archivo).stat().st_size / 1e6:.1f} MB")
    # esquinas en el orden que pide la capa "image" de los mapas: NO, NE, SE, SO
    return dict(archivo=archivo, oeste=o, sur=s, este=e, norte=n,
                esquinas=[[o, n], [e, n], [e, s], [o, s]])


if __name__ == "__main__":
    import sys

    pedidas = sys.argv[1:] or list(RECUADROS)
    previas = json.loads((STATIC / "satelite.json").read_text()) if (STATIC / "satelite.json").exists() else {}
    # en el orden de RECUADROS, que es el de las capas del mapa (de abajo hacia arriba)
    # la primera (la de más abajo) va opaca; las demás se desvanecen en los bordes
    salida = {nombre: genera(nombre, *r, encima=i > 0) if nombre in pedidas else previas[nombre]
              for i, (nombre, r) in enumerate(RECUADROS.items())}
    (STATIC / "satelite.json").write_text(json.dumps(salida, indent=1))
    print("Esquinas en static/satelite.json. Imagen: Esri World Imagery.")
