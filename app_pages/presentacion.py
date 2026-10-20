"""Presentación: portada del proyecto, condiciones actuales, accesos a cada vista, fuentes y autoría."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import comun as C
import fuentes as F
from comun import BANDA, DIAS, EJE_T, ROJO, barra, fmt, linea_ahora, nombre_modelo

PAL = C.paleta()
N_VIPNET = sum(s["fuente"] == "vipnet" for s in F.SITIOS)
CUENTA = {v: sum(v in s["vars"] and s["fuente"] == "vipnet" for s in F.SITIOS)
          for v in ("precipitacion", "temperatura", "humedad", "viento")}

FOTO_PORTADA = "app/static/portada.jpg"  # bahía de Valparaíso, Esri World Imagery (servida desde static/)
TARJETAS = [
    ("Comparar modelos", "comparar", ":material/stacked_line_chart:",
     "Una variable a la vez: los 7 modelos, la banda del super-ensamble y lo observado. Debajo, qué modelo "
     "anduvo mejor en los últimos días (sesgo, error medio, correlación)."),
    ("Lluvia", "lluvia", ":material/water_drop:",
     "Acumulado por estación sobre imagen satelital, histograma hora a hora, acumulado del evento y lluvia "
     "esperada cada 6 horas con ráfagas."),
    ("Meteograma", "meteograma", ":material/monitoring:",
     "Temperatura, humedad, viento, dirección, presión y lluvia apiladas en un mismo eje de tiempo, para un "
     "modelo o la mediana de todos."),
    ("Mapa de estaciones", "mapa", ":material/map:",
     "La última medición de cada estación por comuna: dónde hace más frío, dónde llueve más. Estado del tiempo "
     "de cada comuna y descarga de los datos de cualquier estación."),
]

st.markdown(f"""
<div style="position:relative;border-radius:18px;padding:3rem 2.4rem 2.4rem;margin:.4rem 0 1.4rem;color:white;
        background:linear-gradient(115deg,rgba(0,32,80,.90) 30%,rgba(0,64,144,.40)),
                   url('{FOTO_PORTADA}') center 60%/cover;">
  <div style="font-size:.85rem;letter-spacing:.12em;text-transform:uppercase;opacity:.85">
    Monitor meteorológico de la Región de Valparaíso</div>
  <div style="font-size:2.9rem;font-weight:800;line-height:1.1;margin:.35rem 0 .8rem">MetGeo Valparaíso</div>
  <div style="font-size:1.15rem;max-width:46rem;opacity:.95;line-height:1.5">
Estaciones de la costa al valle y la cordillera, modelos globales y verificación de pronósticos en un solo lugar.</div>
  <div style="display:flex;flex-wrap:wrap;gap:.6rem;margin-top:1.4rem">
{"".join(f'<span style="background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.3);'
         f'border-radius:999px;padding:.35rem .9rem;font-size:.92rem"><b>{a}</b> {b}</span>'
         for a, b in [(str(len(F.SITIOS)), "sitios de observación"), (str(len(C.NOMBRES_COMUNAS)), "comunas"), ("7", "modelos globales"),
                      ("143", "miembros de ensamble"), ("cada hora", "se actualiza")])}
  </div>
  <div style="position:absolute;right:1rem;bottom:.6rem;font-size:.72rem;opacity:.7">Imagen: Esri World Imagery, bahía de Valparaíso</div>
</div>""", unsafe_allow_html=True)

# --- ahora mismo
st.subheader("Ahora mismo", icon=":material/schedule:", anchor=False)
c = C.controles()
sitio, ahora, metar, pron, avisos = c.sitio, c.ahora, c.metar, c.pron, c.avisos
origen_pron, observado, det_var = c.origen_pron, c.observado, c.det_var
C.metricas_ahora(c)
ahora_h = pd.Timestamp(ahora).floor("h")
prox = lambda df: df[(df.index > ahora_h) & (df.index <= ahora_h + pd.Timedelta(hours=24))]  # noqa: E731
temp = det_var("temperatura")
raf = det_var("rafaga")
dias_estado = C.estado_por_dia(pron, ahora)
if dias_estado:
    st.markdown(f"**Estado del tiempo en {sitio['nombre']}** ({sitio['comuna']}), según los 7 modelos")
    C.tarjetas_estado(dias_estado)
    st.caption("Estado: el que dan la mayoría de los modelos (la precipitación cuenta si dura al menos "
               f"{F.HORAS_PARA_PRECIPITACION} horas). Temperaturas: mediana de los modelos. Lluvia: mediana del "
               "super-ensamble y, entre paréntesis, su rango p10–p90. Por comuna: «Mapa de estaciones».")
if not temp.empty:
    st.markdown(f"**Próximas 24 horas en {sitio['nombre']}** (mediana de los 7 modelos; la lluvia, del "
                "super-ensamble)")
    fila = st.container(horizontal=True, gap="small")
    tm = prox(temp).median(axis=1)
    fila.metric("Temperatura mínima", fmt(tm.min(), 0, "°C"), border=True)
    fila.metric("Temperatura máxima", fmt(tm.max(), 0, "°C"), border=True)
    fila.metric("Ráfaga máxima", fmt(prox(raf).median(axis=1).max(), 0, "km/h") if not raf.empty else "—", border=True)
    if pron["pp"] is not None:
        ll = prox(pron["pp"]).sum().values
        q10, q50, q90 = np.percentile(ll, [10, 50, 90])
        fila.metric("Lluvia esperada", fmt(q50, 0, "mm"), f"rango {q10:.0f}–{q90:.0f} mm", delta_color="off", border=True)

    # adelanto: 24 h hacia atrás y 72 h hacia adelante
    ventana = lambda df: df[(df.index > ahora_h - pd.Timedelta(hours=24)) &  # noqa: E731
                            (df.index <= ahora_h + pd.Timedelta(hours=72))]
    fp = make_subplots(specs=[[{"secondary_y": True}]])
    if pron["pp"] is not None:
        q = F.percentiles(ventana(pron["pp"]))
        fp.add_trace(go.Bar(x=q.index - pd.Timedelta(minutes=30), y=q.p50, width=3.6e6 * 0.85,
                            marker_color=PAL.lluvia_esp, name="lluvia esperada (mm/h)", opacity=.45),
                     secondary_y=True)
    # lluvia observada encima, más angosta y opaca, para contrastarla con la esperada
    ll_obs = observado(sitio, "precipitacion")
    if ll_obs is not None:
        ll_obs = ll_obs[ll_obs.index > ahora_h - pd.Timedelta(hours=24)]
        fp.add_trace(go.Bar(x=ll_obs.index - pd.Timedelta(minutes=30), y=ll_obs.values, width=3.6e6 * 0.5,
                            marker_color=PAL.lluvia_obs, name="lluvia observada (mm/h)", opacity=.9),
                     secondary_y=True)
    tv = ventana(temp).median(axis=1)
    fp.add_trace(go.Scatter(x=tv.index, y=tv.values, line=dict(color="#d6604d", width=3),
                            name="temperatura pronosticada (°C)"), secondary_y=False)
    o = observado(sitio, "temperatura")
    if o is not None:
        o = o[o.index > ahora_h - pd.Timedelta(hours=24)]
        fp.add_trace(go.Scatter(x=o.index, y=o.values, line=dict(color=PAL.tinta, width=2.4),
                                name="temperatura observada (°C)"), secondary_y=False)
    linea_ahora(fp, pd.Timestamp(ahora))
    fp.update_yaxes(title_text="°C", secondary_y=False)
    tope = float(q.p50.max()) if pron["pp"] is not None and len(q) else 1.0
    if ll_obs is not None and len(ll_obs):
        tope = max(tope, float(ll_obs.max()))
    fp.update_yaxes(title_text="mm/h", secondary_y=True, showgrid=False, tickmode="auto",
                    range=[0, max(tope, 1.0) * 2.2])  # la lluvia queda en la mitad de abajo
    fp.update_layout(title=f"Ayer, hoy y los próximos 3 días · {sitio['nombre']}", height=330,
                     margin=dict(l=10, r=10, t=45, b=10), hovermode="x unified", bargap=0, barmode="overlay",
                     legend=dict(orientation="h", y=-0.25, yanchor="top"))
    fp.update_xaxes(**EJE_T)
    C.grafico(fp, f"proximos_dias_{sitio['id']}", key="adelanto")
    st.caption("El sitio se cambia arriba, en «Sitio». La línea punteada roja marca la hora actual.")

# --- qué se puede hacer
st.subheader("Qué puedes hacer aquí", icon=":material/explore:", anchor=False)
cols = st.columns(len(TARJETAS))
for col, (nombre, archivo, icono, texto) in zip(cols, TARJETAS):
    with col.container(border=True, height=260):
        st.markdown(f"**{nombre}**")
        st.caption(texto)
        st.page_link(f"app_pages/{archivo}.py", label="Abrir", icon=icono, width="stretch")

# --- cómo funciona
st.subheader("Cómo funciona", icon=":material/settings_suggest:", anchor=False)
col_red, col_pasos = st.columns([5, 6], gap="large")
with col_red:
    fred = go.Figure()
    for g, color in PAL.grupos.items():
        ss = [x for x in F.SITIOS if x["grupo"] == g]
        fred.add_trace(go.Scattermap(lat=[x["lat"] for x in ss], lon=[x["lon"] for x in ss], mode="markers",
                                     marker=dict(size=11, color=color), name=F.NOMBRE_GRUPO[g],
                                     text=[f"{x['nombre']} ({x['comuna']})" for x in ss],
                                     hovertemplate="%{text}<extra></extra>"))
    C.prepara_mapa(fred, **C.vista_region(600, 436))
    # leyenda bajo el mapa, para que no tape las estaciones del sur
    fred.update_layout(margin=dict(l=0, r=0, t=0, b=34), height=470,
                       legend=dict(orientation="h", y=0, yanchor="top", x=0, bgcolor="rgba(0,0,0,0)"))
    C.grafico(fred, "red_de_estaciones", config=barra("resetViewMap"), key="mapa_red")
    st.caption(f"La red: {N_VIPNET} estaciones VIPNet y los METAR de Torquemada, Rodelillo y Santo Domingo, agrupadas "
               f"en la costa, el valle (bajo los 1000 m) y la cordillera (1000 m o más). "
               f"Mapa base: {C.credito_mapa()}.")
with col_pasos:
    for n, titulo, texto in [
        ("1", "Observa", f"Cada 15 minutos se leen las {N_VIPNET} estaciones de la red VIPNet (DGA/MOP) del "
                         f"Región de Valparaíso, que miden cada 30 minutos lluvia ({CUENTA['precipitacion']}), temperatura "
                         f"({CUENTA['temperatura']}), humedad ({CUENTA['humedad']}) y viento ({CUENTA['viento']}), "
                         "y los METAR de Torquemada (Concón), Rodelillo (Valparaíso) y Santo Domingo, las únicas "
                         "fuentes públicas de ráfagas, dirección del viento y presión."),
        ("2", "Pronostica", "Una GitHub Action baja cada hora, para cada sitio, el pronóstico de 7 modelos "
                            "globales (GFS, IFS, ICON, GEM, GSM, UM y ARPEGE) y de 143 miembros de "
                            "ensamble de cuatro centros, que dan la banda de incertidumbre."),
        ("3", "Compara", "Lo ya ocurrido se contrasta con lo que cada modelo pronosticó para esas mismas "
                         "horas: sesgo, error medio y correlación, para saber en quién confiar esta semana."),
    ]:
        st.markdown(
            f'<div style="display:flex;gap:1rem;align-items:flex-start;margin-bottom:1.1rem">'
            f'<div style="flex:0 0 2.4rem;height:2.4rem;border-radius:50%;background:#004090;color:white;'
            f'font-weight:800;display:flex;align-items:center;justify-content:center">{n}</div>'
            f'<div><div style="font-weight:700;font-size:1.05rem">{titulo}</div>'
            f'<div style="opacity:.8;line-height:1.5">{texto}</div></div></div>', unsafe_allow_html=True)

# --- fuentes y advertencias
st.subheader("Fuentes y advertencias", icon=":material/fact_check:", anchor=False)
col_f, col_c = st.columns([7, 5], gap="large")
col_f.markdown("""
| Fuente | Qué aporta | Frecuencia |
|---|---|---|
| [VIPNet](https://vipnet.mop.gob.cl) (DGA/MOP) | lluvia, temperatura, humedad y viento en __VIP__ estaciones | 30 min |
| [METAR](https://aviationweather.gov) SCVM (Torquemada), SCRD (Rodelillo) y SCSN (Santo Domingo), NOAA AWC | temperatura, humedad, viento, ráfaga, dirección, presión QNH | 1 h |
| [Open-Meteo](https://open-meteo.com) | GFS (NOAA), IFS (ECMWF), ICON (DWD), GEM (Canadá), GSM (JMA), UM (UK Met Office), ARPEGE (Météo-France) | 1 h |
| [Open-Meteo Ensemble](https://open-meteo.com/en/docs/ensemble-api) | GEFS (31) + IFS-ENS (51) + ICON-EPS (40) + GEPS (21) = 143 miembros | 1 h |
| Esri World Imagery | imagen satelital de los mapas (una imagen fija, no mosaicos en vivo) | — |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) · [BCN](https://www.bcn.cl/siit/mapas_vectoriales) | mapa de calles · límites comunales | — |
""".replace("__VIP__", str(N_VIPNET)))
col_c.markdown("""
- Datos observados **preliminares**, sin control de calidad.
- Los METAR informan ráfaga solo cuando es significativa; el de Rodelillo no informa todas las horas.
- La presión del METAR es QNH, equivalente en la práctica a la presión al nivel del mar.
- Los días pasados de Open-Meteo son pronósticos de corto plazo, no reanálisis; parte del error medido es de
  representatividad (punto de grilla contra estación).
- Es una herramienta de divulgación: **no reemplaza los avisos de SENAPRED ni de la DMC**.
""")

# --- autoría
st.space("medium")
with st.container(horizontal=True, vertical_alignment="center", gap="large"):
    st.image(str(PAL.logo), width=300)
    st.markdown(
        f"Hecho por **Bruno Herrera** · MetGeo Spa  \nversión {C.VERSION}")
    with st.container(horizontal=True, gap="small", width="content"):
        st.link_button("Suscríbete al newsletter", C.NEWSLETTER, icon=":material/mail:", type="primary")
        st.link_button("metgeo.cl", C.METGEO, icon=":material/public:")
        st.link_button("Instagram @metgeo.spa", C.INSTAGRAM, icon=":material/photo_camera:")
        st.link_button("LinkedIn MetGeo Spa", C.LINKEDIN, icon=":material/work:")
st.caption(f"Consultado el {ahora:%d/%m/%Y %H:%M} (hora de Chile) · pronóstico: "
           f"{origen_pron or 'no disponible'}.")
for v in C.VARS_VIPNET:
    avisos.extend(C.vipnet_seguro(v)[1])
avisos += [f"METAR {codigo}: sin datos" for codigo, df in metar.items() if df.empty]
if avisos:
    with st.expander("Avisos de descarga"):
        st.write("\n".join(f"- {a}" for a in sorted(set(avisos))))
