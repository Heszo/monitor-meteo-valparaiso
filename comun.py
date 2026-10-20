"""
Lo que comparten todas las páginas: cargas con caché, el contexto de la
corrida (sitio, ventana, datos) y utilidades de gráficos.

Las cargas usan ttl + refresh_mode="background": cuando una entrada vence,
el visitante recibe al instante la versión anterior y la nueva se baja por
detrás. Además app.py (st.App) las toca cada pocos minutos desde el
servidor, así que casi nadie espera una descarga. Para que eso funcione las
claves de caché son fijas: se pide siempre la ventana máxima y se recorta
después.
"""
import base64
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import fuentes as F

RAIZ = Path(__file__).resolve().parent
VERSION = (RAIZ / "VERSION").read_text().strip()
LOGO_SOLO = RAIZ / "static" / "logo_solo.png"  # ícono de la pestaña (page_icon no acepta SVG)
NEGRO, ROJO, BANDA = "#111111", "#B5323C", "rgba(120,150,190,.22)"
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
EJE_T = dict(tickformat="%d/%m<br>%H:%M", nticks=8, tickangle=0)
HORAS_OBS = F.DIAS_PUBLICADOS * 24 + 2
VARS_VIPNET = ("precipitacion", "temperatura", "humedad", "viento")
VACIO = {"det": {}, "pct": {}, "pp": None, "raf6h": None}
VIEJO = pd.Timedelta(hours=3)
INSTAGRAM = "https://www.instagram.com/metgeo.spa/"
LINKEDIN = "https://www.linkedin.com/company/metgeo-spa/"
METGEO = "https://metgeo.cl"
NEWSLETTER = "https://metgeo.cl/noticias.html#newsletter"

# ------------------------------------------------------------------ mapas
# Límites comunales (BCN, simplificados a ~400 m): se dibujan en todos los mapas para ubicar las estaciones.
COMUNAS = json.loads((RAIZ / "static" / "comunas_valparaiso.geojson").read_text(encoding="utf-8"))
NOMBRES_COMUNAS = sorted(f["properties"]["comuna"] for f in COMUNAS["features"])
# Imagen satelital fija (genera_satelite.py): una imagen de la región y otra más detallada del Gran
# Valparaíso, encima. El navegador las baja una vez y las guarda; no se piden mosaicos al mover el mapa.
SATELITE = json.loads((RAIZ / "static" / "satelite.json").read_text())
CENTRO = dict(lat=-33.0, lon=-70.9)
# mapas base: imagen satelital o calles (OpenStreetMap), cada uno con el color de los límites comunales
# y del texto de las estaciones que se lee bien encima
BASES = {
    "satelite": dict(nombre="Satélite", linea="rgba(255,255,255,.7)", texto="white", grilla="rgba(255,255,255,.55)",
                     credito="Esri World Imagery"),
    "calles": dict(nombre="Calles", linea="rgba(90,60,120,.8)", texto="#1a1a1a", grilla="rgba(40,40,40,.3)",
                   credito="© colaboradores de OpenStreetMap"),
}
PASO_GRILLA = 0.5  # grados entre las líneas de latitud y longitud
# el mapa no se puede mover ni alejar más allá de la imagen de contexto, así que nunca muestra bordes vacíos
LIMITES_MAPA = {k: SATELITE["contexto"][v] for k, v in
                dict(west="oeste", east="este", south="sur", north="norte").items()}


# ------------------------------------------------------------------ modo claro / oscuro
# config.toml define [theme.light] y [theme.dark] sin fijar `base`, así que Streamlit sigue el modo del
# navegador. Lo que se dibuja desde Python (logos, colores de los gráficos, tarjetas HTML) lo elige aquí.
# Los logos "claro" son los de trazo claro, para fondo oscuro.
CLARO = SimpleNamespace(
    oscuro=False, logo=RAIZ / "static" / "logo_completo.svg", icono=RAIZ / "static" / "logo_solo.svg",
    tinta=NEGRO, azul="#1F5A96", ens="#56708f", lluvia_esp="#6FA3D2", lluvia_obs="#1F4E8C", rafaga="#5B4B8A",
    niveles=("#9DBFDD", "#6FA3D2", "#1F4E8C"), grupos=F.GRUPOS, fondo_leyenda="rgba(255,255,255,.85)",
    plantilla="plotly_white", fondo="#FFFFFF")
OSCURO = SimpleNamespace(
    oscuro=True, logo=RAIZ / "static" / "logo_completo_claro.svg", icono=RAIZ / "static" / "logo_solo_claro.svg",
    tinta="#F2F2F2", azul="#6FA8DC", ens="#9DB3CC", lluvia_esp="#4E94C3", lluvia_obs="#BFE0F7", rafaga="#B9A6E8",
    niveles=("#5A7FA3", "#6FA8DC", "#A8D4F5"), grupos={"costa": "#3CC6C9", "valle": "#F28C3E", "cordillera": "#B08AE0"},
    fondo_leyenda="rgba(14,17,23,.8)", plantilla="plotly_dark", fondo="#0E1117")


def paleta():
    """Colores y logos del modo en que el navegador muestra la app (claro si no se sabe)."""
    return OSCURO if st.context.theme.type == "dark" else CLARO


# Cambiar el tema a mano (menú ⋮ → Settings) no vuelve a correr el script, así que los gráficos quedaban con los
# colores del modo anterior. Este componente invisible mira el fondo de la app y, si no coincide con el modo con
# que se dibujó, pide un rerun; el navegador manda el modo nuevo con ese rerun y st.context.theme se actualiza.
_VIGIA_JS = """
export default function ({ data, setTriggerValue }) {
    const modo = () => {
        const app = document.querySelector('.stApp') || document.body;
        const m = getComputedStyle(app).backgroundColor.match(/\\d+(\\.\\d+)?/g);
        if (!m) return null;
        const [r, g, b] = m.map(Number);
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5 ? 'dark' : 'light';
    };
    let pedido = null;  // un solo rerun por cambio, para no entrar en bucle si el servidor no se entera
    const revisa = () => {
        const actual = modo();
        if (actual && actual !== data.tema && actual !== pedido) {
            pedido = actual;
            setTriggerValue('cambio', actual);
        }
    };
    revisa();
    const reloj = setInterval(revisa, 400);
    return () => clearInterval(reloj);
}
"""

_vigias = {}  # montador del componente por runtime (las pruebas crean uno nuevo por app sin reimportar este módulo)


def vigila_tema():
    """Vuelve a dibujar la página cuando el tema cambia a mano. Va una vez por corrida, arriba de la página."""
    from streamlit.components.v2.get_bidi_component_manager import get_bidi_component_manager

    registro = id(get_bidi_component_manager())
    if registro not in _vigias:
        _vigias[registro] = st.components.v2.component("vigia_tema", js=_VIGIA_JS)
    _vigias[registro](key="vigia_tema", data={"tema": st.context.theme.type or "light"}, height=0,
                      on_cambio_change=lambda: None)


def base_actual():
    return st.session_state.get("mapa_base") or "satelite"


def con_grilla():
    return bool(st.session_state.get("grilla_latlon", False))


def controles_mapa():
    """Controles «Mapa base» y «Grilla lat/lon»; la elección se comparte entre páginas."""
    st.segmented_control("Mapa base", list(BASES), default="satelite", required=True, key="mapa_base",
                         persist_state="session", format_func=lambda k: BASES[k]["nombre"])
    st.toggle("Grilla lat/lon", key="grilla_latlon", persist_state="session",
              help=f"Líneas de latitud y longitud cada {PASO_GRILLA:g}°".replace(".", ","))


def _capas_satelite(relativa=True):
    """Capas "image" con la imagen satelital fija. La URL es relativa (la sirve la app en app/static/);
    al exportar con Kaleido la imagen va dentro de la figura."""
    capas = []
    for r in SATELITE.values():
        fuente = f"app/static/{r['archivo']}" if relativa else (
            f"data:image/{'webp' if r['archivo'].endswith('.webp') else 'jpeg'};base64," + base64.b64encode((RAIZ / "static" / r["archivo"]).read_bytes()).decode())
        capas.append(dict(sourcetype="image", source=fuente, coordinates=r["esquinas"], below="traces"))
    return capas


def paso_grilla(zoom):
    """Grados entre líneas de la grilla según el zoom: más finas al acercarse a una comuna."""
    return 0.1 if zoom >= 9 else (0.25 if zoom >= 8 else PASO_GRILLA)


def _lineas_grilla(paso=PASO_GRILLA):
    """GeoJSON con los paralelos y meridianos cada 'paso' grados que cruzan la imagen."""
    r = SATELITE["region"]
    lats = np.round(np.arange(np.ceil(r["sur"] / paso), np.floor(r["norte"] / paso) + 1) * paso, 2)
    lons = np.round(np.arange(np.ceil(r["oeste"] / paso), np.floor(r["este"] / paso) + 1) * paso, 2)
    lineas = ([[[r["oeste"], la], [r["este"], la]] for la in lats] +
              [[[lo, r["sur"]], [lo, r["norte"]]] for lo in lons])
    return {"type": "Feature", "properties": {}, "geometry": {"type": "MultiLineString", "coordinates": lineas}}, lats, lons


def grados(v, eje):
    """'37,5° S' / '72° O'."""
    letra = ("S" if v < 0 else "N") if eje == "lat" else ("O" if v < 0 else "E")
    return f"{abs(v):g}° {letra}".replace(".", ",")


def mapa(**extra):
    """layout.map con el mapa base elegido, los límites comunales y, si se pidió, la grilla de latitud y
    longitud; extra: center, zoom, capas_extra."""
    b = BASES[base_actual()]
    base = (_capas_satelite() if base_actual() == "satelite" else
            [dict(sourcetype="raster", source=[F.OSM], below="traces")])
    capas = [*base, dict(sourcetype="geojson", source=COMUNAS, type="line", color=b["linea"], line=dict(width=1),
                         below="traces")]
    vista = dict(style="white-bg", center=CENTRO, zoom=7.7, bounds=LIMITES_MAPA) | extra
    if con_grilla():
        capas.append(dict(sourcetype="geojson", source=_lineas_grilla(paso_grilla(vista["zoom"]))[0], type="line",
                          color=b["grilla"], line=dict(width=1, dash=[4, 3]), below="traces"))
    capas += vista.pop("capas_extra", [])
    return vista | dict(layers=capas)


def prepara_mapa(fig, **extra):
    """Pone el mapa (mapa()) en la figura y, con la grilla activa, los rótulos de los cruces de líneas que
    caen en la vista inicial (estimada para un mapa de ~800 × 620 px)."""
    m = mapa(**extra)
    fig.update_layout(map=m)
    if con_grilla():
        _, lats, lons = _lineas_grilla(paso_grilla(m["zoom"]))
        ancho = 800 * 360 / (512 * 2 ** m["zoom"])  # grados de longitud a la vista
        alto = ancho * 620 / 800 * np.cos(np.deg2rad(m["center"]["lat"]))
        lats = lats[np.abs(lats - m["center"]["lat"]) <= alto / 2]
        lons = lons[np.abs(lons - m["center"]["lon"]) <= ancho / 2]
        la, lo = np.meshgrid(lats, lons)
        fig.add_trace(go.Scattermap(
            # markers+text con un punto invisible: solo "text" rompe la exportación de Kaleido ("Map error")
            lat=la.ravel(), lon=lo.ravel(), mode="markers+text", marker=dict(size=1, opacity=0),
            hoverinfo="skip", showlegend=False,
            text=[f"{grados(a, 'lat')}<br>{grados(o, 'lon')}" for a, o in zip(la.ravel(), lo.ravel())],
            textposition="top right", textfont=dict(size=9, color=BASES[base_actual()]["texto"])))
        # debajo de las estaciones: donde los rótulos chocan, gana el nombre de la estación
        fig.data = (fig.data[-1], *fig.data[:-1])
    return fig


def texto_mapa(tamano=12):
    """Letra de los nombres de las estaciones: en negrita y del color que mejor se lee sobre el mapa base."""
    return dict(color=BASES[base_actual()]["texto"], size=tamano, weight="bold")


def credito_mapa():
    return BASES[base_actual()]["credito"]


def comuna(nombre):
    """El polígono (GeoJSON) de una comuna."""
    return next(f for f in COMUNAS["features"] if f["properties"]["comuna"] == nombre)


def _puntos(geometria):
    """Todos los vértices (lon, lat) de un Polygon o MultiPolygon."""
    poligonos = geometria["coordinates"] if geometria["type"] == "MultiPolygon" else [geometria["coordinates"]]
    return np.array([p for pol in poligonos for anillo in pol for p in anillo])


def encuadre(lon, lat, ancho, alto, margen=1.5):
    """Centro y zoom de un mapa de ancho × alto px que muestra todos los puntos (lon, lat), con un margen
    alrededor (1,5 = 50 % más que el recuadro de los puntos)."""
    lon, lat = np.asarray(lon), np.asarray(lat)
    dlon = (lon.max() - lon.min()) * margen
    dlat = (lat.max() - lat.min()) * margen / np.cos(np.deg2rad(lat.mean()))  # Mercator estira la latitud
    zoom = min(np.log2(ancho * 360 / (512 * dlon)), np.log2(alto * 360 / (512 * dlat)))
    return dict(center=dict(lat=float((lat.max() + lat.min()) / 2), lon=float((lon.max() + lon.min()) / 2)),
                zoom=float(np.clip(zoom, 6, 12)))


def vista_region(ancho, alto):
    """Centro y zoom que muestran todas las estaciones de la red, sin cortar las del borde."""
    return encuadre([s["lon"] for s in F.SITIOS], [s["lat"] for s in F.SITIOS], ancho, alto, margen=1.12)


def vista_comuna(nombre, ancho=800, alto=620):
    """Centro y zoom del mapa que encuadran la comuna, con un margen alrededor."""
    return encuadre(*_puntos(comuna(nombre)["geometry"]).T, ancho, alto)


def resalta_comuna(nombre):
    """Capas de mapa que rellenan y remarcan una comuna."""
    geo = comuna(nombre)
    return [dict(sourcetype="geojson", source=geo, type="fill", color="rgba(255,214,0,.18)", below="traces"),
            dict(sourcetype="geojson", source=geo, type="line", color="#FFD600", line=dict(width=3),
                 below="traces")]


def sitio_de_comuna(nombre):
    """La estación de la comuna más cercana a su centro o, si no tiene, la más cercana de la región:
    representa a la comuna en el pronóstico."""
    centro = vista_comuna(nombre)["center"]
    propias = [s for s in F.SITIOS if s["comuna"] == nombre] or F.SITIOS
    return min(propias, key=lambda s: (s["lat"] - centro["lat"]) ** 2 + (s["lon"] - centro["lon"]) ** 2)


# ------------------------------------------------------------------ cargas con caché
# Las funciones con caché lanzan la excepción (así no se guarda una falla) y quien las
# llama la atrapa.
@st.cache_data(ttl="15m", refresh_mode="background", show_spinner="Leyendo los pronósticos publicados…")
def carga_publicados():
    return F.lee_pronosticos()


@st.cache_data(ttl="15m", refresh_mode="background", show_spinner="Descargando los METAR de Torquemada, Rodelillo y Santo Domingo…")
def carga_metar():
    return F.metars(HORAS_OBS)


@st.cache_data(ttl="15m", refresh_mode="background", show_spinner="Descargando estaciones VIPNet…")
def carga_vipnet(variable):
    return F.vipnet_variable(variable, HORAS_OBS)


@st.cache_data(ttl="1h", max_entries=40, show_spinner="Consultando Open-Meteo en vivo…")
def carga_vivo(lat, lon):
    return F.pronostico_vivo(lat, lon, F.DIAS_PUBLICADOS, F.DIAS_PUBLICADOS)


@st.cache_data(ttl="15m", refresh_mode="background", show_spinner="Leyendo la grilla de los mapas de superficie…")
def carga_grilla_publicada():
    return F.lee_grilla()


@st.cache_data(ttl="1h", show_spinner="Consultando la grilla en Open-Meteo en vivo (tarda unos segundos)…")
def carga_grilla_viva():
    return F.grilla()


def grilla():
    """(tabla, origen) de la grilla regional: la copia publicada y, si falta, Open-Meteo en vivo.
    (None, error) si ninguna responde."""
    try:
        return carga_grilla_publicada(), "copia publicada"
    except Exception:  # noqa: BLE001
        pass
    try:
        return carga_grilla_viva(), "Open-Meteo en vivo"
    except Exception as ex:  # noqa: BLE001
        return None, str(ex)


@st.cache_data(ttl="10m", max_entries=20, show_spinner="Descargando los datos de la estación…")
def carga_estacion(sitio_id, horas):
    """Lo medido por una estación, sin promediar, para el botón de descarga."""
    return F.datos_estacion(F.SITIO[sitio_id], horas)


def calienta_caches():
    """La llama app.py al arrancar y cada pocos minutos: con las entradas frescas es
    casi gratis; con las vencidas dispara su refresco en segundo plano."""
    for f, args in [(carga_publicados, ()), (carga_metar, ()), *[(carga_vipnet, (v,)) for v in VARS_VIPNET]]:
        f(*args)


def metar_seguro():
    """{código: DataFrame horario} de los METAR; vacío el que no responda."""
    try:
        return carga_metar()
    except Exception:  # noqa: BLE001
        return {c: pd.DataFrame() for c in F.METARS}


def vipnet_seguro(variable):
    try:
        return carga_vipnet(variable)
    except Exception as ex:  # noqa: BLE001
        return {}, [f"VIPNet {variable}: {str(ex)[:120]}"]


def pronostico(s):
    """(pronóstico, origen, error). Primero la copia que publica la GitHub Action cada hora; si
    falta o tiene más de 3 h, Open-Meteo en vivo; si eso también falla, la copia vieja o nada."""
    ahora_utc = pd.Timestamp.now(tz="UTC")
    try:
        generado, pub = carga_publicados()
    except Exception:  # noqa: BLE001
        generado, pub = None, {}
    local = lambda t: t.tz_convert(F.ZONA).strftime("%d/%m %H:%M")  # noqa: E731
    if generado is not None and s["id"] in pub and ahora_utc - generado < VIEJO:
        return pub[s["id"]], f"copia publicada a las {local(generado)}", None
    try:
        return carga_vivo(s["lat"], s["lon"]), "Open-Meteo en vivo", None
    except Exception as ex:  # noqa: BLE001
        if generado is not None and s["id"] in pub:
            return pub[s["id"]], f"copia publicada a las {local(generado)} (desactualizada)", str(ex)
        return VACIO, None, str(ex)


# ------------------------------------------------------------------ contexto de la corrida
def prepara_contexto(sitio_id, pasado, futuro, modelos, con_ensamble):
    """Arma el contexto de esta corrida y lo deja en st.session_state para las páginas."""
    sitio = F.SITIO[sitio_id]
    ahora = F.ahora_local()
    t0 = pd.Timestamp(ahora).floor("h") - pd.Timedelta(days=pasado)
    t_fin = pd.Timestamp(ahora).floor("D") + pd.Timedelta(days=futuro)
    metar = metar_seguro()
    pron, origen, error = pronostico(sitio)
    avisos = []

    def recorta(df):
        if df is None or df.empty:
            return df
        return df[(df.index >= t0) & (df.index < t_fin)]

    def det_var(v):
        return pron["det"].get(v, pd.DataFrame())

    def observado(s, variable):
        """Serie horaria observada de 'variable' en el sitio s (o None), ventana completa."""
        if variable not in s["vars"]:
            return None
        if s["fuente"] == "metar":
            col = F.VARIABLES[variable]["metar"]
            m = metar.get(s["codigo"], pd.DataFrame())
            o = m[col].dropna() if not m.empty and col in m else None
        else:
            series, av = vipnet_seguro(variable)
            avisos.extend(av)
            o = series.get(s["id"])
        return None if o is None else o[o.index >= t0]

    c = SimpleNamespace(sitio=sitio, pasado=pasado, futuro=futuro, modelos=modelos, con_ensamble=con_ensamble,
                        ahora=ahora, t0=t0, t_fin=t_fin, metar=metar, pron=pron, det=pron["det"],
                        pct=pron["pct"], origen_pron=origen, error_pron=error, avisos=avisos,
                        recorta=recorta, det_var=det_var, observado=observado)
    st.session_state["_ctx"] = c
    return c


def contexto():
    return st.session_state["_ctx"]


# ------------------------------------------------------------------ utilidades de gráficos y texto
def barra(boton="resetScale2d"):
    return {"displayModeBar": True, "displaylogo": False, "modeBarButtons": [[boton]]}


def linea_ahora(fig, ahora, xref="x", yref="paper"):
    """add_shape en vez de add_vline: add_vline falla con Timestamps de pandas."""
    x = pd.Timestamp(ahora).isoformat()
    fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, xref=xref, yref=yref,
                  line=dict(color=ROJO, width=1.4, dash="dot"))


def fmt(v, dec, unidad=""):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:.{dec}f}{(' ' + unidad) if unidad else ''}"


def _data_uri(ruta):
    return "data:image/svg+xml;base64," + base64.b64encode(ruta.read_bytes()).decode()


_LOGO_URI = {False: _data_uri(CLARO.logo), True: _data_uri(OSCURO.logo)}
_kaleido = threading.Lock()
_kaleido_listo = False
ANCHO_EXPORTA = 1400
LOGO_ALTO = 46  # px; el logo completo mide 780 × 199,5 (proporción 3,91)


def _area_dibujo(f, ancho, alto):
    """(ancho, alto) en px del área de dibujo ("paper"), que los márgenes automáticos (leyendas, títulos de
    ejes) agrandan sin avisar: se mide en un SVG de prueba, uniendo el recorte de cada subgráfico (los
    recortes de un solo eje ocupan todo el ancho o todo el alto y se descartan)."""
    svg = f.to_image(format="svg", width=ancho, height=alto).decode()
    cajas = [(x, y, w, h) for x, y, w, h in (map(float, c) for c in re.findall(
        r'class="axesclip"><rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg))
        if w < ancho and h < alto]
    if not cajas:  # mapas: sin fondo cartesiano, el área es lo que dejan los márgenes
        m = f.layout.margin
        return ancho - (m.l or 0) - (m.r or 0), alto - (m.t or 0) - (m.b or 0)
    return (max(x + w for x, _, w, _ in cajas) - min(x for x, _, _, _ in cajas),
            max(y + h for _, y, _, h in cajas) - min(y for _, y, _, _ in cajas))


def exporta(fig, formato, oscuro):
    """PNG (al doble de resolución) o PDF vectorial de la figura, con el fondo del modo en que se veía y
    el logo de MetGeo arriba a la derecha. Lo dibuja kaleido con un Chrome que queda abierto (la primera
    exportación tarda unos segundos; las siguientes, décimas)."""
    global _kaleido_listo
    p = OSCURO if oscuro else CLARO
    f = go.Figure(fig)
    if f.layout.map.layers and any(c.sourcetype == "image" for c in f.layout.map.layers):
        # Kaleido no conoce la dirección de la app: la imagen satelital va dentro de la figura
        otras = [c for c in f.layout.map.layers if c.sourcetype != "image"]
        f.update_layout(map_layers=[*_capas_satelite(relativa=False), *otras])
    alto = (fig.layout.height or 450) + LOGO_ALTO + 10
    m = fig.layout.margin
    f.update_layout(template=p.plantilla, paper_bgcolor=p.fondo, plot_bgcolor=p.fondo, height=alto,
                    margin=dict(l=max(m.l or 0, 30), r=max(m.r or 0, 30), t=(m.t or 0) + LOGO_ALTO + 10,
                                b=max(m.b or 0, 30)))
    with _kaleido:
        if not _kaleido_listo:
            import kaleido
            kaleido.start_sync_server(silence_warnings=True)
            _kaleido_listo = True
        ancho_px, alto_px = _area_dibujo(f, ANCHO_EXPORTA, alto)
        # logo justo encima de la esquina superior derecha del área de dibujo, en el margen que se agregó
        f.add_layout_image(source=_LOGO_URI[oscuro], xref="paper", yref="paper", x=1, y=1 + 4 / alto_px,
                           xanchor="right", yanchor="bottom", sizex=LOGO_ALTO * 3.91 / ancho_px,
                           sizey=LOGO_ALTO / alto_px, sizing="contain", layer="above")
        return f.to_image(format=formato, width=ANCHO_EXPORTA, height=alto, scale=2 if formato == "png" else 1)


def grafico(fig, nombre, config=None, key=None):
    """st.plotly_chart más los botones para descargar la figura en PNG o PDF. 'nombre' va en el archivo."""
    st.plotly_chart(fig, config=config or barra(), key=key)
    oscuro = paleta().oscuro
    archivo = f"metgeo_{nombre}_{F.ahora_local():%Y%m%d_%H%M}"
    with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
        for formato, mime, ayuda in [("png", "image/png", "Imagen PNG en alta resolución"),
                                     ("pdf", "application/pdf", "PDF vectorial, editable")]:
            st.download_button(formato.upper(), data=lambda formato=formato: exporta(fig, formato, oscuro),
                               file_name=f"{archivo}.{formato}", mime=mime, on_click="ignore", type="tertiary",
                               icon=":material/download:", help=ayuda, key=f"dl_{key or nombre}_{formato}")


def estilo_mapas():
    """Esquinas redondeadas y un borde suave en los mapas (los gráficos de Plotly que llevan un mapa)."""
    st.html("""<style>
    .stPlotlyChart:has(.maplibregl-map) .js-plotly-plot .plot-container {
        border-radius: 14px; overflow: hidden; border: 1px solid rgba(128,128,128,.35); }
    </style>""")


def logo():
    """Logo de la barra superior según el modo claro u oscuro."""
    p = paleta()
    st.logo(str(p.logo), icon_image=str(p.icono), size="large", link=METGEO)


# íconos de 24×24 (LinkedIn es el de Simple Icons, CC0); van como <img> porque st.html quita los <svg> en línea
_ICONOS = {
    "linkedin": '<path fill="currentColor" d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 '
                '2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 '
                '7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zm1.78 13.02H3.56V9h3.56v11.45zM22.22 0H1.77C.79 '
                '0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/>',
    "instagram": '<g fill="none" stroke="currentColor" stroke-width="2.2"><rect x="2.5" y="2.5" width="19" height="19" '
                 'rx="5.5"/><circle cx="12" cy="12" r="4.3"/></g><circle cx="17.6" cy="6.4" r="1.4" fill="currentColor"/>',
    "web": '<g fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="9.5"/>'
           '<ellipse cx="12" cy="12" rx="4.2" ry="9.5"/><path d="M2.5 12h19M4 7h16M4 17h16"/></g>',
    "newsletter": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round">'
                  '<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><path d="m3 6.5 9 6.5 9-6.5"/></g>',
}


def redes(alineacion="center"):
    """Botones a LinkedIn, Instagram, metgeo.cl y el newsletter de MetGeo. HTML con colores heredados,
    así que se ven bien en modo claro y oscuro."""
    base = ("display:inline-flex;align-items:center;gap:.45rem;padding:.42rem .95rem;border-radius:999px;"
            "font-size:.92rem;font-weight:600;text-decoration:none;line-height:1;")
    botones = []
    for icono, texto, url, color in [("linkedin", "LinkedIn", LINKEDIN, "#0A66C2"),
                                     ("instagram", "Instagram", INSTAGRAM, "#E1306C"),
                                     ("web", "metgeo.cl", METGEO, "#4E94C3"),
                                     ("newsletter", "Newsletter", NEWSLETTER, None)]:
        if color:  # contorno, con el ícono en el color de la marca
            estilo = base + "border:1px solid rgba(128,128,128,.45);color:inherit;"
        else:  # el newsletter destaca: relleno con el azul de MetGeo
            estilo = base + "border:1px solid #004090;background:#004090;color:#FFFFFF;"
            color = "#FFFFFF"
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" style="color:{color}">'
               f'{_ICONOS[icono]}</svg>')
        botones.append(
            f'<a href="{url}" target="_blank" rel="noopener" style="{estilo}">'
            f'<img src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}" width="18" height="18" '
            f'alt=""><span>{texto}</span></a>')
    st.html(f'<div style="display:flex;flex-wrap:wrap;gap:.5rem;justify-content:{alineacion}">'
            f'{"".join(botones)}</div>')


# ------------------------------------------------------------------ estado del tiempo
def estado_por_dia(pron, ahora, dias=5):
    """Lista con el pronóstico de cada día desde hoy: estado del tiempo (el de la mayoría de los 7 modelos,
    ver F.estado_dia), temperaturas mínima y máxima (mediana de los modelos), lluvia (p10, p50 y p90 del
    super-ensamble) y ráfaga máxima (mediana de los modelos). Vacía si el pronóstico no trae estado."""
    codigos = pron["det"].get("estado")
    if codigos is None or codigos.empty:
        return []
    horario = F.estado_horario(codigos)
    temp = pron["det"].get("temperatura", pd.DataFrame()).median(axis=1)
    raf = pron["det"].get("rafaga", pd.DataFrame()).median(axis=1)
    hoy = pd.Timestamp(ahora).normalize()
    filas = []
    for k in range(dias):
        d0, d1 = hoy + pd.Timedelta(days=k), hoy + pd.Timedelta(days=k + 1)
        en = lambda x: x[(x.index > d0) & (x.index <= d1)] if x is not None and len(x) else pd.Series(dtype=float)  # noqa: E731
        estado = F.estado_dia(en(horario))
        if estado is None:
            continue
        lluvia = None
        if pron["pp"] is not None:
            ll = pron["pp"][(pron["pp"].index > d0) & (pron["pp"].index <= d1)]
            if len(ll):
                lluvia = np.percentile(ll.fillna(0).sum().values, [10, 50, 90])
        t, r = en(temp), en(raf)
        filas.append(dict(dia=d0, estado=estado, tmin=t.min() if len(t) else np.nan,
                          tmax=t.max() if len(t) else np.nan, lluvia=lluvia,
                          rafaga=r.max() if len(r) else np.nan))
    return filas


def tarjetas_estado(filas):
    """Tarjetas HTML, una por día, con el ícono y el nombre del estado del tiempo."""
    p = paleta()
    html = ['<div style="display:flex;flex-wrap:wrap;gap:8px">']
    for k, f in enumerate(filas):
        e = F.ESTADO[f["estado"]]
        nombre_dia = "Hoy" if k == 0 else ("Mañana" if k == 1 else DIAS[f["dia"].weekday()].capitalize())
        lluvia = ""
        if f["lluvia"] is not None and f["lluvia"][2] >= 0.5:
            q10, q50, q90 = f["lluvia"]
            lluvia = (f'<div style="font-size:12px;color:{p.lluvia_obs};font-weight:700">{q50:.0f} mm'
                      f'<span style="font-weight:400;opacity:.75"> ({q10:.0f}–{q90:.0f})</span></div>')
        rafaga = (f'<div style="font-size:11px;color:{p.rafaga}">ráfaga {f["rafaga"]:.0f} km/h</div>'
                  if not np.isnan(f["rafaga"]) else "")
        html.append(
            '<div style="flex:1 1 120px;max-width:170px;border:1px solid rgba(128,128,128,.35);border-radius:12px;'
            'padding:10px 8px;text-align:center;font-family:sans-serif">'
            f'<div style="font-weight:700">{nombre_dia} <span style="font-weight:400;opacity:.7">{f["dia"]:%d/%m}</span></div>'
            f'<div style="font-size:38px;line-height:1.25">{e["icono"]}</div>'
            f'<div style="font-size:13px;font-weight:600">{e["nombre"]}</div>'
            f'<div style="font-size:14px;margin-top:2px"><span style="color:#2C7BB6">{fmt(f["tmin"], 0, "°")}</span>'
            f' / <span style="color:#D6604D;font-weight:700">{fmt(f["tmax"], 0, "°")}</span></div>'
            f'{lluvia}{rafaga}</div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def nombre_modelo(m):
    corto, centro, _ = F.MODELOS[m]
    return f"{corto} ({centro})"


def metricas_ahora(c):
    """Última observación del sitio elegido; lo que el sitio no mide queda en «—»."""
    sitio = c.sitio

    def ultimo(variable):
        """(valor, hora) de la última medición del sitio; (nan, None) si no la mide o no hay dato."""
        o = c.observado(sitio, variable)
        o = None if o is None else o.dropna()
        if o is None or o.empty:
            return np.nan, None
        return float(o.iloc[-1]), o.index[-1]

    horas = []
    tarjetas = []
    for var, nombre, dec, unidad, icono in [
        ("temperatura", "Temperatura", 0, "°C", "thermostat"),
        ("humedad", "Humedad", 0, "%", "humidity_percentage"),
        ("viento", "Viento", 0, "km/h", "air"),
        ("rafaga", "Ráfaga", 0, "km/h", "storm"),
        ("presion", "Presión", 0, "hPa", "speed"),
    ]:
        v, h = ultimo(var)
        if h is not None:
            horas.append(h)
        delta = None
        if var == "viento" and h is not None and "direccion" in sitio["vars"]:
            delta = F.cardinal(ultimo("direccion")[0])
        elif var == "presion" and h is not None:
            p = c.observado(sitio, "presion").dropna()
            hace3 = p[p.index <= h - pd.Timedelta(hours=3)]
            delta = f"{v - hace3.iloc[-1]:+.0f} hPa en 3 h" if len(hace3) else None
        # el METAR informa ráfaga solo cuando es significativa: sin dato con METAR vigente = sin ráfagas
        sin_rafagas = (var == "rafaga" and var in sitio["vars"] and np.isnan(v)
                       and not c.metar.get(sitio["codigo"], pd.DataFrame()).empty)
        tarjetas.append((nombre, "sin ráfagas" if sin_rafagas else fmt(v, dec, unidad), delta, icono))

    pp = c.observado(sitio, "precipitacion")
    pp24 = np.nan
    if pp is not None and not pp.empty:
        pp24 = pp[pp.index > pp.index.max() - pd.Timedelta(hours=24)].sum()
        horas.append(pp.index.max())
    tarjetas.append(("Lluvia 24 h", fmt(pp24, 1, "mm"), None, "rainy"))

    if horas:
        h = max(horas)
        st.caption(f"Ahora en {F.etiqueta(sitio)}, comuna de {sitio['comuna']} · última medición a las {h:%H:%M} del {h:%d/%m} "
                   "(hora de Chile). «—»: sin medición de esa variable en esta estación.")
    else:
        st.caption(f"Sin mediciones recientes de {F.etiqueta(sitio)}.")
    # fila horizontal: se reparte en varias líneas sola en pantallas angostas
    with st.container(horizontal=True, gap="small"):
        for nombre, valor, delta, icono in tarjetas:
            st.metric(nombre, valor, delta, delta_color="off", delta_arrow="off", border=True,
                      icon=f":material/{icono}:")


# ------------------------------------------------------------------ controles
def etiqueta_sitio(i):
    return f"{F.etiqueta(F.SITIO[i])} · {F.SITIO[i]['comuna']}"


def _al_cambiar_comuna():
    """Otra comuna: el sitio pasa a ser su primera estación."""
    st.session_state["sitio"] = next(s["id"] for s in F.SITIOS if s["comuna"] == st.session_state["comuna_sitio"])


def controles(por_comuna=True):
    """Barra de controles (reemplaza a la barra lateral): el sitio a la vista y el resto dentro de
    "Ajustes". Arma y devuelve el contexto de la corrida. Sitio y días quedan en la URL para
    compartir la vista; modelos y banda se conservan al cambiar de página. Con 'por_comuna' se elige
    primero la comuna y «Sitio» lista solo sus estaciones (las comunas sin estación no aparecen; en
    «Mapa de estaciones» están todas)."""
    if "sitio" not in st.session_state:  # primera vez: el de la URL compartida o el primero de la red
        pedido = st.query_params.get("sitio")
        st.session_state["sitio"] = pedido if pedido in F.SITIO else F.SITIOS[0]["id"]
    ids = [s["id"] for s in F.SITIOS]
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        if por_comuna:
            st.session_state["comuna_sitio"] = F.SITIO[st.session_state["sitio"]]["comuna"]
            comuna = st.selectbox("Comuna", sorted({s["comuna"] for s in F.SITIOS}), key="comuna_sitio",
                                  on_change=_al_cambiar_comuna, width=200,
                                  help="Filtra las estaciones de «Sitio» a las de esta comuna.")
            ids = [i for i in ids if F.SITIO[i]["comuna"] == comuna]
        sitio_id = st.selectbox("Sitio", ids, format_func=etiqueta_sitio, key="sitio", bind="query-params",
                                width=320 if por_comuna else 400,
                                help="Escribe para buscar por estación o por comuna. Los modelos se consultan en "
                                     "las coordenadas del sitio elegido.")
        with st.popover("Ajustes", icon=":material/tune:"):
            pasado = st.slider("Días hacia atrás", 1, F.DIAS_PUBLICADOS, 3, key="pasado", bind="query-params")
            futuro = st.slider("Días de pronóstico", 1, F.DIAS_PUBLICADOS, 5, key="futuro", bind="query-params")
            modelos = st.multiselect("Modelos", list(F.MODELOS), default=list(F.MODELOS), format_func=nombre_modelo,
                                     key="modelos", persist_state="session")
            con_ensamble = st.toggle("Banda del super-ensamble (p10–p90)", value=True, key="banda",
                                     persist_state="session")
            st.caption("Los datos se renuevan solos cada hora.")
        origen = st.empty()
    c = prepara_contexto(sitio_id, pasado, futuro, modelos, con_ensamble)
    origen.caption(f":material/schedule: Pronóstico: {c.origen_pron or 'no disponible'}")
    if c.error_pron and c.origen_pron is None:
        st.warning("No se pudo obtener el pronóstico (Open-Meteo no respondió y todavía no hay copia publicada). "
                   "Se muestran solo las observaciones; vuelve a intentar en unos minutos.  \n"
                   f"Detalle: `{c.error_pron[:160]}`", icon=":material/cloud_off:")
    elif c.error_pron:
        st.caption(f":material/info: Open-Meteo no respondió; se muestra la {c.origen_pron}.")
    return c
