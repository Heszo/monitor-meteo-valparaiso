"""
Descarga y ordena los datos del monitor: observaciones (VIPNet DGA/MOP y
METAR de Torquemada, Rodelillo y Santo Domingo) y pronósticos (7 modelos deterministas y el
super-ensamble de 143 miembros, ambos vía Open-Meteo).

Todas las series quedan en hora local de Chile (America/Santiago), sin zona
horaria, en pasos horarios. El valor de la hora T es:
- lluvia: lo caído en la hora que TERMINA en T (misma convención que Open-Meteo);
- el resto: el valor instantáneo más cercano a T (media de la hora que termina en T
  para las estaciones VIPNet, que miden cada 30 min).
"""
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ZONA = ZoneInfo("America/Santiago")
UA = {"User-Agent": "monitor-meteo-valparaiso (divulgación; github.com/Heszo)"}
URL_VIPNET = "https://vipnet.mop.gob.cl/v1/vipnet/estacion/valores"
URL_METAR = "https://aviationweather.gov/api/data/metar"
URL_OM = "https://api.open-meteo.com/v1/forecast"
URL_ENS = "https://ensemble-api.open-meteo.com/v1/ensemble"
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# ------------------------------------------------------------------ catálogo
# clave: dict(nombre, unidad, om = variable de Open-Meteo, vipnet = tipoEstacion,
#            metar = columna del METAR, ens = si el super-ensamble la trae)
VARIABLES = {
    "temperatura": dict(nombre="Temperatura", unidad="°C", om="temperature_2m", vipnet=1,
                        metar="temperatura", decimales=1),
    "humedad": dict(nombre="Humedad relativa", unidad="%", om="relative_humidity_2m", vipnet=4,
                    metar="humedad", decimales=0),
    "viento": dict(nombre="Viento medio (10 m)", unidad="km/h", om="wind_speed_10m", vipnet=5,
                   metar="viento", decimales=0),
    "rafaga": dict(nombre="Ráfaga (10 m)", unidad="km/h", om="wind_gusts_10m", vipnet=None,
                   metar="rafaga", decimales=0),
    "direccion": dict(nombre="Dirección del viento", unidad="°", om="wind_direction_10m", vipnet=None,
                      metar="direccion", decimales=0, sin_ensamble=True),
    "presion": dict(nombre="Presión al nivel del mar", unidad="hPa", om="pressure_msl", vipnet=None,
                    metar="presion", decimales=1),
    "precipitacion": dict(nombre="Precipitación", unidad="mm/h", om="precipitation", vipnet=0,
                          metar=None, decimales=1),
}
# El estado del tiempo (código WMO de cada modelo) va aparte: no es una magnitud que se pueda
# promediar, comparar con una estación ni pedir al ensamble.
OM_ESTADO = "weather_code"

MODELOS = {
    "gfs_seamless": ("GFS", "NOAA", "#1f77b4"),
    "ecmwf_ifs025": ("IFS", "ECMWF", "#d62728"),
    "icon_seamless": ("ICON", "DWD", "#2ca02c"),
    "gem_seamless": ("GEM", "Canadá", "#9467bd"),
    "jma_seamless": ("GSM", "JMA", "#8c564b"),
    "ukmo_seamless": ("UM", "UK Met Office", "#e377c2"),
    "meteofrance_seamless": ("ARPEGE", "Météo-France", "#ff7f0e"),
}
ENSAMBLES = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless", "gem_global"]  # 31+51+40+21 = 143

# Sitios: los METAR de Torquemada (SCVM, Concón), Rodelillo (SCRD, Valparaíso) y Santo Domingo (SCSN), y las
# estaciones VIPNet de la Región de Valparaíso continental que entregan datos (catálogo con región 5, verificado
# el 20/10/2026 con 7 y 90 días de datos; límites de static/comunas_valparaiso.geojson). "vars" = variables que
# mide cada una. Quedan fuera:
# - Isla de Pascua y Juan Fernández: Rapa Nui (2 estaciones VIPNet) y un METAR insular están a
#   cientos de kilómetros del continente y harían inútil el encuadre de los mapas;
# - sin datos esa semana: Fundo Las Dos Puertas, Las Puertas y los glaciares Juncal Norte y León Negro (EMAM);
# - el pluviómetro de Rinconada San Juan (23 mm en 90 días contra 91-200 mm en las estaciones de alrededor;
#   sus demás variables se usan);
# - humedad que no se comporta como tal (correlación con la temperatura mayor que -0,6 o variación diaria
#   menor de 5 puntos): fija en 100 % o en 96-100 % (Lago Peñuelas, Embalse Lliu-Lliu, Lo Rojas, El Cobre,
#   Laguna de Zapallar, Longotoma, Artificio, Las Piedras), casi plana (Colliguay, Quillota, La Viña, Las
#   Colmenas, El Salvador) o sin ciclo diario (Nacimiento del Sobrante); Portillo informa 5 datos por semana;
# - estaciones a menos de ~2 km de otra que mide lo mismo o más, para no tapar nombres en el mapa: Río Putaendo
#   en Resguardo Los Patos y Río Rocín bajo el Embalse Chacrilla (junto a Resguardo Los Patos), Río Alicahue en
#   Colliguay (junto a Alicahue), Río Petorca en Peñón (junto a Hierro Viejo), Río Sobrante en Piñadero (junto a
#   El Trapiche) y Estero Riecillo (junto a Riecillos, y su humedad era 4-30 %).
# Grupos: costa (al oeste de 71,25° O), valle (al este, bajo los 1000 m) y cordillera (1000 m o más). "comuna": la
# comuna donde cae la estación según los límites de la BCN.
SITIOS = [
    dict(id="torquemada", nombre="Torquemada (Concón)", fuente="metar", codigo="SCVM", comuna="Concón",
         lat=-32.9470, lon=-71.4790, alt=136, grupo="costa", vars=["temperatura", "humedad", "viento", "rafaga", "direccion", "presion"]),
    dict(id="aerodromo_rodelillo", nombre="Rodelillo (aeródromo)", fuente="metar", codigo="SCRD", comuna="Valparaíso",
         lat=-33.0680, lon=-71.5570, alt=342, grupo="costa", vars=["temperatura", "humedad", "viento", "rafaga", "direccion", "presion"]),
    dict(id="santo_domingo", nombre="Santo Domingo", fuente="metar", codigo="SCSN", comuna="Santo Domingo",
         lat=-33.6560, lon=-71.6150, alt=73, grupo="costa", vars=["temperatura", "humedad", "viento", "rafaga", "direccion", "presion"]),
    dict(id="las_colmenas", nombre="Las Colmenas", fuente="vipnet", codigo="05120004-7", comuna="La Ligua",
         lat=-32.3104, lon=-71.2587, alt=80, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="pozo_estero_guaquen", nombre="Pozo Estero Guaquén", fuente="vipnet", codigo="05000005-2", comuna="La Ligua",
         lat=-32.3336, lon=-71.4208, alt=25, grupo="costa", vars=["precipitacion"]),
    dict(id="longotoma", nombre="Longotoma", fuente="vipnet", codigo="05120006-3", comuna="La Ligua",
         lat=-32.3931, lon=-71.3717, alt=20, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="pozo_quebradilla", nombre="Pozo Quebradilla", fuente="vipnet", codigo="05221015-1", comuna="La Ligua",
         lat=-32.4847, lon=-71.2586, alt=67, grupo="costa", vars=["precipitacion"]),
    dict(id="laguna_de_zapallar", nombre="Laguna de Zapallar", fuente="vipnet", codigo="05310001-5", comuna="Zapallar",
         lat=-32.6238, lon=-71.4075, alt=50, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="puchuncavi", nombre="Puchuncaví", fuente="vipnet", codigo="05320012-5", comuna="Puchuncaví",
         lat=-32.6828, lon=-71.4142, alt=77, grupo="costa", vars=["precipitacion"]),
    dict(id="estero_quintero_en_valle_alegre", nombre="Estero Quintero en Valle Alegre", fuente="vipnet", codigo="05320001-K", comuna="Quintero",
         lat=-32.8011, lon=-71.4195, alt=40, grupo="costa", vars=["precipitacion"]),
    dict(id="lo_rojas", nombre="Lo Rojas", fuente="vipnet", codigo="05425003-7", comuna="La Cruz",
         lat=-32.8136, lon=-71.2505, alt=190, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="pozo_quillota", nombre="Pozo Quillota", fuente="vipnet", codigo="05426031-8", comuna="Quillota",
         lat=-32.9083, lon=-71.2664, alt=107, grupo="costa", vars=["precipitacion"]),
    dict(id="los_aromos", nombre="Los Aromos", fuente="vipnet", codigo="05427007-0", comuna="Limache",
         lat=-32.9583, lon=-71.3451, alt=100, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="las_salinas", nombre="Las Salinas", fuente="vipnet", codigo="05500003-4", comuna="Viña del Mar",
         lat=-33.0024, lon=-71.5468, alt=20, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="valparaiso", nombre="Valparaíso", fuente="vipnet", codigo="05510007-1", comuna="Valparaíso",
         lat=-33.0413, lon=-71.6046, alt=44, grupo="costa", vars=["precipitacion"]),
    dict(id="rodelillo", nombre="Rodelillo", fuente="vipnet", codigo="05510001-2", comuna="Valparaíso",
         lat=-33.0507, lon=-71.5842, alt=110, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="cerro_colorado_armada", nombre="Cerro Colorado (Armada)", fuente="vipnet", codigo="05510005-5", comuna="Valparaíso",
         lat=-33.0824, lon=-71.6171, alt=510, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="lago_penuelas", nombre="Lago Peñuelas", fuente="vipnet", codigo="05510002-0", comuna="Valparaíso",
         lat=-33.1451, lon=-71.5560, alt=360, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="las_piedras", nombre="Las Piedras", fuente="vipnet", codigo="05500001-8", comuna="Quilpué",
         lat=-33.1556, lon=-71.3120, alt=225, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="tapihue", nombre="Tapihue", fuente="vipnet", codigo="05520002-5", comuna="Casablanca",
         lat=-33.2908, lon=-71.2895, alt=310, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="pozo_los_perales", nombre="Pozo Los Perales", fuente="vipnet", codigo="05520042-4", comuna="Casablanca",
         lat=-33.3225, lon=-71.3111, alt=314, grupo="costa", vars=["precipitacion"]),
    dict(id="casablanca", nombre="Casablanca", fuente="vipnet", codigo="05520001-7", comuna="Casablanca",
         lat=-33.3231, lon=-71.4105, alt=290, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="algarrobo", nombre="Algarrobo", fuente="vipnet", codigo="05530005-4", comuna="El Tabo",
         lat=-33.4390, lon=-71.6240, alt=130, grupo="costa", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="lagunillas", nombre="Lagunillas", fuente="vipnet", codigo="05530003-8", comuna="Casablanca",
         lat=-33.4473, lon=-71.4548, alt=200, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="san_antonio_punta_panul", nombre="San Antonio (Punta Panul)", fuente="vipnet", codigo="05530002-K", comuna="San Antonio",
         lat=-33.5747, lon=-71.6251, alt=80, grupo="costa", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="cerrillos_de_leyda", nombre="Cerrillos de Leyda", fuente="vipnet", codigo="05748003-3", comuna="San Antonio",
         lat=-33.6344, lon=-71.5104, alt=182, grupo="costa", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="rinconada_san_juan", nombre="Rinconada San Juan", fuente="vipnet", codigo="05748005-K", comuna="San Antonio",
         lat=-33.7628, lon=-71.5175, alt=170, grupo="costa", vars=["temperatura", "humedad", "viento"]),
    dict(id="rio_maipo_en_cabimbao", nombre="Río Maipo en Cabimbao", fuente="vipnet", codigo="05748001-7", comuna="San Antonio",
         lat=-33.7676, lon=-71.5305, alt=35, grupo="costa", vars=["precipitacion"]),
    dict(id="frutillar_alto", nombre="Frutillar Alto", fuente="vipnet", codigo="05111002-1", comuna="Petorca",
         lat=-32.1496, lon=-70.9980, alt=780, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="chalaco", nombre="Chalaco", fuente="vipnet", codigo="05101006-K", comuna="Petorca",
         lat=-32.1789, lon=-70.7874, alt=880, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="el_sobrante_hacienda", nombre="El Sobrante (Hacienda)", fuente="vipnet", codigo="05100006-4", comuna="Petorca",
         lat=-32.2295, lon=-70.7948, alt=810, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="palquico", nombre="Palquico", fuente="vipnet", codigo="05111001-3", comuna="Petorca",
         lat=-32.2527, lon=-71.1386, alt=450, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="hierro_viejo", nombre="Hierro Viejo", fuente="vipnet", codigo="05110003-4", comuna="Petorca",
         lat=-32.2814, lon=-70.9768, alt=440, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="el_salvador", nombre="El Salvador", fuente="vipnet", codigo="05111004-8", comuna="Petorca",
         lat=-32.3063, lon=-71.0773, alt=340, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="alicahue", nombre="Alicahue", fuente="vipnet", codigo="05200006-8", comuna="Cabildo",
         lat=-32.3410, lon=-70.7517, alt=750, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="artificio", nombre="Artificio", fuente="vipnet", codigo="05120003-9", comuna="Cabildo",
         lat=-32.3986, lon=-71.0956, alt=250, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="chacrilla", nombre="Chacrilla", fuente="vipnet", codigo="05220006-7", comuna="Cabildo",
         lat=-32.4272, lon=-71.0607, alt=290, grupo="valle", vars=["precipitacion"]),
    dict(id="la_vina", nombre="La Viña", fuente="vipnet", codigo="05210002-K", comuna="Cabildo",
         lat=-32.4322, lon=-70.9119, alt=370, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="valle_hermoso", nombre="Valle Hermoso", fuente="vipnet", codigo="05221005-4", comuna="La Ligua",
         lat=-32.4435, lon=-71.1991, alt=80, grupo="valle", vars=["precipitacion"]),
    dict(id="pataguas", nombre="Pataguas", fuente="vipnet", codigo="05220016-4", comuna="La Ligua",
         lat=-32.5122, lon=-71.1794, alt=164, grupo="valle", vars=["precipitacion"]),
    dict(id="las_pataguas", nombre="Las Pataguas", fuente="vipnet", codigo="05220007-5", comuna="La Ligua",
         lat=-32.5374, lon=-71.1353, alt=350, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="el_tartaro", nombre="El Tártaro", fuente="vipnet", codigo="05414005-3", comuna="Putaendo",
         lat=-32.5685, lon=-70.6988, alt=950, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="mina_cerro_negro", nombre="Mina Cerro Negro", fuente="vipnet", codigo="05211003-3", comuna="Cabildo",
         lat=-32.5930, lon=-70.8721, alt=650, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="el_cobre", nombre="El Cobre", fuente="vipnet", codigo="05424005-8", comuna="Nogales",
         lat=-32.6536, lon=-71.1965, alt=280, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="san_felipe", nombre="San Felipe", fuente="vipnet", codigo="05410008-6", comuna="San Felipe",
         lat=-32.7554, lon=-70.7070, alt=640, grupo="valle", vars=["precipitacion"]),
    dict(id="catemu", nombre="Catemu", fuente="vipnet", codigo="05421005-1", comuna="Catemu",
         lat=-32.7579, lon=-70.9426, alt=440, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="pozo_lo_campo", nombre="Pozo Lo Campo", fuente="vipnet", codigo="05420012-9", comuna="Panquehue",
         lat=-32.8097, lon=-70.9253, alt=441, grupo="valle", vars=["precipitacion"]),
    dict(id="los_andes", nombre="Los Andes", fuente="vipnet", codigo="05410007-8", comuna="Los Andes",
         lat=-32.8113, lon=-70.6420, alt=820, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_aconcagua_en_romeral", nombre="Río Aconcagua en Romeral", fuente="vipnet", codigo="05423003-6", comuna="Llaillay",
         lat=-32.8401, lon=-71.0255, alt=365, grupo="valle", vars=["precipitacion"]),
    dict(id="rio_aconcagua_en_chacabuquito", nombre="Río Aconcagua en Chacabuquito", fuente="vipnet", codigo="05410002-7", comuna="San Esteban",
         lat=-32.8504, lon=-70.5094, alt=950, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="estero_rabuco", nombre="Estero Rabuco", fuente="vipnet", codigo="05423013-3", comuna="Hijuelas",
         lat=-32.8535, lon=-71.1206, alt=300, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="las_chilcas", nombre="Las Chilcas", fuente="vipnet", codigo="05422002-2", comuna="Llaillay",
         lat=-32.8662, lon=-70.8483, alt=850, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="quillota", nombre="Quillota", fuente="vipnet", codigo="05426004-0", comuna="Quillota",
         lat=-32.8961, lon=-71.2065, alt=130, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="quebrada_alvarado", nombre="Quebrada Alvarado", fuente="vipnet", codigo="05427008-9", comuna="Olmué",
         lat=-33.0506, lon=-71.1146, alt=290, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="embalse_lliu_lliu", nombre="Embalse Lliu-Lliu", fuente="vipnet", codigo="05427006-2", comuna="Limache",
         lat=-33.0984, lon=-71.2145, alt=260, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="colliguay", nombre="Colliguay", fuente="vipnet", codigo="05741002-7", comuna="Quilpué",
         lat=-33.1685, lon=-71.1465, alt=490, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="pedernal_hacienda", nombre="Pedernal (Hacienda)", fuente="vipnet", codigo="05101005-1", comuna="Petorca",
         lat=-32.0927, lon=-70.7988, alt=1100, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="nacimiento_del_sobrante", nombre="Nacimiento del Sobrante", fuente="vipnet", codigo="05100003-K", comuna="Petorca",
         lat=-32.1883, lon=-70.4831, alt=3143, grupo="cordillera", vars=["temperatura", "viento"]),
    dict(id="el_trapiche", nombre="El Trapiche", fuente="vipnet", codigo="05100005-6", comuna="Petorca",
         lat=-32.2291, lon=-70.7376, alt=1180, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="la_mostaza", nombre="La Mostaza", fuente="vipnet", codigo="05200007-6", comuna="Cabildo",
         lat=-32.4376, lon=-70.6816, alt=1200, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="resguardo_los_patos", nombre="Resguardo Los Patos", fuente="vipnet", codigo="05414004-5", comuna="Putaendo",
         lat=-32.5015, lon=-70.5817, alt=1220, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="jahuel", nombre="Jahuel", fuente="vipnet", codigo="05415004-0", comuna="Santa María",
         lat=-32.6873, lon=-70.5965, alt=1020, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="canal_colorado_en_bocatoma", nombre="Canal Colorado en Bocatoma", fuente="vipnet", codigo="05404001-6", comuna="San Esteban",
         lat=-32.8386, lon=-70.3554, alt=1391, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="portillo", nombre="Portillo", fuente="vipnet", codigo="05401007-9", comuna="Los Andes",
         lat=-32.8425, lon=-70.0971, alt=3032, grupo="cordillera", vars=["temperatura"]),
    dict(id="vilcuya", nombre="Vilcuya", fuente="vipnet", codigo="05410006-K", comuna="Los Andes",
         lat=-32.8603, lon=-70.4717, alt=1100, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_juncal_en_juncal", nombre="Río Juncal en Juncal", fuente="vipnet", codigo="05401003-6", comuna="Los Andes",
         lat=-32.8703, lon=-70.1472, alt=2200, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_aconcagua_en_rio_blanco", nombre="Río Aconcagua en Río Blanco", fuente="vipnet", codigo="05403002-9", comuna="Los Andes",
         lat=-32.9101, lon=-70.3073, alt=1420, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="estero_pocuro_en_el_sifon", nombre="Estero Pocuro en El Sifón", fuente="vipnet", codigo="05411001-4", comuna="Calle Larga",
         lat=-32.9206, lon=-70.5435, alt=1000, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="riecillos", nombre="Riecillos", fuente="vipnet", codigo="05403006-1", comuna="Los Andes",
         lat=-32.9226, lon=-70.3571, alt=1290, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
]
SITIO = {s["id"]: s for s in SITIOS}
METARS = sorted({s["codigo"] for s in SITIOS if s["fuente"] == "metar"})

# Nodos del super-ensamble. En Open-Meteo cada miembro cuenta como una variable, así que el ensamble de
# un sitio (143 miembros × 6 variables × 14 días) pesa ~85 consultas de la cuota gratuita: pedirlo para
# los ~70 sitios cada hora agota el límite de 5000 por hora. Como sus grillas son de 0,25–0,5°, se pide
# una vez por celda de 0,5° en la estación más cercana al centro de la celda (el "nodo"), y las demás
# estaciones de la celda lo comparten. Los 7 modelos deterministas sí se piden en cada estación.
PASO_NODO = 0.5


def _nodos():
    celdas = {}
    for s in SITIOS:
        celdas.setdefault((round(s["lat"] / PASO_NODO), round(s["lon"] / PASO_NODO)), []).append(s)
    nodo = {}
    for (i, j), ss in celdas.items():
        rep = min(ss, key=lambda s: (s["lat"] - i * PASO_NODO) ** 2 + (s["lon"] - j * PASO_NODO) ** 2)
        nodo.update({s["id"]: rep["id"] for s in ss})
    return nodo


NODO = _nodos()  # id de sitio -> id de la estación cuyo ensamble usa
GRUPOS = {"costa": "#00797C", "valle": "#E0701A", "cordillera": "#6B3FA0"}
NOMBRE_GRUPO = {"costa": "costa", "valle": "valle", "cordillera": "cordillera"}
SIGLA = {"metar": "DMC", "vipnet": "DGA"}  # quién opera la estación, para las etiquetas


def etiqueta(s):
    """'Santa Juana (DGA)': nombre del sitio y, entre paréntesis, la sigla de la fuente."""
    return f"{s['nombre']} ({SIGLA[s['fuente']]})"


def ahora_local():
    return datetime.now(ZONA).replace(tzinfo=None)


def a_local(utc):
    """DatetimeIndex/Series UTC (con o sin tz) -> hora de Chile sin zona."""
    t = pd.DatetimeIndex(pd.to_datetime(utc, utc=True))
    return t.tz_convert(ZONA).tz_localize(None)


# ------------------------------------------------------------------ VIPNet
# Rango físico por tipoEstacion (lluvia en mm cada 30 min): fuera de él, el dato se descarta.
LIMITES = {0: (0, 40), 1: (-25, 45), 4: (1, 100), 5: (0, 200)}
HORAS_MAX_VIPNET = 365 * 24  # una estación y un año: ~17 500 datos, 3 MB y ~5 s (probado el 01/10/2026)
HORAS_MAX_METAR = 15 * 24    # la API del NOAA no entrega más de ~15 días hacia atrás


def vipnet(codigo, tipo, horas):
    """Serie cruda (cada 30 min) de una estación VIPNet: DataFrame[hora, valor], sin los valores
    fuera de LIMITES."""
    t = ahora_local()  # la API arma la ventana en hora chilena
    cuerpo = {"codigoEstacion": codigo, "tipoEstacion": tipo, "fetchHour": t.hour,
              "fetchDay": f"{t:%Y-%m-%d}", "hoursRange": int(horas)}
    r = requests.post(URL_VIPNET, json=cuerpo, headers=UA, timeout=60)
    r.raise_for_status()
    d = r.json().get("data", [])
    if not d:
        return pd.DataFrame(columns=["hora", "valor"])
    df = pd.DataFrame({"hora": a_local([x["fecha"]["$date"] for x in d]),
                       "valor": [np.nan if x.get("instantaneo") is None else float(x["instantaneo"])
                                 for x in d]})
    lo, hi = LIMITES.get(tipo, (-np.inf, np.inf))
    df.loc[(df.valor < lo) | (df.valor > hi), "valor"] = np.nan
    return df.sort_values("hora").drop_duplicates("hora").reset_index(drop=True)


def a_horaria(df, variable):
    """Pasa una serie cruda a horaria (hora que termina en T). Lluvia: suma,
    solo horas completas; resto: media de la hora."""
    if df.empty:
        return pd.Series(dtype=float)
    g = df.groupby(df.hora.dt.ceil("h"))["valor"]
    if variable != "precipitacion":
        return g.mean()
    paso = df.hora.diff().median()
    por_hora = max(int(round(pd.Timedelta(hours=1) / paso)), 1) if pd.notna(paso) else 1
    tab = g.agg(["sum", "count"])
    return tab.loc[tab["count"] >= por_hora, "sum"]


def vipnet_variable(variable, horas):
    """{id_sitio: Series horaria} para todas las estaciones VIPNet que miden
    'variable', descargadas en paralelo. Devuelve también la lista de avisos."""
    tipo = VARIABLES[variable]["vipnet"]
    sitios = [s for s in SITIOS if s["fuente"] == "vipnet" and variable in s["vars"]]

    def una(s):
        try:
            return s["id"], a_horaria(vipnet(s["codigo"], tipo, horas), variable), None
        except Exception as ex:  # noqa: BLE001
            return s["id"], None, f"{s['nombre']}: {str(ex)[:120]}"

    with ThreadPoolExecutor(max_workers=12) as pool:
        res = list(pool.map(una, sitios))
    series = {i: s for i, s, _ in res if s is not None and not s.empty}
    avisos = [a for _, _, a in res if a]
    avisos += [f"{SITIO[i]['nombre']}: sin datos de {VARIABLES[variable]['nombre'].lower()}"
               for i, s, a in res if a is None and (s is None or s.empty)]
    return series, avisos


# ------------------------------------------------------------------ METAR
def humedad_relativa(t, td):
    """Magnus (Alduchov y Eskridge, 1996)."""
    a, b = 17.625, 243.04
    return 100 * np.exp(a * td / (b + td)) / np.exp(a * t / (b + t))


def metar_crudo(estacion, horas):
    """Todos los METAR/SPECI de una estación, sin agrupar: DataFrame con hora local, tipo,
    temperatura, rocío, humedad, viento, ráfaga, dirección, presión (QNH) y el texto del reporte."""
    r = requests.get(URL_METAR, params={"ids": estacion, "format": "json", "hours": int(horas)},
                     headers=UA, timeout=30)
    r.raise_for_status()
    d = r.json()
    if not d:
        return pd.DataFrame()

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return np.nan  # p. ej. dirección "VRB"

    df = pd.DataFrame({
        "hora": a_local(pd.to_datetime([x["obsTime"] for x in d], unit="s")),
        "tipo": [x.get("metarType") for x in d],
        "temperatura": [num(x.get("temp")) for x in d],
        "rocio": [num(x.get("dewp")) for x in d],
        "viento": [num(x.get("wspd")) * 1.852 for x in d],
        "rafaga": [num(x.get("wgst")) * 1.852 for x in d],
        "direccion": [num(x.get("wdir")) for x in d],
        "presion": [num(x.get("altim")) for x in d],
        "texto": [x.get("rawOb", "") for x in d],
    })
    df["humedad"] = humedad_relativa(df.temperatura, df.rocio)
    # viento calmo: la dirección no tiene sentido
    df.loc[df.viento == 0, "direccion"] = np.nan
    return df.sort_values("hora").reset_index(drop=True)


def metar(estacion="SCVM", horas=72):
    """METAR/SPECI de una estación: DataFrame horario (hora local) con
    temperatura, humedad, viento, ráfaga, dirección y presión (QNH)."""
    df = metar_crudo(estacion, horas)
    if df.empty:
        return df
    # a la hora más cercana; entre METAR y SPECI de la misma hora, gana el METAR
    df["hora_redonda"] = df.hora.dt.round("h")
    df = (df.sort_values(["hora_redonda", "tipo"])
          .drop_duplicates("hora_redonda", keep="first")
          .set_index("hora_redonda").sort_index())
    df.index.name = "hora"
    return df


def metars(horas):
    """{código: DataFrame horario} de todos los METAR de la red (vacío si uno no responde)."""
    def uno(codigo):
        try:
            return codigo, metar(codigo, horas)
        except Exception:  # noqa: BLE001
            return codigo, pd.DataFrame()

    with ThreadPoolExecutor(max_workers=len(METARS)) as pool:
        return dict(pool.map(uno, METARS))


# ------------------------------------------------------------------ descarga a pedido
def datos_estacion(s, horas):
    """Lo que midió la estación s en las últimas 'horas', sin promediar (cada 30 min en VIPNet; cada
    reporte en el METAR), en una tabla con una columna por variable. Para el botón de descarga."""
    if s["fuente"] == "metar":
        df = metar_crudo(s["codigo"], min(horas, HORAS_MAX_METAR))
        if df.empty:
            return df
        cols = ["hora", "tipo", *[VARIABLES[v]["metar"] for v in s["vars"]], "texto"]
        return df[cols].rename(columns={"tipo": "reporte"})
    horas = min(horas, HORAS_MAX_VIPNET)

    def una(v):
        df = vipnet(s["codigo"], VARIABLES[v]["vipnet"], horas)
        return df.set_index("hora")["valor"].rename(v)

    with ThreadPoolExecutor(max_workers=4) as pool:
        series = list(pool.map(una, s["vars"]))
    return pd.concat(series, axis=1).sort_index().reset_index() if series else pd.DataFrame()


# ------------------------------------------------------------------ Open-Meteo
# Open-Meteo gratuito limita las consultas por IP. En Streamlit Community Cloud la IP es compartida
# con otras apps y suele estar agotada (HTTP 429), así que la app lee los pronósticos que una GitHub
# Action publica cada hora en la rama "datos" (ver actualiza_pronosticos.py) y solo consulta en vivo
# si esa copia falta o está vieja.
REPO = "Heszo/monitor-meteo-valparaiso"
URL_PUBLICADOS = os.environ.get("MONITOR_DATOS", f"https://raw.githubusercontent.com/{REPO}/datos")  # URL o carpeta
DIAS_PUBLICADOS = 7  # pasado y futuro guardados en la copia publicada (el máximo de la barra lateral)


class OpenMeteoError(RuntimeError):
    pass


def _get_json(url, params, intentos=4, timeout=60):
    """GET con reintentos ante 429, errores 5xx, cortes y respuestas que no son JSON. Ante el
    límite por minuto de Open-Meteo se espera un minuto; ante el límite por hora no se reintenta."""
    ultimo = ""
    for k in range(intentos):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 429 and "Hourly" in r.text:
                raise OpenMeteoError(f"{url.split('/')[2]}: límite de consultas por hora agotado")
            if r.status_code == 429 and "Minutely" in r.text and k < intentos - 1:
                time.sleep(61)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
            else:
                r.raise_for_status()
                return r.json()
        except (requests.Timeout, requests.ConnectionError, ValueError) as ex:
            ultimo = type(ex).__name__
        except requests.HTTPError as ex:  # 4xx distinto de 429: no tiene sentido reintentar
            raise OpenMeteoError(f"{url.split('/')[2]}: {ex.response.status_code} {ex.response.text[:200]}") from None
        if k < intentos - 1:
            time.sleep(2 * 2 ** k)
    raise OpenMeteoError(f"{url.split('/')[2]}: {ultimo} tras {intentos} intentos")


def _params(puntos, variables, pasado, futuro):
    """Parámetros para uno o varios puntos [(lat, lon), ...]: Open-Meteo acepta listas separadas por
    coma y responde una lista en el mismo orden, así una consulta sirve para un lote de sitios."""
    return dict(latitude=",".join(f"{la:.4f}" for la, _ in puntos),
                longitude=",".join(f"{lo:.4f}" for _, lo in puntos), hourly=",".join(variables),
                past_days=int(pasado), forecast_days=int(futuro), timezone="America/Santiago",
                wind_speed_unit="kmh")


def _por_punto(respuesta):
    """Lista con el bloque "hourly" de cada punto (con un solo punto Open-Meteo no devuelve lista)."""
    return [r["hourly"] for r in (respuesta if isinstance(respuesta, list) else [respuesta])]


def _serie(valores):
    return np.array([np.nan if x is None else x for x in valores], float)


def deterministas(puntos, pasado, futuro):
    """Por cada punto, {variable: DataFrame(tiempo x modelo)} de los 7 modelos deterministas, más
    "estado": el código WMO del estado del tiempo de cada modelo."""
    oms = {**{k: v["om"] for k, v in VARIABLES.items()}, "estado": OM_ESTADO}
    salida = []
    for h in _por_punto(_get_json(URL_OM, _params(puntos, oms.values(), pasado, futuro) |
                                  {"models": ",".join(MODELOS)}, timeout=120)):
        t = pd.to_datetime(h["time"])
        uno = {}
        for clave, om in oms.items():
            cols = {m: _serie(h[f"{om}_{m}"]) for m in MODELOS if f"{om}_{m}" in h}
            uno[clave] = pd.DataFrame({m: x for m, x in cols.items() if np.isfinite(x).any()}, index=t)
        salida.append(uno)
    return salida


def ensamble(puntos, pasado, futuro):
    """Por cada punto, {variable: DataFrame(tiempo x miembro)} del super-ensamble (los 4
    centros juntos). La dirección se omite: sus percentiles no tienen sentido.
    Si un centro no responde se sigue con los demás; si no responde ninguno, error."""
    claves = [k for k, v in VARIABLES.items() if not v.get("sin_ensamble")]
    oms = [VARIABLES[k]["om"] for k in claves]

    def uno(modelo):
        try:
            return modelo, _por_punto(_get_json(URL_ENS, _params(puntos, oms, pasado, futuro) | {"models": modelo},
                                                timeout=180))
        except OpenMeteoError:
            return modelo, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        respuestas = [(m, hs) for m, hs in pool.map(uno, ENSAMBLES) if hs]
    if not respuestas:
        raise OpenMeteoError("ensemble-api.open-meteo.com: ningún centro respondió")
    salida = []
    for i in range(len(puntos)):
        t = pd.to_datetime(respuestas[0][1][i]["time"])
        por_var = {}
        for clave, om in zip(claves, oms):
            cols = {}
            for modelo, hs in respuestas:
                for k, valores in hs[i].items():
                    if k == om or k.startswith(om + "_member"):
                        serie = _serie(valores)
                        if np.isfinite(serie).any():
                            cols[f"{modelo}:{k}"] = serie
            por_var[clave] = pd.DataFrame(cols, index=t)
        salida.append(por_var)
    return salida


def percentiles(miembros, qs=(10, 50, 90)):
    if miembros is None or miembros.empty:
        return None
    with warnings.catch_warnings():  # horas sin ningún miembro (el final del horizonte): quedan en NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        return pd.DataFrame({f"p{q}": np.nanpercentile(miembros.values, q, axis=1) for q in qs},
                            index=miembros.index)


def resumen_pronostico(det, ens):
    """Lo que la app usa de un sitio: deterministas, percentiles del ensamble
    por variable, los miembros de lluvia (para acumulados y bloques) y la
    ráfaga de cada bloque de 6 h (mediana entre miembros del máximo del bloque)."""
    raf = ens.get("rafaga")
    raf6h = None
    if raf is not None and not raf.empty:
        raf6h = raf.resample("6h", origin="start_day", closed="right", label="left").max().median(axis=1)
    return {"det": det, "pct": {k: percentiles(v) for k, v in ens.items()},
            "pp": ens.get("precipitacion"), "raf6h": raf6h}


def pronostico_lote(puntos, pasado, futuro, exige_ensamble=True):
    """Resumen de cada punto [(lat, lon), ...], en vivo y con una consulta por fuente para todo el
    lote. Con exige_ensamble=False, si el ensamble no responde se devuelven igual los 7 modelos
    (sin banda ni miembros de lluvia)."""
    det = deterministas(puntos, pasado, futuro)
    try:
        ens = ensamble(puntos, pasado, futuro)
    except OpenMeteoError:
        if exige_ensamble:
            raise
        ens = [{} for _ in puntos]
    return [resumen_pronostico(d, e) for d, e in zip(det, ens)]


def pronostico_vivo(lat, lon, pasado, futuro, exige_ensamble=True):
    """Resumen de un sitio en vivo."""
    return pronostico_lote([(lat, lon)], pasado, futuro, exige_ensamble)[0]


# --- copia publicada: 4 tablas parquet con columnas "sitio|variable|serie". Las tablas del ensamble
# (pct, pp, raf6h) se guardan una vez por nodo; meta.json dice qué nodo usa cada sitio.
def guarda_pronosticos(por_sitio, carpeta, generado, nodo=None):
    import json
    from pathlib import Path

    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    nodo = {sid: (nodo or {}).get(sid, sid) for sid in por_sitio}
    tablas = {"det": {}, "pct": {}, "pp": {}, "raf6h": {}}
    hechos = set()
    for sid, r in por_sitio.items():
        for var, df in r["det"].items():
            for c in df:
                tablas["det"][f"{sid}|{var}|{c}"] = df[c]
        e = nodo[sid]
        if e in hechos:
            continue
        hechos.add(e)
        for var, df in r["pct"].items():
            if df is not None:
                for c in df:
                    tablas["pct"][f"{e}|{var}|{c}"] = df[c]
        if r["pp"] is not None:
            for c in r["pp"]:
                tablas["pp"][f"{e}|precipitacion|{c}"] = r["pp"][c]
        if r["raf6h"] is not None:
            tablas["raf6h"][f"{e}|rafaga|p50"] = r["raf6h"]
    for nombre, cols in tablas.items():
        pd.DataFrame(cols).astype("float32").to_parquet(carpeta / f"{nombre}.parquet", compression="zstd")
    (carpeta / "meta.json").write_text(json.dumps({"generado": generado, "sitios": sorted(por_sitio),
                                                   "nodos": nodo}))


def _desarma(df):
    """{sitio: {variable: DataFrame(tiempo x serie)}} desde columnas 'sitio|variable|serie'."""
    salida = {}
    for col in df.columns:
        sid, var, serie = col.split("|", 2)
        salida.setdefault(sid, {}).setdefault(var, {})[serie] = df[col].astype(float)
    return {sid: {v: pd.DataFrame(c) for v, c in vs.items()} for sid, vs in salida.items()}


def lee_pronosticos(base=URL_PUBLICADOS):
    """(generado, {sitio: resumen}) desde la copia publicada (URL o carpeta)."""
    import io
    import json
    from pathlib import Path

    def lee(nombre):
        if str(base).startswith("http"):
            r = requests.get(f"{base}/{nombre}", headers=UA, timeout=30)
            r.raise_for_status()
            return r.content
        return (Path(base) / nombre).read_bytes()

    meta = json.loads(lee("meta.json"))
    t = {n: _desarma(pd.read_parquet(io.BytesIO(lee(f"{n}.parquet")))) for n in ("det", "pct", "pp", "raf6h")}
    por_sitio = {}
    for sid in meta["sitios"]:
        e = meta.get("nodos", {}).get(sid, sid)
        pp = t["pp"].get(e, {}).get("precipitacion")
        raf = t["raf6h"].get(e, {}).get("rafaga")
        por_sitio[sid] = {"det": t["det"].get(sid, {}), "pct": t["pct"].get(e, {}), "pp": pp,
                          "raf6h": raf["p50"] if raf is not None else None}
    return pd.Timestamp(meta["generado"]), por_sitio


# ------------------------------------------------------------------ estado del tiempo
# Códigos WMO de Open-Meteo agrupados en estados, de menor a mayor severidad: (clave, nombre, ícono,
# códigos). Un mismo día se describe con el estado más severo que den la mayoría de los modelos.
ESTADOS = [
    ("despejado", "Despejado", "☀️", (0, 1)),
    ("parcial", "Parcial nublado", "⛅", (2,)),
    ("nublado", "Nublado", "☁️", (3,)),
    ("niebla", "Niebla", "🌫️", (45, 48)),
    ("llovizna", "Llovizna", "🌦️", (51, 53, 55, 56, 57)),
    ("chubascos", "Chubascos", "🌦️", (80, 81, 82)),
    ("lluvia", "Lluvia", "🌧️", (61, 63, 65, 66, 67)),
    ("nieve", "Nieve", "🌨️", (71, 73, 75, 77, 85, 86)),
    ("tormenta", "Tormenta eléctrica", "⛈️", (95, 96, 99)),
]
ESTADO = {clave: dict(nombre=n, icono=i, orden=k) for k, (clave, n, i, _) in enumerate(ESTADOS)}
_DE_CODIGO = {c: clave for clave, _, _, cs in ESTADOS for c in cs}
HORAS_PARA_PRECIPITACION = 3  # un día con lluvia, llovizna, etc. en al menos estas horas


def estado_horario(codigos):
    """Estado de cada hora a partir de los códigos de los modelos (DataFrame tiempo × modelo): el más
    severo que alcanza la mitad de los modelos con dato."""
    orden = codigos.apply(lambda col: col.map(lambda c: ESTADO[_DE_CODIGO[int(c)]]["orden"]
                                              if pd.notna(c) and int(c) in _DE_CODIGO else np.nan))
    # el estado de "la mitad de los modelos": la mediana (por arriba) de los órdenes
    med = np.ceil(orden.median(axis=1))
    return med.map(lambda k: ESTADOS[int(k)][0] if pd.notna(k) else None)


def estado_dia(horario):
    """Estado de un día a partir de sus estados horarios: la precipitación más severa que dure al menos
    HORAS_PARA_PRECIPITACION horas; si no hay, el estado de cielo más común de las horas de luz."""
    h = horario.dropna()
    if h.empty:
        return None
    severos = [e for e in reversed(ESTADOS) if ESTADO[e[0]]["orden"] >= ESTADO["llovizna"]["orden"]]
    for clave, *_ in severos:
        if (h.map(lambda e: ESTADO[e]["orden"] >= ESTADO[clave]["orden"])).sum() >= HORAS_PARA_PRECIPITACION:
            return clave
    luz = h[(h.index.hour >= 8) & (h.index.hour <= 20)]
    return (luz if len(luz) else h).mode().iloc[0]


# ------------------------------------------------------------------ grilla regional (mapas de superficie)
# Los 7 modelos en una grilla de 0,2° que cubre la región (11 × 12 = 132 puntos), para dibujar campos
# de viento, temperatura, presión y lluvia. Ventana corta (1 día atrás, 5 adelante): con 6 variables ×
# 7 modelos cada punto pesa unas 2 consultas, ~260 por corrida.
GRILLA_LAT = np.round(np.arange(-32.0, -34.01, -0.2), 2)  # de norte a sur
GRILLA_LON = np.round(np.arange(-72.0, -69.79, 0.2), 2)   # de oeste a este
GRILLA_VARS = ["viento", "direccion", "rafaga", "temperatura", "presion", "precipitacion"]
GRILLA_PASADO, GRILLA_FUTURO = 1, 5
GRILLA_LOTE = 20  # puntos por consulta (~0,7 MB por respuesta)


def grilla(pasado=GRILLA_PASADO, futuro=GRILLA_FUTURO, pausa=0):
    """Pronóstico de los 7 modelos en la grilla regional: DataFrame largo con columnas tiempo, lat,
    lon y 'variable|modelo'. Se pide por lotes; si un lote falla, error (una grilla con huecos no
    sirve para dibujar el campo)."""
    puntos = [(la, lo) for la in GRILLA_LAT for lo in GRILLA_LON]
    oms = [VARIABLES[v]["om"] for v in GRILLA_VARS]
    partes = []
    for k in range(0, len(puntos), GRILLA_LOTE):
        if k and pausa:
            time.sleep(pausa)
        lote = puntos[k:k + GRILLA_LOTE]
        resp = _get_json(URL_OM, _params(lote, oms, pasado, futuro) | {"models": ",".join(MODELOS)}, timeout=120)
        for (la, lo), h in zip(lote, _por_punto(resp)):
            df = pd.DataFrame({f"{v}|{m}": _serie(h[f"{VARIABLES[v]['om']}_{m}"])
                               for v in GRILLA_VARS for m in MODELOS if f"{VARIABLES[v]['om']}_{m}" in h})
            df.insert(0, "tiempo", pd.to_datetime(h["time"]))
            df.insert(1, "lat", la)
            df.insert(2, "lon", lo)
            partes.append(df)
    return pd.concat(partes, ignore_index=True).dropna(axis=1, how="all")  # p. ej. GSM no trae ráfagas


def guarda_grilla(tabla, carpeta):
    from pathlib import Path

    datos = tabla.astype({c: "float32" for c in tabla.columns if "|" in c})
    datos.to_parquet(Path(carpeta) / "grilla.parquet", compression="zstd")


def lee_grilla(base=URL_PUBLICADOS):
    """DataFrame de guarda_grilla desde la copia publicada (URL o carpeta)."""
    import io
    from pathlib import Path

    if str(base).startswith("http"):
        r = requests.get(f"{base}/grilla.parquet", headers=UA, timeout=60)
        r.raise_for_status()
        return pd.read_parquet(io.BytesIO(r.content))
    return pd.read_parquet(Path(base) / "grilla.parquet")


def cubo(tabla, variable, modelo):
    """(horas, arreglo horas × lat × lon) de 'variable' del 'modelo', de norte a sur y de oeste a este.
    variable="uv": las componentes (u, v) del viento en km/h. modelo="mediana": mediana entre los modelos
    (el viento, sobre u y v, para no promediar ángulos)."""
    horas = np.sort(tabla.tiempo.unique())
    it = np.searchsorted(horas, tabla.tiempo.values)
    iy = np.abs(tabla.lat.values[:, None] - GRILLA_LAT).argmin(axis=1)
    ix = np.abs(tabla.lon.values[:, None] - GRILLA_LON).argmin(axis=1)

    def arreglo(col):
        a = np.full((len(horas), len(GRILLA_LAT), len(GRILLA_LON)), np.nan, np.float32)
        if col in tabla:
            a[it, iy, ix] = tabla[col].values
        return a

    def uv(m):
        rad = np.deg2rad(arreglo(f"direccion|{m}"))
        vel = arreglo(f"viento|{m}")
        return np.stack([-vel * np.sin(rad), -vel * np.cos(rad)])  # la dirección es de dónde viene el viento

    una = uv if variable == "uv" else (lambda m: arreglo(f"{variable}|{m}"))
    if modelo != "mediana":
        return pd.DatetimeIndex(horas), una(modelo)
    presentes = [m for m in MODELOS if f"{'viento' if variable == 'uv' else variable}|{m}" in tabla]
    if not presentes:
        return pd.DatetimeIndex(horas), una(None)
    with warnings.catch_warnings():  # puntos sin ningún modelo: quedan en NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        return pd.DatetimeIndex(horas), np.nanmedian([una(m) for m in presentes], axis=0)


# ------------------------------------------------------------------ verificación
def diferencia(pron, obs, variable):
    """Diferencia pronóstico - observado; la dirección se toma en el círculo
    (-180, 180]."""
    d = pron - obs
    if variable == "direccion":
        d = (d + 180) % 360 - 180
    return d


def verificacion(modelos_df, obs, variable, hasta):
    """Métricas de cada modelo contra la observación en las horas ya
    ocurridas (<= hasta): n, sesgo, MAE, RMSE, correlación."""
    filas = []
    obs = obs[(obs.index <= hasta)].dropna()
    for m in modelos_df.columns:
        par = pd.concat([modelos_df[m], obs], axis=1, join="inner").dropna()
        if len(par) < 3:
            continue
        d = diferencia(par.iloc[:, 0], par.iloc[:, 1], variable)
        corr = par.iloc[:, 0].corr(par.iloc[:, 1]) if variable != "direccion" else np.nan
        filas.append(dict(modelo=m, n=len(par), sesgo=d.mean(), mae=d.abs().mean(),
                          rmse=float(np.sqrt((d ** 2).mean())), r=corr))
    return pd.DataFrame(filas).sort_values("mae") if filas else pd.DataFrame()


def cardinal(grados):
    if grados is None or np.isnan(grados):
        return "—"
    nombres = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
    return nombres[int((grados + 11.25) // 22.5) % 16]
