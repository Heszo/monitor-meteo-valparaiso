"""Lluvia: mapa del acumulado observado, histograma horario, acumulado y tarjetas de 6 h."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import comun as C
import fuentes as F
from comun import BANDA, DIAS, EJE_T, NEGRO, ROJO, barra, fmt, linea_ahora, nombre_modelo

PAL = C.paleta()
c = C.contexto()
sitio, pasado, futuro, modelos, con_ensamble = c.sitio, c.pasado, c.futuro, c.modelos, c.con_ensamble
ahora, t0, t_fin, metar, pron, det, pct, avisos = c.ahora, c.t0, c.t_fin, c.metar, c.pron, c.det, c.pct, c.avisos
origen_pron = c.origen_pron
observado, recorta, det_var = c.observado, c.recorta, c.det_var

ESCALA_LLUVIA = [(25, "#FFF3B0"), (50, "#B8E186"), (75, "#41B6C4"), (100, "#2C7FB8"), (150, "#8856A7"),
                 (np.inf, "#E7298A")]
NIVELES_6H = list(zip((10, 25, np.inf), ("débil", "moderada", "fuerte"), PAL.niveles))
AZUL = PAL.azul

lluvia_obs, av = C.vipnet_seguro("precipitacion")
avisos.extend(av)
activas = [s for s in F.SITIOS if s["id"] in lluvia_obs]
ahora_h = pd.Timestamp(ahora).floor("h")
ini = t0
obs_ll = {i: o[o.index > ini] for i, o in lluvia_obs.items()}
tot = {i: float(o.sum()) for i, o in obs_ll.items()}
P = recorta(pron["pp"])
P = P[P.index > ini] if P is not None else None
R = pron["raf6h"]

st.caption(f"Lluvia observada desde el {DIAS[ini.weekday()]} {ini:%d/%m %H:%M} (inicio de la ventana; "
           f"se cambia con «Días hacia atrás») y pronóstico del super-ensamble en {sitio['nombre']}.")
fila = st.container(horizontal=True, gap="small")
for g in F.GRUPOS:
    v = [tot[s["id"]] for s in activas if s["grupo"] == g]
    fila.metric(f"Observado* {F.NOMBRE_GRUPO[g]} (mm)",
                "—" if not v else (f"{min(v):.0f}–{max(v):.0f}" if len(v) > 1 else f"{v[0]:.0f}"), border=True,
                help=f"Rango del acumulado entre las {len(v)} estaciones del grupo.")
if P is not None and not P.empty:
    resto = P[P.index > ahora_h].sum().values
    r10, r50, r90 = np.percentile(resto, [10, 50, 90])
    fila.metric(f"Faltan en {sitio['nombre']} desde las {ahora_h:%H} h (mm)", f"{r50:.0f}",
                f"rango {r10:.0f}–{r90:.0f}", delta_color="off", border=True,
                help=f"Lluvia pronosticada de aquí al fin del horizonte ({futuro} días).")

col_mapa, col_graf = st.columns([5, 7], gap="medium")
with col_mapa:
    st.markdown("**Acumulado observado\\***")
    mm = [tot[s["id"]] for s in activas]
    fmap = go.Figure(go.Scattermap(
        lat=[s["lat"] for s in activas], lon=[s["lon"] for s in activas], mode="markers+text",
        marker=dict(size=14, color=[next(cc for lim, cc in ESCALA_LLUVIA if v < lim) for v in mm]),
        text=[f"{s['nombre']} {v:.0f}" for s, v in zip(activas, mm)], customdata=[s["comuna"] for s in activas],
        textposition="middle right", textfont=C.texto_mapa(11),
        hovertemplate="%{text} mm (%{customdata})<extra></extra>"))
    C.prepara_mapa(fmap, **C.vista_region(560, 470))
    fmap.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=470, showlegend=False)
    C.grafico(fmap, "mapa_lluvia", config=barra("resetViewMap"), key="mapa_lluvia")
    st.caption("Colores: < 25 · 25–50 · 50–75 · 75–100 · 100–150 · > 150 mm. Acerca el mapa para leer los nombres "
               f"donde las estaciones están juntas. Mapa base: {C.credito_mapa()}.")
    GRUPOS_TXT = "Los tres grupos"
    ver = st.selectbox("Ver en los gráficos", [GRUPOS_TXT, *[s["id"] for s in activas]], key="estacion",
                       bind="query-params",
                       format_func=lambda i: i if i == GRUPOS_TXT else f"{F.SITIO[i]['nombre']} · {F.SITIO[i]['comuna']}",
                       help="Compara el pronóstico con el promedio de cada grupo o con una estación.")
elegida = None if ver == GRUPOS_TXT else ver
if elegida:
    curvas = [(F.SITIO[elegida]["nombre"], [elegida], PAL.grupos[F.SITIO[elegida]["grupo"]])]
else:
    curvas = [(f"{F.NOMBRE_GRUPO[g]} ({sum(s['grupo'] == g for s in activas)} est.)",
               [s["id"] for s in activas if s["grupo"] == g], colg)
              for g, colg in PAL.grupos.items() if any(s["grupo"] == g for s in activas)]

with col_graf:
    if P is None or P.empty:
        st.warning("El super-ensamble no respondió; los datos se renuevan solos cada hora.")
    else:
        q = F.percentiles(P)
        fa = go.Figure()
        fa.add_trace(go.Scatter(x=q.index, y=q.p90, line=dict(width=0, shape="vh"), showlegend=False,
                                hoverinfo="skip"))
        fa.add_trace(go.Scatter(x=q.index, y=q.p10, line=dict(width=0, shape="vh"), fill="tonexty",
                                fillcolor="rgba(157,191,221,.55)", name="pronóstico p10–p90", hoverinfo="skip"))
        fa.add_trace(go.Bar(x=q.index - pd.Timedelta(minutes=30), y=q.p50, width=3.6e6 * 0.85,
                            marker_color=AZUL, opacity=.85, name="pronóstico mediana"))
        for nombre, ids, colg in curvas:
            tab = pd.concat([obs_ll[i] for i in ids], axis=1, sort=True)
            fa.add_trace(go.Scatter(x=tab.index - pd.Timedelta(minutes=30), y=tab.mean(axis=1), mode="lines",
                                    line=dict(color=colg, width=2.4), name=f"observado* {nombre}"))
        linea_ahora(fa, ahora_h)
        fa.update_layout(title="Precipitación por hora (mm)", height=360, margin=dict(l=10, r=10, t=40, b=10),
                         bargap=0, legend=dict(orientation="h", y=-.3, yanchor="top"), hovermode="x unified")
        fa.update_xaxes(**EJE_T)
        C.grafico(fa, f"lluvia_por_hora_{sitio['id']}", key="hist_lluvia")

        A = F.percentiles(P.fillna(0).cumsum())
        fb = go.Figure()
        fb.add_trace(go.Scatter(x=np.r_[A.index, A.index[::-1]], y=np.r_[A.p90, A.p10[::-1]], fill="toself",
                                fillcolor="rgba(157,191,221,.55)", line=dict(width=0),
                                name="pronóstico p10–p90", hoverinfo="skip"))
        fb.add_trace(go.Scatter(x=A.index, y=A.p50, line=dict(color=AZUL, width=3), name="pronóstico mediana"))
        for nombre, ids, colg in curvas:
            for i in ids:
                o = obs_ll[i]
                fb.add_trace(go.Scatter(x=[ini, *o.index], y=[0, *o.cumsum()], line=dict(color=colg, width=1.6),
                                        name=F.SITIO[i]["nombre"], showlegend=False))
        linea_ahora(fb, ahora_h)
        fb.update_layout(title=dict(text="Acumulado desde el inicio (mm)",
                                    subtitle=dict(text=f"pronóstico total {A.p50.iloc[-1]:.0f} mm "
                                                       f"({A.p10.iloc[-1]:.0f}–{A.p90.iloc[-1]:.0f})")),
                         height=290, margin=dict(l=10, r=10, t=60, b=10), showlegend=False,
                         hovermode="x unified")
        fb.update_xaxes(**EJE_T)
        C.grafico(fb, f"lluvia_acumulada_{sitio['id']}", key="acum_lluvia")

if P is not None and not P.empty:
    st.markdown("**Lluvia esperada cada 6 horas** (mediana del pronóstico; rango p10–p90)")
    html = ['<div style="display:flex;flex-wrap:wrap;gap:8px">']
    b0 = max(ini, ahora_h - pd.Timedelta(hours=24)).floor("6h")  # 24 h de pasado + todo el pronóstico
    fin = P.index.max()
    while b0 < fin:
        b1 = b0 + pd.Timedelta(hours=6)
        m = (P.index > b0) & (P.index <= b1)
        q10, q50, q90 = np.percentile(P[m].sum().values, [10, 50, 90])
        rf = None
        if R is not None and b0 in R.index:
            rf = float(R.loc[b0])
        pasado_b, actual = b1 <= ahora_h, b0 <= ahora_h < b1
        color = next(cc for lim, _, cc in NIVELES_6H if q50 < lim)
        obs_txt = ""
        if pasado_b:
            partes = []
            for g, colg in PAL.grupos.items():
                v = [float(lluvia_obs[s["id"]][(lluvia_obs[s["id"]].index > b0) &
                                               (lluvia_obs[s["id"]].index <= b1)].sum())
                     for s in activas if s["grupo"] == g]
                if v:
                    partes.append(f'<span style="color:{colg}">{F.NOMBRE_GRUPO[g]} {min(v):.0f}'
                                  f'{"–%.0f" % max(v) if round(min(v)) != round(max(v)) else ""}</span>')
            obs_txt = "<br>".join(partes)
        fin_h = "24" if b1.hour == 0 else f"{b1:%H}"
        html.append(
            f'<div style="flex:1 1 92px;max-width:130px;border:{"2px solid " + ROJO if actual else "1px solid rgba(128,128,128,.35)"};'
            f'border-radius:10px;padding:8px 6px;text-align:center;opacity:{.55 if pasado_b else 1};'
            f'font-family:sans-serif">'
            f'<div style="font-weight:700">{DIAS[b0.weekday()].capitalize()} {b0.day}</div>'
            f'<div style="font-size:12px;opacity:.7">{b0:%H}–{fin_h} h</div>'
            f'<div style="font-size:26px;font-weight:800;color:{color}">{q50:.0f}</div>'
            f'<div style="font-size:11px;opacity:.7">mm · {q10:.0f}–{q90:.0f}</div>'
            f'<div style="font-size:11px;margin-top:4px;font-weight:700">{obs_txt}</div>'
            + (f'<div style="font-size:11px;color:{PAL.rafaga}">ráfaga {rf:.0f} km/h</div>'
               if rf is not None and not np.isnan(rf) and not pasado_b else "")
            + (f"<div style='font-size:10px;color:white;background:{ROJO};border-radius:4px;margin-top:4px'>"
               "AHORA</div>" if actual else "")
            + "</div>")
        b0 = b1
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.caption("Ráfaga: mediana del máximo del bloque entre los miembros que la informan (GEFS e IFS-ENS). "
               "Intensidad descriptiva (débil < 10, moderada 10–25, fuerte > 25 mm en 6 h): no reemplaza los "
               "avisos de SENAPRED y la DMC. * Observado: VIPNet (DGA/MOP), datos preliminares.")
