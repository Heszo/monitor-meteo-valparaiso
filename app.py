"""
Punto de entrada: envuelve streamlit_app.py en st.App para mantener la caché
caliente desde el servidor. Al arrancar (y luego cada 5 minutos) se tocan
las cargas con caché de comun.py: las frescas son un acierto instantáneo y
las vencidas se refrescan en segundo plano, así que los visitantes casi
nunca esperan una descarga, aunque nadie haya entrado en horas.

    streamlit run app.py
"""
import logging
from contextlib import asynccontextmanager

import anyio
import streamlit as st

log = logging.getLogger(__name__)
# el calentamiento corre fuera de una sesión: sin esto, cada vuelta deja avisos inofensivos en el log
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)
CADA_S = 5 * 60  # muy por debajo de la ventana en que se sirve lo vencido (ttl 15 min × 3)


@asynccontextmanager
async def lifespan(app):
    # se importa aquí: con el runtime de Streamlit ya iniciado, la caché es la real
    import comun

    def calentar():
        try:
            comun.calienta_caches()
        except Exception:  # noqa: BLE001  (una fuente caída no debe tumbar el servidor)
            log.exception("No se pudo calentar la caché")

    async def periodico():
        while True:
            # la primera vez no bloquea el arranque: el servidor ya atiende mientras descarga
            await anyio.to_thread.run_sync(calentar)
            await anyio.sleep(CADA_S)

    async with anyio.create_task_group() as tareas:
        tareas.start_soon(periodico)
        try:
            yield
        finally:
            tareas.cancel_scope.cancel()


app = st.App("streamlit_app.py", lifespan=lifespan)
