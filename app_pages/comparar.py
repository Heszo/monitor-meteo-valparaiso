"""Comparar modelos: una variable a la vez, los 7 modelos, el super-ensamble y lo observado, con verificación."""
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

var = st.segmented_control("Variable", list(F.VARIABLES), default="temperatura", required=True,
                           format_func=lambda k: F.VARIABLES[k]["nombre"], key="variable", bind="query-params")
V = F.VARIABLES[var]
acumular = False
if var == "precipitacion":
    acumular = st.toggle("Mostrar acumulado desde el inicio de la ventana", value=False, key="acumulado")
histograma = var == "precipitacion" and not acumular

dv = det_var(var)
mod_df = recorta(dv[[m for m in modelos if m in dv]])
obs = recorta(observado(sitio, var))
banda = None
if acumular:
    mod_df = mod_df.fillna(0).cumsum()
    obs = obs.cumsum() if obs is not None else None
    if con_ensamble and pron["pp"] is not None:
        banda = F.percentiles(recorta(pron["pp"]).fillna(0).cumsum())
elif con_ensamble and pct.get(var) is not None:
    banda = recorta(pct[var])
unidad = "mm" if acumular else V["unidad"]

# en el histograma de lluvia, el valor de T es lo caído en (T-1h, T]: escalón "vh" y barras
# centradas media hora antes
forma = "vh" if histograma else "linear"
fig = go.Figure()
if banda is not None:
    x = banda.index
    if histograma:
        fig.add_trace(go.Scatter(x=x, y=banda.p90, line=dict(width=0, shape=forma), showlegend=False,
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=banda.p10, line=dict(width=0, shape=forma), fill="tonexty",
                                 fillcolor=BANDA, name="super-ensamble p10–p90", hoverinfo="skip"))
    else:
        fig.add_trace(go.Scatter(x=np.r_[x, x[::-1]], y=np.r_[banda.p90, banda.p10[::-1]], fill="toself",
                                 fillcolor=BANDA, line=dict(width=0), name="super-ensamble p10–p90",
                                 hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=banda.p50, line=dict(color=PAL.ens, width=1.5, dash="dash", shape=forma),
                             name="super-ensamble mediana"))
if histograma and obs is not None and len(obs):
    fig.add_trace(go.Bar(x=obs.index - pd.Timedelta(minutes=30), y=obs.values, width=3.6e6 * 0.85,
                         marker_color=PAL.tinta, opacity=0.8, name=f"observado · {sitio['nombre']}"))
modo = "markers" if var == "direccion" else "lines"
for m in mod_df.columns:
    fig.add_trace(go.Scatter(x=mod_df.index, y=mod_df[m], mode=modo, name=nombre_modelo(m),
                             line=dict(color=F.MODELOS[m][2], width=1.6, shape=forma), marker=dict(size=4)))
if not histograma and obs is not None and len(obs):
    fig.add_trace(go.Scatter(x=obs.index, y=obs.values, mode="lines+markers" if var != "direccion" else "markers",
                             name=f"observado · {sitio['nombre']}", line=dict(color=PAL.tinta, width=2.6),
                             marker=dict(size=5, color=PAL.tinta)))
linea_ahora(fig, pd.Timestamp(ahora))
fig.update_layout(title=f"{V['nombre']}{' acumulada' if acumular else ''} ({unidad}) · {sitio['nombre']}",
                  height=460, hovermode="x unified", margin=dict(l=10, r=10, t=50, b=10),
                  legend=dict(orientation="h", y=-0.18, yanchor="top"))
if var == "direccion":
    fig.update_yaxes(range=[0, 360], tickvals=[0, 90, 180, 270, 360], ticktext=["N", "E", "S", "O", "N"])
fig.update_xaxes(**EJE_T)
C.grafico(fig, f"comparar_{var}_{sitio['id']}")
if obs is None:
    disponibles = [F.SITIO[s["id"]]["nombre"] for s in F.SITIOS if var in s["vars"]]
    st.info(icon=":material/sensors_off:", body=f"{sitio['nombre']} no mide {V['nombre'].lower()}. "
            + (f"Sitios que sí: {', '.join(disponibles)}." if disponibles else
               "Ninguna estación abierta de la región la mide."))

# verificación
st.markdown(f"**¿Qué modelo anduvo mejor?** Pronóstico contra lo observado en {sitio['nombre']}, "
            f"horas ya ocurridas de la ventana ({pasado} días)")
if obs is not None and len(obs) and not acumular:
    tabla = F.verificacion(mod_df, obs, var, pd.Timestamp(ahora))
    if banda is not None:
        t_ens = F.verificacion(banda[["p50"]].rename(columns={"p50": "super-ensamble"}), obs, var,
                               pd.Timestamp(ahora))
        tabla = pd.concat([tabla, t_ens]).sort_values("mae")
    if tabla.empty:
        st.caption("Todavía no hay horas en común entre observado y pronóstico.")
    else:
        tabla["Modelo"] = [nombre_modelo(m) if m in F.MODELOS else "Super-ensamble (mediana)"
                           for m in tabla.modelo]
        col_t, col_g = st.columns([3, 2])
        dec = V["decimales"] + 1
        col_t.dataframe(
            tabla[["Modelo", "n", "sesgo", "mae", "rmse", "r"]].rename(columns={
                "n": "Horas", "sesgo": f"Sesgo ({V['unidad']})", "mae": f"MAE ({V['unidad']})",
                "rmse": f"RMSE ({V['unidad']})", "r": "Correlación"}),
            hide_index=True, width="stretch",
            column_config={c: st.column_config.NumberColumn(format=f"%.{dec}f")
                           for c in [f"Sesgo ({V['unidad']})", f"MAE ({V['unidad']})",
                                     f"RMSE ({V['unidad']})"]} |
            {"Correlación": st.column_config.NumberColumn(format="%.2f")})
        fb = go.Figure(go.Bar(
            x=tabla.mae, y=tabla.Modelo, orientation="h",
            marker_color=[F.MODELOS[m][2] if m in F.MODELOS else PAL.ens for m in tabla.modelo],
            text=[f"{v:.{dec}f}" for v in tabla.mae], textposition="outside"))
        fb.update_layout(title=f"Error absoluto medio ({V['unidad']}) · menor es mejor", height=300,
                         margin=dict(l=10, r=30, t=40, b=10), yaxis=dict(autorange="reversed"))
        with col_g:
            C.grafico(fb, f"error_{var}_{sitio['id']}")
        st.caption("Sesgo > 0: el modelo sobrestima. Los días pasados de Open-Meteo son pronósticos de "
                   "corto plazo de las corridas recientes, no reanálisis. El modelo se compara en el punto "
                   "de grilla más cercano a la estación, así que parte del error es de representatividad.")
elif acumular:
    st.caption("Desactiva el acumulado para ver las métricas por hora.")
else:
    st.caption("Sin observación en este sitio para esta variable.")
