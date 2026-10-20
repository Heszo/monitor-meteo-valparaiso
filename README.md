# MetGeo Valparaíso

Monitor meteorológico de la Región de Valparaíso.

**App en línea (cuando se publique): [metgeo-valparaiso.streamlit.app](https://metgeo-valparaiso.streamlit.app/)** ·
por Bruno Herrera · MetGeo Spa ([github.com/Heszo](https://github.com/Heszo))

App Streamlit que junta en un solo lugar lo **observado** en las estaciones públicas de la Región de Valparaíso
continental (de Petorca a San Antonio y de la costa a la cordillera de Los Andes) y lo **pronosticado** por 7
modelos globales y un super-ensamble de 143 miembros, para lluvia, temperatura, humedad, viento, ráfagas,
dirección del viento y presión, además del estado del tiempo de los próximos días. Sirve para ver qué viene y,
sobre todo, para **comparar modelos entre sí y contra la observación**. Es hermana de
[MetGeo Biobío](https://github.com/Heszo/monitor-meteo-biobio) y de MetGeo Araucanía: misma base y mismas vistas,
otra red. Todavía **no tiene la vista «Mapas de superficie»** (ver «Pendiente»).

Se actualiza sola y no necesita claves ni base de datos: las observaciones se descargan al abrir la app
(caché de 15 minutos) y los pronósticos los publica cada hora una GitHub Action (ver más abajo).

## Vistas

| Vista | Qué muestra |
|---|---|
| **Home** | Portada: qué es el proyecto, las condiciones de ahora, el estado del tiempo de los próximos 5 días (ícono, mínima y máxima, lluvia y ráfaga), lo que viene en 24 h y los próximos 3 días, accesos a cada vista, cómo funciona, fuentes y advertencias. |
| **Comparar modelos** | Una variable a la vez en el sitio elegido: los 7 modelos, la banda p10–p90 del super-ensamble y lo observado. Debajo, una tabla con sesgo, MAE, RMSE y correlación de cada modelo en las horas ya ocurridas. La lluvia se dibuja como histograma horario. |
| **Lluvia** | Mapa satelital con el acumulado observado por estación, histograma horario (mediana y p10–p90 del ensamble contra el observado por grupo o estación), acumulado y tarjetas de lluvia esperada cada 6 h con ráfaga. |
| **Meteograma** | Las 6 variables apiladas en un mismo eje de tiempo, para un modelo o la mediana de los modelos elegidos. |
| **Mapa de estaciones** | Última medición (o lluvia acumulada en las últimas N horas) de cada estación, con los límites comunales. Al elegir una comuna el mapa se acerca a ella, la resalta, la tabla muestra sus estaciones (o la más cercana, si no tiene) y aparece el estado del tiempo pronosticado para la comuna. Al final, **descarga a pedido** de los datos de cualquier estación en CSV (cada 30 min en VIPNet, hasta un año; cada reporte en los METAR, hasta 15 días). |

Los modelos se consultan en las coordenadas del sitio elegido arriba: primero la «Comuna» (que filtra las
estaciones) y luego el «Sitio» (se puede escribir para buscar por nombre o por comuna). Todos los mapas dibujan los límites de las 36 comunas continentales
de la región, sobre imagen satelital o sobre un mapa de calles de OpenStreetMap, con una grilla de latitud y
longitud opcional cada 0,5° («Mapa base» y «Grilla lat/lon»; la elección se mantiene al cambiar de página).

**Imagen satelital fija.** Los mapas no piden mosaicos de Esri cada vez que se mueven: usan tres imágenes (contexto, región y Gran Valparaíso)
guardadas en `static/` (la región a ~120 m por píxel y, encima, el Gran Valparaíso, de Concón a Villa Alemana, a ~30 m), que el navegador
baja una vez y guarda en caché. Las genera `python genera_satelite.py` (une los mosaicos de Esri World Imagery,
los oscurece un poco para que se lean los nombres en blanco y anota las esquinas en `static/satelite.json`);
basta correrlo de nuevo si cambia el recuadro o se quiere una imagen más nueva. Al exportar un mapa a PNG o PDF,
la imagen va dentro de la figura.

## La red: 69 sitios

- **66 estaciones VIPNet** (DGA/MOP): las de la región continental que hoy entregan datos. Miden cada 30 min
  lluvia (63), temperatura (52), humedad (37) y viento (20).
- **METAR SCVM** (Torquemada, Concón), **SCRD** (Rodelillo, Valparaíso; no informa todas las horas) y **SCSN**
  (Santo Domingo): las únicas fuentes públicas de ráfagas, dirección del viento y presión.

Se agrupan en **costa** (28, al oeste de 71,25° O), **valle** (28, al este y bajo los 1000 m) y **cordillera**
(13, 1000 m o más). Cada sitio lleva su comuna según los límites de la BCN; 7 comunas no tienen estación
(Algarrobo, Calera, Cartagena, El Quisco, Papudo, Rinconada y Villa Alemana): para ellas se usa la estación más
cercana. Quedan fuera Isla de Pascua y Juan Fernández (2 estaciones VIPNet en Rapa Nui y un METAR insular), que están a
cientos de kilómetros y descuadrarían todos los mapas.

Control de calidad (verificado el 20/10/2026 con 7 y 90 días de datos):
- Se descartan los valores fuera de rango físico (lluvia < 0 o > 40 mm en 30 min, temperatura fuera de
  −25…45 °C, humedad fuera de 1…100 %, viento sobre 200 km/h).
- Sin datos esa semana: Fundo Las Dos Puertas, Las Puertas y los glaciares Juncal Norte y León Negro (EMAM).
- Pluviómetro de Rinconada San Juan (23 mm en 90 días contra 91–200 mm alrededor): se omite su lluvia.
- Humedad que no se comporta como tal (correlación con la temperatura mayor que −0,6 o variación de menos de 5
  puntos en la semana): fija en 100 % o en 96–100 % (Lago Peñuelas, Embalse Lliu-Lliu, Lo Rojas, El Cobre, Laguna de
  Zapallar, Longotoma, Artificio, Las Piedras), casi plana (Colliguay, Quillota, La Viña, Las Colmenas, El Salvador)
  o sin ciclo diario (Nacimiento del Sobrante). Portillo informa solo 5 datos de humedad por semana.
- Para no tapar nombres en el mapa se omiten estaciones a menos de ~2 km de otra que mide lo mismo o más:
  Río Putaendo en Resguardo Los Patos y Río Rocín bajo el Embalse Chacrilla (junto a Resguardo Los Patos), Río
  Alicahue en Colliguay (junto a Alicahue), Río Petorca en Peñón (junto a Hierro Viejo), Río Sobrante en
  Piñadero (junto a El Trapiche) y Estero Riecillo (junto a Riecillos; su humedad marcaba 4–30 %).
- Esta semana fue seca en la costa, así que los pluviómetros que marcan 0 allí (Cerrillos de Leyda, Río Maipo en
  Cabimbao, San Antonio) no se pudieron contrastar con la semana: se mantienen porque en 90 días acumularon
  91–219 mm. Conviene revisarlos con el primer temporal.
- Algunas consultas a VIPNet fallan de forma intermitente cuando se piden muchas a la vez; la app lo informa en
  «Avisos de descarga» y reintenta en el siguiente refresco.

Bajo cada gráfico hay dos botones para **descargarlo en PNG** (2800 px de ancho) **o PDF** (vectorial, con texto
editable), con el logo de MetGeo y los colores del modo en que se estaba viendo. Los dibuja
[kaleido](https://github.com/plotly/Kaleido), que necesita Chrome o Chromium: en Streamlit Community Cloud lo
instala `packages.txt`; en tu computador sirve el Chrome que ya tengas.

La app sigue el **modo claro u oscuro del navegador** (`[theme.light]` y `[theme.dark]` en
`.streamlit/config.toml`). Logos, colores de los gráficos y tarjetas se eligen en `comun.paleta()`; los logos de
trazo claro (`static/*_claro.svg`) son los del modo oscuro. Como cambiar el tema a mano (menú ⋮ → Settings) no
vuelve a correr el script, `comun.vigila_tema()` lo detecta en el navegador y pide un rerun para redibujar los
gráficos con los colores nuevos.

## Fuentes (todas públicas)

| Fuente | Variables | Cobertura |
|---|---|---|
| [VIPNet](https://vipnet.mop.gob.cl) (DGA/MOP) | lluvia (63 estaciones), temperatura (52), humedad (37), viento (20) | toda la región, cada 30 min |
| [METAR](https://aviationweather.gov/data/api/) SCVM (Torquemada), SCRD (Rodelillo) y SCSN (Santo Domingo), NOAA Aviation Weather Center | temperatura, humedad, viento, ráfaga, dirección, presión QNH | aeropuertos, cada hora |
| [Open-Meteo Forecast](https://open-meteo.com/en/docs) | GFS, IFS, ICON, GEM, GSM, UM, ARPEGE (incluido el estado del tiempo, código WMO) | 1–7 días atrás y 1–7 días hacia adelante |
| [Open-Meteo Ensemble](https://open-meteo.com/en/docs/ensemble-api) | GEFS (31) + IFS-ENS (51) + ICON-EPS (40) + GEPS (21) | ídem |
| Esri World Imagery | imagen satelital de los mapas (tres imágenes fijas en `static/`) | — |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) (© colaboradores de OpenStreetMap) | mapa base de calles | — |
| [BCN](https://www.bcn.cl/siit/mapas_vectoriales) (división político-administrativa, vía [chile-geojson](https://github.com/caracena/chile-geojson)) | límites comunales (`static/comunas_valparaiso.geojson`, simplificados a ~400 m) | — |

Advertencias:
- Observaciones preliminares, sin control de calidad oficial (solo el filtro descrito arriba).
- El viento de VIPNet es la media horaria de lecturas instantáneas cada 30 min: es más ruidoso que el del METAR.
- Los METAR informan ráfaga solo cuando es significativa.
- El estado del tiempo de cada día es el que dan la mayoría de los 7 modelos (la precipitación cuenta si dura
  al menos 3 horas); es orientativo.
- El super-ensamble se calcula por celdas de 0,5° (ver abajo): estaciones cercanas comparten la misma banda.
- Los días pasados de Open-Meteo son pronósticos de corto plazo de corridas recientes, no reanálisis;
  la verificación compara un punto de grilla con una estación, así que incluye error de representatividad.
- Es una herramienta de divulgación: no reemplaza los avisos de SENAPRED ni de la DMC.
- Open-Meteo es gratuito para uso no comercial.

## Cómo se actualizan los pronósticos

Open-Meteo gratuito limita las consultas por dirección IP, y la IP de Streamlit Community Cloud es
compartida con muchas otras apps: consultado desde ahí suele responder `429 Too Many Requests`. Por eso:

1. La GitHub Action [`pronosticos.yml`](.github/workflows/pronosticos.yml) corre cada hora (minuto 17),
   ejecuta `actualiza_pronosticos.py` para los 69 sitios (7 días atrás y 7 adelante) y publica 4 archivos
   parquet más `meta.json` en la rama [`datos`](../../tree/datos).
   La rama se reescribe en cada corrida, sin historial, así el repositorio no crece.
2. La app lee esa copia. Si falta o tiene más de 3 horas, consulta Open-Meteo en vivo (con reintentos);
   si tampoco responde, muestra un aviso y sigue mostrando las observaciones.

Cuidar la cuota gratuita de Open-Meteo (600 consultas por minuto, 5000 por hora): cada miembro del ensamble
cuenta como una variable, así que el ensamble de un sitio pesa ~85 consultas. Por eso los sitios se piden en
lotes de 8 coordenadas por consulta, los 7 modelos en cada sitio y el super-ensamble una sola vez por celda de
0,5° (11 "nodos", `F.NODO`), con los lotes del ensamble separados por un minuto. Una corrida completa tarda unos 3 minutos y pesa
~1300 consultas (modelos ~400, ensamble ~900). Conviene no repetirla varias veces en la misma hora
desde la misma IP (por ejemplo, al probar en el computador).

Para forzar una actualización: pestaña *Actions* → *Actualizar pronósticos* → *Run workflow*.
GitHub pausa las Actions programadas de un repositorio público tras 60 días sin actividad; si pasa,
basta reactivarla desde la misma pestaña.

## Estructura

```
app.py                     punto de entrada: st.App que mantiene la caché caliente
streamlit_app.py           navegación (st.navigation), controles de la barra lateral y encabezado
app_pages/                 una página por vista: presentación, comparar, lluvia, meteograma, mapa
comun.py                   cargas con caché, mapas, modo claro/oscuro, descargas PNG/PDF, botones de redes
fuentes.py                 descarga y ordena los datos; catálogo de variables, modelos, estaciones y estados
actualiza_pronosticos.py   baja los pronósticos de todos los sitios (lo corre la GitHub Action)
genera_satelite.py         arma las imágenes satelitales fijas de static/ (contexto, región y Gran Valparaíso;
                           se corre a mano: `python genera_satelite.py [nombres]`)
tests/                     pruebas de humo con st.testing.AppTest
.github/workflows/         Actions: pronósticos cada hora y pruebas en cada push
.streamlit/                tema, archivos estáticos y configuración de la caché
static/                    foto de portada, logos, imágenes satelitales y límites comunales, servidos en app/static/
requirements.txt           dependencias de Python
packages.txt               Chromium para exportar gráficos en Streamlit Community Cloud
VERSION, CHANGELOG.md      versión actual y registro de cambios
```

## Velocidad

- Las cargas usan caché con `ttl` de 15 minutos y `refresh_mode="background"`: cuando una entrada
  vence, el visitante recibe al instante la versión anterior y la nueva se baja por detrás.
- `app.py` envuelve la app en `st.App` y, desde el servidor, toca esas cargas al arrancar y cada 5
  minutos, así que la caché está caliente aunque nadie haya entrado en horas.
- Las claves de caché no dependen de los controles: siempre se pide la ventana máxima (7 días) y se
  recorta en la página.
- Solo se ejecuta la página abierta.

## Enlaces compartibles

El sitio, los días, la variable y la estación elegida quedan en la URL, así que se puede compartir una
vista exacta; por ejemplo
`/comparar?sitio=valparaiso&variable=Presión+al+nivel+del+mar&pasado=5`.

Para agregar o quitar estaciones, o cambiar qué variables mide cada una, editar `SITIOS` en
`fuentes.py` (con su comuna, según `static/comunas_valparaiso.geojson`). El catálogo completo de VIPNet sale de
`POST https://vipnet.mop.gob.cl/v1/vipnet/estaciones` con `{"tipoEstacion": 0}`
(tipos: 0 lluvia, 1 temperatura, 4 humedad, 5 viento).

## Correr en tu computador

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Pruebas: `cd tests && python -m pytest -q` (si la copia publicada todavía no tiene todos los sitios, generar
una con `python actualiza_pronosticos.py salida` y correrlas con `MONITOR_DATOS=../salida`).

Para usar una copia local de los pronósticos (por ejemplo, recién generada con
`python actualiza_pronosticos.py salida`), definir `MONITOR_DATOS=salida` antes de lanzar la app.

## Publicar en Streamlit Community Cloud (gratis)

1. Entrar a [share.streamlit.io](https://share.streamlit.io) con la cuenta de GitHub.
2. *Create app* → elegir este repositorio, rama `main`, archivo `app.py`.
3. Elegir la URL (por ejemplo `metgeo-valparaiso.streamlit.app`) y *Deploy*.

La app se duerme tras unos días sin visitas; la primera visita la despierta.

## Versiones

La versión vigente está en `VERSION` y se muestra al pie de la app; cada cambio queda en
[`CHANGELOG.md`](CHANGELOG.md) (versionado semántico: parche para correcciones, menor para funciones nuevas,
mayor para cambios que rompen enlaces o fuentes). Para publicar una versión:

1. Mientras trabajas, anota los cambios bajo `## [Sin publicar]` en `CHANGELOG.md`.
2. Al cerrar la versión, cambia ese título por `## [X.Y.Z] - AAAA-MM-DD`, deja un `## [Sin publicar]` vacío
   encima, actualiza los enlaces del final y escribe `X.Y.Z` en `VERSION` (una prueba revisa que coincidan).
3. Haz commit, etiqueta y sube:

   ```bash
   git commit -am "Versión X.Y.Z"
   git tag -a vX.Y.Z -m "Versión X.Y.Z"
   git push origin main vX.Y.Z
   ```

La Action [`version.yml`](.github/workflows/version.yml) crea entonces la versión en la pestaña *Releases* de
GitHub con sus notas del registro de cambios.

## Pendiente

- **Mapas de superficie** (viento animado con partículas y rosas de viento): están en
  [MetGeo Biobío](https://github.com/Heszo/monitor-meteo-biobio) (`app_pages/superficie.py`). Esta app ya trae lo
  que necesitan los datos: `F.grilla` (grilla de 0,2° que cubre la región, 11 × 12 puntos), `F.guarda_grilla`,
  `F.lee_grilla`, `F.cubo` y `comun.grilla()`. Para activarla, copiar `superficie.py`, ajustar sus textos y su
  encuadre, agregarla a la navegación en `streamlit_app.py`, volver a llamar `F.guarda_grilla(F.grilla(...))` al
  final de `actualiza_pronosticos.py` y agregar `carga_grilla_publicada` a `comun.calienta_caches`.
- **Publicación**: crear el repositorio `Heszo/monitor-meteo-valparaiso`, correr a mano la Action de pronósticos y
  desplegar en Streamlit Community Cloud (ver «Publicar»). Mientras no exista la rama `datos`, la app consulta
  Open-Meteo en vivo.

## Autoría y licencia

Bruno Herrera · MetGeo Spa · [github.com/Heszo](https://github.com/Heszo). Código bajo licencia [MIT](LICENSE).
Logos de MetGeo Spa: todos los derechos reservados, no incluidos en la licencia MIT.
Imagen de portada y mapas: Esri World Imagery (Esri, Maxar, Earthstar Geographics y la comunidad de usuarios SIG).
