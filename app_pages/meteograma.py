"""Meteograma: las 6 variables apiladas en un mismo eje de tiempo."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import comun as C
import fuentes as F
from comun import BANDA, DIAS, EJE_T, ROJO, barra, fmt, linea_ahora, nombre_modelo

PAL = C.paleta()
c = C.contexto()
sitio, pasado, futuro, modelos, con_ensamble = c.sitio, c.pasado, c.futuro, c.modelos, c.con_ensamble
ahora, t0, t_fin, metar, pron, det, pct, avisos = c.ahora, c.t0, c.t_fin, c.metar, c.pron, c.det, c.pct, c.avisos
origen_pron = c.origen_pron
observado, recorta, det_var = c.observado, c.recorta, c.det_var

fuente_mod = st.selectbox("Pronóstico a mostrar", ["mediana"] + modelos,
                          format_func=lambda m: "Mediana de los modelos elegidos" if m == "mediana"
                          else nombre_modelo(m), key="pronostico", bind="query-params")
filas = ["temperatura", "humedad", "viento", "direccion", "presion", "precipitacion"]
titulos = {"temperatura": "Temperatura (°C)", "humedad": "Humedad relativa (%)",
           "viento": "Viento y ráfaga (km/h)", "direccion": "Dirección del viento",
           "presion": "Presión al nivel del mar (hPa)", "precipitacion": "Precipitación (mm/h)"}
fm = make_subplots(rows=len(filas), cols=1, shared_xaxes=True, vertical_spacing=0.045,
                   subplot_titles=[titulos[f] for f in filas])
fm.update_annotations(x=0, xanchor="left", font=dict(size=13))
color_mod = PAL.azul if fuente_mod == "mediana" else F.MODELOS[fuente_mod][2]
etiqueta_mod = "mediana de modelos" if fuente_mod == "mediana" else F.MODELOS[fuente_mod][0]

def serie_mod(v):
    dv = det_var(v)
    df = recorta(dv[[m for m in modelos if m in dv]])
    if df is None or df.empty:
        return None
    if fuente_mod != "mediana":
        return df[fuente_mod] if fuente_mod in df else None
    if v == "direccion":  # mediana circular aproximada: por componentes
        rad = np.deg2rad(df)
        return (np.rad2deg(np.arctan2(np.sin(rad).mean(axis=1), np.cos(rad).mean(axis=1))) % 360)
    return df.median(axis=1)

ya = set()
for fila, v in enumerate(filas, start=1):
    leyenda = lambda nombre: nombre not in ya and not ya.add(nombre)  # noqa: E731
    if con_ensamble and pct.get(v) is not None:
        b = recorta(pct[v])
        if b is not None:
            fm.add_trace(go.Scatter(x=np.r_[b.index, b.index[::-1]], y=np.r_[b.p90, b.p10[::-1]],
                                    fill="toself", fillcolor=BANDA, line=dict(width=0), hoverinfo="skip",
                                    name="super-ensamble p10–p90", legendgroup="ens",
                                    showlegend=leyenda("ens")), row=fila, col=1)
    s = serie_mod(v)
    if s is not None:
        if v == "precipitacion":
            fm.add_trace(go.Bar(x=s.index, y=s.values, marker_color=color_mod, opacity=.8, name=etiqueta_mod,
                                legendgroup="mod", showlegend=leyenda("mod")), row=fila, col=1)
        else:
            fm.add_trace(go.Scatter(x=s.index, y=s.values, mode="markers" if v == "direccion" else "lines",
                                    line=dict(color=color_mod, width=2), marker=dict(size=4, color=color_mod),
                                    name=etiqueta_mod, legendgroup="mod", showlegend=leyenda("mod")),
                         row=fila, col=1)
    if v == "viento":
        r = serie_mod("rafaga")
        if r is not None:
            fm.add_trace(go.Scatter(x=r.index, y=r.values, line=dict(color=color_mod, width=1.2, dash="dot"),
                                    name=f"ráfaga ({etiqueta_mod})", legendgroup="raf",
                                    showlegend=leyenda("raf")), row=fila, col=1)
    o = recorta(observado(sitio, v))
    if o is not None and len(o):
        fm.add_trace(go.Scatter(x=o.index, y=o.values, mode="markers" if v == "direccion" else "lines",
                                line=dict(color=PAL.tinta, width=2.2), marker=dict(size=4, color=PAL.tinta),
                                name=f"observado · {sitio['nombre']}", legendgroup="obs",
                                showlegend=leyenda("obs")), row=fila, col=1)
    if v == "viento":
        o = recorta(observado(sitio, "rafaga"))
        if o is not None and len(o):
            fm.add_trace(go.Scatter(x=o.index, y=o.values, mode="markers", marker=dict(color=PAL.tinta, size=7,
                                    symbol="triangle-up"), name="ráfaga observada", legendgroup="rafo",
                                    showlegend=leyenda("rafo")), row=fila, col=1)
    linea_ahora(fm, pd.Timestamp(ahora), xref=f"x{fila if fila > 1 else ''}",
                yref=f"y{fila if fila > 1 else ''} domain")
fm.update_yaxes(range=[0, 360], tickvals=[0, 90, 180, 270, 360], ticktext=["N", "E", "S", "O", "N"],
                row=filas.index("direccion") + 1, col=1)
fm.update_layout(height=1300, hovermode="x unified", margin=dict(l=10, r=10, t=70, b=10), bargap=0.1,
                 legend=dict(orientation="h", y=1.0, yanchor="bottom", x=0, xanchor="left"))
fm.update_layout(legend_y=1.035)
fm.update_xaxes(**EJE_T, showgrid=True)
fm.update_xaxes(showticklabels=True, row=len(filas), col=1)
C.grafico(fm, f"meteograma_{sitio['id']}")
faltan = [F.VARIABLES[v]["nombre"].lower() for v in filas if v not in sitio["vars"]]
if faltan:
    st.caption(f"{sitio['nombre']} no mide: {', '.join(faltan)} (solo pronóstico en esos paneles).")
