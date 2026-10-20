"""
Pruebas de humo de la app con st.testing (sin navegador): cada página, cada
variable y varios sitios deben dibujarse sin excepciones. Usan las fuentes
reales (copia publicada, METAR, VIPNet); si alguna está caída la app debe
seguir sin romperse, que es justamente lo que se prueba.

    python -m pytest -q
"""
import pytest
from streamlit.testing.v1 import AppTest

import fuentes as F

PAGINAS = ["presentacion", "comparar", "lluvia", "meteograma", "mapa"]
ENTRADA = "../streamlit_app.py"
TIEMPO = 300  # la primera corrida descarga todo


def abre(pagina="presentacion", **estado):
    at = AppTest.from_file(ENTRADA, default_timeout=TIEMPO)
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    if pagina != "presentacion":
        at.switch_page(f"app_pages/{pagina}.py").run()
    return at


def errores(at):
    return [e.value for e in at.exception]


@pytest.mark.parametrize("pagina", PAGINAS)
def test_cada_pagina(pagina):
    assert errores(abre(pagina)) == []


@pytest.mark.parametrize("sitio", ["torquemada", "aerodromo_rodelillo", "santo_domingo", "valparaiso", "portillo"])
def test_sitios(sitio):
    for pagina in PAGINAS:
        assert errores(abre(pagina, sitio=sitio)) == [], (sitio, pagina)


def test_cada_variable_en_comparar():
    at = abre("comparar", sitio="valparaiso")
    for var in F.VARIABLES:
        at.segmented_control(key="variable").set_value(var).run()
        assert errores(at) == [], var
    at.segmented_control(key="variable").set_value("precipitacion").run()
    at.toggle(key="acumulado").set_value(True).run()
    assert errores(at) == []


def test_ventanas_extremas():
    for pasado, futuro in [(1, 1), (F.DIAS_PUBLICADOS, F.DIAS_PUBLICADOS)]:
        for pagina in PAGINAS:
            assert errores(abre(pagina, pasado=pasado, futuro=futuro)) == [], (pasado, futuro, pagina)


def test_presentacion_enlaza_cada_pagina():
    at = abre()
    enlaces = {e.proto.page for e in at.get("page_link")}  # url_path de cada página
    assert set(PAGINAS[1:]) <= enlaces


def test_estacion_en_lluvia():
    at = abre("lluvia", sitio="los_andes")
    at.selectbox(key="estacion").set_value("los_andes").run()
    assert errores(at) == []


def test_comuna_en_mapa():
    at = abre("mapa")
    for comuna in ["Valparaíso", "Villa Alemana"]:  # Villa Alemana no tiene estaciones: se muestra la más cercana
        at.selectbox(key="comuna").set_value(comuna).run()
        assert errores(at) == [], comuna
        assert len(at.dataframe[0].value) >= 1
    at.segmented_control(key="mapa_base").set_value("calles").run()
    at.toggle(key="grilla_latlon").set_value(True).run()
    assert errores(at) == []


def test_catalogo():
    ids = [s["id"] for s in F.SITIOS]
    assert len(ids) == len(set(ids))
    assert set(F.NODO) == set(ids) and set(F.NODO.values()) <= set(ids)
    for s in F.SITIOS:
        assert s["grupo"] in F.GRUPOS and set(s["vars"]) <= set(F.VARIABLES), s["id"]
    import comun as C
    assert {s["comuna"] for s in F.SITIOS} <= set(C.NOMBRES_COMUNAS)
    assert len(C.NOMBRES_COMUNAS) == 36
    for nombre in C.NOMBRES_COMUNAS:  # cada comuna tiene una estación que la representa
        assert C.sitio_de_comuna(nombre)["id"] in F.SITIO


def test_estado_del_tiempo():
    import pandas as pd

    t = pd.date_range("2026-10-02 01:00", periods=24, freq="h")
    seco = pd.DataFrame({m: [3] * 24 for m in "abcdefg"}, index=t)
    assert F.estado_dia(F.estado_horario(seco)) == "nublado"
    lluvia = seco.copy()
    lluvia.iloc[10:15, :5] = 63  # 5 de 7 modelos, 5 horas
    assert F.estado_dia(F.estado_horario(lluvia)) == "lluvia"
    aislada = seco.copy()
    aislada.iloc[10:15, :2] = 63  # solo 2 de 7 modelos: no alcanza
    assert F.estado_dia(F.estado_horario(aislada)) == "nublado"


def test_descarga_de_estacion():
    at = abre("mapa")
    at.selectbox(key="estacion_descarga").set_value("valparaiso").run()
    at.button(key="prepara_descarga").click().run()
    assert errores(at) == []
    assert any(b.label.startswith("Descargar CSV") for b in at.get("download_button"))


def test_guardar_mapa():
    """La imagen satelital fija va dentro del PDF exportado (Kaleido no conoce la dirección de la app)."""
    import plotly.io as pio

    import comun as C
    at = abre("mapa")
    mapa = next(g for g in at.get("plotly_chart") if '"map"' in g.proto.spec)
    assert C.exporta(pio.from_json(mapa.proto.spec), "pdf", False)[:5] == b"%PDF-"


def test_version_en_changelog():
    """VERSION y la última versión de CHANGELOG.md deben coincidir (la Action de versiones lo exige)."""
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    version = (raiz / "VERSION").read_text().strip()
    publicadas = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", (raiz / "CHANGELOG.md").read_text(), re.M)
    assert publicadas and publicadas[0] == version, (version, publicadas[:1])


@pytest.mark.parametrize("pagina", ["presentacion", "comparar", "lluvia", "meteograma"])
def test_comuna_filtra_sitios(pagina):
    """Al cambiar la comuna, «Sitio» pasa a una estación de esa comuna y solo lista las de ella."""
    at = abre(pagina)
    at.selectbox(key="comuna_sitio").set_value("Los Andes").run()
    assert errores(at) == []
    assert F.SITIO[at.session_state["sitio"]]["comuna"] == "Los Andes"
    assert len(at.selectbox(key="sitio").options) == sum(s["comuna"] == "Los Andes" for s in F.SITIOS)
