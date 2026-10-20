# Cambios

Todos los cambios relevantes de MetGeo Valparaíso. Nació el 20/10/2026 a partir de
[MetGeo Biobío](https://github.com/Heszo/monitor-meteo-biobio) 2.0.0. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones siguen
[versionado semántico](https://semver.org/lang/es/):

- **mayor** (2.0.0): cambios que rompen enlaces compartidos, quitan vistas o cambian de dónde salen los datos;
- **menor** (1.1.0): vistas, gráficos o funciones nuevas;
- **parche** (1.0.1): correcciones y ajustes que no agregan funciones.

Cómo publicar una versión: ver «Versiones» en el [README](README.md#versiones).

## [Sin publicar]

## [1.0.0] - 2026-10-20

Primera versión. Todavía sin la vista «Mapas de superficie» (ver «Pendiente» en el README).

### Agregado
- Región de Valparaíso continental: 69 sitios (66 estaciones VIPNet y los METAR de Torquemada, Rodelillo y Santo
  Domingo) con su comuna, agrupados en costa, valle y cordillera, y control de calidad de los datos de VIPNet
  (rango físico, pluviómetros y sensores de humedad defectuosos fuera).
- Vistas Home, Comparar modelos, Lluvia, Meteograma y Mapa de estaciones, con pronósticos de 7 modelos globales y
  super-ensamble de 143 miembros (Open-Meteo, publicados cada hora por una GitHub Action), estado del tiempo de los
  próximos días, verificación contra lo observado y descarga a pedido de los datos de cada estación en CSV.
- Límites de las 36 comunas continentales en todos los mapas, imagen satelital fija (contexto, región y Gran
  Valparaíso) o mapa de calles, y grilla de latitud y longitud opcional.
- Selector de «Comuna» junto a «Sitio» en todas las vistas (en «Mapa de estaciones», con su propio selector).
- Modo claro y oscuro, descarga de cada gráfico en PNG o PDF y enlaces compartibles.

[Sin publicar]: https://github.com/Heszo/monitor-meteo-valparaiso/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Heszo/monitor-meteo-valparaiso/releases/tag/v1.0.0
