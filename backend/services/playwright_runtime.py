"""Lanzamiento robusto de Chromium para los conectores con Playwright (CNMV, BME, DataComex...).

`pip install playwright` no trae el navegador: si el contenedor se recrea, la cache
/root/.cache/ms-playwright desaparece y `chromium.launch()` falla con
"Executable doesn't exist". Aqui se instala una vez y se reintenta.
"""

import asyncio
import logging
import sys

logger = logging.getLogger(__name__)

LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
_install_lock = asyncio.Lock()


async def install_chromium() -> None:
    async with _install_lock:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("playwright install chromium: timeout 300 s")
        if proc.returncode != 0:
            raise RuntimeError(
                "playwright install chromium fallo: " + out.decode(errors="ignore")[-300:]
                + " (ejecutar 'playwright install --with-deps chromium' en el servidor)")


async def launch_chromium(p, args=None):
    """`p` es el objeto de `async_playwright()`. Devuelve el browser."""
    args = args or LAUNCH_ARGS
    try:
        return await p.chromium.launch(headless=True, args=args)
    except Exception as e:
        if "Executable doesn't exist" not in str(e):
            raise
        logger.warning("Chromium no instalado: ejecutando 'playwright install chromium'...")
        await install_chromium()
        return await p.chromium.launch(headless=True, args=args)
