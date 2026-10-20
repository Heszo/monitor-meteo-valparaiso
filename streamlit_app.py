"""
MetGeo Valparaíso: monitor meteorológico de la Región de Valparaíso. Lluvia,
temperatura, humedad, viento y presión, observados (VIPNet DGA/MOP y METAR de
Torquemada, Rodelillo y Santo Domingo) y pronosticados por 7 modelos
globales y un super-ensamble de 143 miembros. Página principal: marca, navegación y encabezado; cada
vista vive en app_pages/ y los controles en comun.controles().

Se lanza con `streamlit run app.py` (app.py envuelve este script en st.App
para mantener la caché caliente); `streamlit run streamlit_app.py` también
funciona, sin ese precalentamiento.
"""
import streamlit as st

import comun as C

st.set_page_config(page_title="MetGeo Valparaíso · monitor meteorológico", page_icon=str(C.LOGO_SOLO),
                   layout="wide")
C.logo()
C.vigila_tema()
C.estilo_mapas()

INICIO = st.Page("app_pages/presentacion.py", title="Home", icon=":material/home:", default=True)
MAPA = st.Page("app_pages/mapa.py", title="Mapa de estaciones", icon=":material/map:")
pagina = st.navigation([
    INICIO,
    st.Page("app_pages/comparar.py", title="Comparar modelos", icon=":material/stacked_line_chart:"),
    st.Page("app_pages/lluvia.py", title="Lluvia", icon=":material/water_drop:"),
    st.Page("app_pages/meteograma.py", title="Meteograma", icon=":material/monitoring:"),
    MAPA,
], position="top")

# La portada pone sus controles debajo de la presentación; el resto, arriba de todo.
if pagina.title != INICIO.title:
    st.title(pagina.title, icon=pagina.icon, anchor=False)
    c = C.controles(por_comuna=pagina.title != MAPA.title)  # el mapa tiene su propio selector de comuna
    C.metricas_ahora(c)
    st.space("small")

pagina.run()

if pagina.title != INICIO.title:  # la portada ya trae su propia firma
    st.space("large")
    with st.container(horizontal=True, horizontal_alignment="center", gap="small"):
        st.link_button("metgeo.cl", C.METGEO, icon=":material/public:")
        st.link_button("Suscríbete al newsletter", C.NEWSLETTER, icon=":material/mail:", type="primary")
    st.caption(f"MetGeo Valparaíso · Bruno Herrera · [Instagram]({C.INSTAGRAM}) · [LinkedIn]({C.LINKEDIN}) · "
               f"v{C.VERSION}", text_alignment="center")
