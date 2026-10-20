"""Mapa de estaciones: última medición de cada estación sobre imagen satelital o calles, con los límites
comunales; al elegir una comuna el mapa se acerca a ella, la tabla muestra sus estaciones y aparece el
estado del tiempo pronosticado para la comuna. Al final, la descarga de los datos de una estación."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import comun as C
import fuentes as F
from comun import barra, fmt

c = C.contexto()
pasado, observado = c.pasado, c.observado

medibles = ["temperatura", "humedad", "precipitacion", "viento", "rafaga", "presion"]
TODAS = "Toda la región"
with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    var_m = st.segmented_control("Variable", medibles, default="temperatura", required=True,
                                 format_func=lambda k: F.VARIABLES[k]["nombre"], key="variable_mapa",
                                 bind="query-params")
    comuna = st.selectbox("Comuna", [TODAS, *C.NOMBRES_COMUNAS], key="comuna", bind="query-params", width=260,
                          help="Acerca el mapa a la comuna, muestra solo sus estaciones en la tabla y el estado "
                               "del tiempo pronosticado para ella.")
    C.controles_mapa()
comuna = None if comuna == TODAS else comuna
ventana_pp = 24
if var_m == "precipitacion":
    ventana_pp = st.slider("Lluvia acumulada en las últimas … horas", 1, pasado * 24, min(24, pasado * 24))
filas_m = []
for s in F.SITIOS:
    o = observado(s, var_m)
    if o is None or not len(o):
        continue
    if var_m == "precipitacion":
        valor, hora = o[o.index > o.index.max() - pd.Timedelta(hours=ventana_pp)].sum(), o.index.max()
    else:
        o = o.dropna()
        if not len(o):
            continue
        valor, hora = float(o.iloc[-1]), o.index[-1]
    filas_m.append(dict(id=s["id"], Estación=s["nombre"], Comuna=s["comuna"], Grupo=F.NOMBRE_GRUPO[s["grupo"]],
                        lat=s["lat"], lon=s["lon"], alt=s["alt"], valor=valor, Hora=hora,
                        Fuente="METAR" if s["fuente"] == "metar" else "VIPNet"))
Vm = F.VARIABLES[var_m]
unidad_m = "mm" if var_m == "precipitacion" else Vm["unidad"]
if not filas_m:
    st.info("Ninguna estación informó esta variable en la ventana.", icon=":material/sensors_off:")
else:
    dm = pd.DataFrame(filas_m)
    escala = {"temperatura": "RdYlBu_r", "humedad": "YlGnBu", "precipitacion": "Blues",
              "viento": "Viridis", "rafaga": "Viridis", "presion": "Plasma"}[var_m]
    texto = [f"{e} {fmt(v, Vm['decimales'])}" for e, v in zip(dm["Estación"], dm.valor)]
    fmap = go.Figure(go.Scattermap(
        lat=dm.lat, lon=dm.lon, mode="markers+text",
        marker=dict(size=14, color=dm.valor, colorscale=escala, showscale=True,
                    colorbar=dict(title=unidad_m, thickness=12)),
        text=texto, customdata=dm[["Estación", "Comuna", "alt"]], textposition="middle right",
        textfont=C.texto_mapa(13 if comuna else 12),
        hovertemplate="<b>%{customdata[0]}</b> (%{customdata[1]}, %{customdata[2]} m)<br>"
                      + "%{marker.color:." + str(Vm["decimales"]) + "f} " + unidad_m + "<extra></extra>"))
    vista = C.vista_region(820, 620)
    if comuna:
        vista = C.vista_comuna(comuna) | dict(capas_extra=C.resalta_comuna(comuna))
    C.prepara_mapa(fmap, **vista)
    fmap.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=620, showlegend=False)
    col_map, col_tab = st.columns([3, 2])
    with col_map:
        C.grafico(fmap, f"mapa_{var_m}" + (f"_{comuna}" if comuna else ""), config=barra("resetViewMap"))
    tabla = dm[dm.Comuna == comuna] if comuna else dm
    if comuna and tabla.empty:
        # la estación más cercana al centro de la comuna, para no dejar al usuario sin referencia
        cen = C.vista_comuna(comuna)["center"]
        cerca = dm.iloc[((dm.lat - cen["lat"]) ** 2 + (dm.lon - cen["lon"]) ** 2).argmin()]
        col_tab.info(f"{comuna} no tiene estaciones que midan esta variable. La más cercana es "
                     f"**{cerca['Estación']}** ({cerca['Comuna']}).", icon=":material/location_off:")
        tabla = dm.loc[[cerca.name]]
    col_tab.dataframe(tabla[["Estación", "Comuna", "Grupo", "valor", "Hora", "Fuente"]]
                      .rename(columns={"valor": f"{Vm['nombre']} ({unidad_m})"}).sort_values(["Grupo", "Comuna"]),
                      hide_index=True, width="stretch", height=480 if not comuna else "auto",
                      column_config={"Hora": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                                     f"{Vm['nombre']} ({unidad_m})": st.column_config.NumberColumn(
                                         format=f"%.{Vm['decimales']}f")})
    titulo = (f"acumulado de las últimas {ventana_pp} h" if var_m == "precipitacion" else "última medición")
    col_tab.caption(f"{Vm['nombre']}: {titulo}. Donde las estaciones están muy juntas, acerca el mapa (o elige "
                    f"una comuna) para leer todos los nombres. Líneas: límites comunales (BCN). Mapa base: "
                    f"{C.credito_mapa()}.")

# --- estado del tiempo de la comuna
if comuna:
    rep = C.sitio_de_comuna(comuna)
    pron_c, _, _ = C.pronostico(rep)
    filas = C.estado_por_dia(pron_c, c.ahora)
    st.markdown(f"**Estado del tiempo pronosticado en {comuna}** (en {rep['nombre']}"
                + ("" if rep["comuna"] == comuna else f", la estación más cercana, en {rep['comuna']}") + ")")
    if filas:
        C.tarjetas_estado(filas)
        st.caption("Estado: el que dan la mayoría de los 7 modelos (la precipitación cuenta si dura al menos "
                   f"{F.HORAS_PARA_PRECIPITACION} horas). Temperaturas mínima y máxima: mediana de los modelos. "
                   "Lluvia: mediana del super-ensamble (rango p10–p90).")
    else:
        st.caption("El pronóstico todavía no trae el estado del tiempo (se agrega en la próxima actualización).")

# --- descarga de datos
st.space("small")
st.subheader("Descargar los datos de una estación", icon=":material/download:", anchor=False)
propias = [s for s in F.SITIOS if not comuna or s["comuna"] == comuna] or F.SITIOS
with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    elegida = st.selectbox("Estación", [s["id"] for s in propias], key="estacion_descarga",
                           format_func=lambda i: f"{F.etiqueta(F.SITIO[i])} · {F.SITIO[i]['comuna']}", width=380)
    s_d = F.SITIO[elegida]
    maximo = (F.HORAS_MAX_METAR if s_d["fuente"] == "metar" else F.HORAS_MAX_VIPNET) // 24
    dias_d = st.select_slider("Días hacia atrás", [d for d in (1, 3, 7, 15, 30, 90, 180, 365) if d <= maximo],
                              value=7, key=f"dias_descarga_{s_d['fuente']}", width=380)  # METAR llega a 15
horas_d = dias_d * 24
# la consulta se hace al pedirla (botón), no al abrir la página
if st.button("Preparar archivo", icon=":material/cloud_download:", key="prepara_descarga"):
    try:
        st.session_state["_descarga"] = (elegida, dias_d, C.carga_estacion(elegida, horas_d))
    except Exception as ex:  # noqa: BLE001
        st.session_state.pop("_descarga", None)
        st.error(f"La fuente no respondió; intenta de nuevo en unos minutos. Detalle: `{str(ex)[:160]}`",
                 icon=":material/cloud_off:")
lista = st.session_state.get("_descarga")
if lista and lista[:2] == (elegida, dias_d):
    _, _, df_d = lista
    if df_d.empty:
        st.info("La estación no entregó datos en ese período.", icon=":material/sensors_off:")
    else:
        nombres = {v: f"{F.VARIABLES[v]['nombre']} ({F.VARIABLES[v]['unidad'].replace('/h', '')})"
                   for v in F.VARIABLES}
        nombres |= {F.VARIABLES[v]["metar"]: n for v, n in nombres.items() if F.VARIABLES[v]["metar"]}
        if s_d["fuente"] == "vipnet":  # VIPNet: lluvia caída en cada intervalo de 30 min
            nombres["precipitacion"] = "Precipitación (mm en 30 min)"
        df_d = df_d.rename(columns=nombres | {"hora": "Hora (Chile)", "reporte": "Reporte", "texto": "METAR"})
        archivo = f"metgeo_{elegida}_{dias_d}d_{F.ahora_local():%Y%m%d_%H%M}.csv"
        st.download_button(f"Descargar CSV ({len(df_d):,} filas)".replace(",", "."),
                           df_d.to_csv(index=False).encode("utf-8-sig"), file_name=archivo, mime="text/csv",
                           icon=":material/download:", type="primary", key="baja_csv")
        st.dataframe(df_d.tail(200), hide_index=True, width="stretch", height=260,
                     column_config={"Hora (Chile)": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")})
st.caption("Datos tal como los publica la fuente, sin promediar: cada 30 minutos en VIPNet (DGA/MOP), con los "
           "valores fuera de rango físico descartados; cada reporte en los METAR (NOAA AWC, hasta "
           f"{F.HORAS_MAX_METAR // 24} días). Preliminares, sin control de calidad oficial. Una estación y un "
           "año pesan ~3 MB y tardan unos segundos.")
