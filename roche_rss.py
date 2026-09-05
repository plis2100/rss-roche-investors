import re
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from playwright.sync_api import sync_playwright


SOURCE_URL = "https://www.roche.com/investors/updates"
BASE_URL = "https://www.roche.com"
OUTPUT_FILE = Path("roche-investors.xml")
MAX_ITEMS = 60


def limpiar_texto(texto):
    return " ".join((texto or "").split())


def fecha_desde_enlace(enlace):
    coincidencia = re.search(
        r"inv-update-(\d{4})-(\d{2})-(\d{2})",
        enlace
    )

    if not coincidencia:
        return None

    año, mes, dia = map(int, coincidencia.groups())

    try:
        return datetime(
            año,
            mes,
            dia,
            8,
            0,
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def leer_elementos_anteriores():
    anteriores = {}

    if not OUTPUT_FILE.exists():
        return anteriores

    try:
        raiz = ET.parse(OUTPUT_FILE).getroot()

        for item in raiz.findall("./channel/item"):
            enlace = limpiar_texto(item.findtext("link"))

            if enlace:
                anteriores[enlace] = {
                    "title": limpiar_texto(item.findtext("title")),
                    "link": enlace,
                    "description": limpiar_texto(
                        item.findtext("description")
                    ),
                    "pubDate": limpiar_texto(item.findtext("pubDate")),
                }

    except Exception as error:
        print(f"No se pudo leer la RSS anterior: {error}")

    return anteriores


def obtener_noticias():
    noticias = {}
    error_final = None

    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=True)

        pagina = navegador.new_page(
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            ),
        )

        try:
            pagina.goto(
                SOURCE_URL,
                wait_until="domcontentloaded",
                timeout=90000
            )

            # Roche carga la lista mediante JavaScript.
            pagina.wait_for_timeout(12000)

            enlaces = pagina.locator(
                'a[href*="/investors/updates/inv-update-"]'
            )

            cantidad = enlaces.count()

            for indice in range(cantidad):
                elemento = enlaces.nth(indice)

                try:
                    href = elemento.get_attribute("href")
                    titulo = limpiar_texto(elemento.inner_text())

                    if not href or not titulo:
                        continue

                    enlace = urljoin(BASE_URL, href)
                    enlace = enlace.split("#")[0].split("?")[0]

                    if "/investors/updates/inv-update-" not in enlace:
                        continue

                    if len(titulo) < 12:
                        continue

                    fecha = fecha_desde_enlace(enlace)

                    noticias[enlace] = {
                        "title": titulo,
                        "link": enlace,
                        "description": (
                            "Actualización para inversores publicada "
                            "por Roche."
                        ),
                        "date": fecha,
                    }

                except Exception as error:
                    print(f"Enlace omitido: {error}")

        except Exception as error:
            error_final = error

        finally:
            navegador.close()

    if not noticias:
        raise RuntimeError(
            "No se encontraron actualizaciones de Roche. "
            f"La RSS anterior no será eliminada. Error: {error_final}"
        )

    return list(noticias.values())


def crear_rss(noticias):
    anteriores = leer_elementos_anteriores()
    combinadas = {}

    for noticia in noticias:
        fecha = noticia["date"]

        combinadas[noticia["link"]] = {
            "title": noticia["title"],
            "link": noticia["link"],
            "description": noticia["description"],
            "pubDate": (
                format_datetime(fecha)
                if fecha
                else format_datetime(datetime.now(timezone.utc))
            ),
        }

    # Conserva publicaciones anteriores aunque desaparezcan de la portada.
    for enlace, noticia in anteriores.items():
        if enlace not in combinadas:
            combinadas[enlace] = noticia

    def clave_fecha(elemento):
        fecha_texto = elemento.get("pubDate", "")

        try:
            return datetime.strptime(
                fecha_texto,
                "%a, %d %b %Y %H:%M:%S %z"
            )
        except ValueError:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)

    ordenadas = sorted(
        combinadas.values(),
        key=clave_fecha,
        reverse=True
    )[:MAX_ITEMS]

    ahora = format_datetime(datetime.now(timezone.utc))

    partes = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        '<rss version="2.0" '
        'xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        "    <title>Roche - Investor Updates</title>",
        f"    <link>{escape(SOURCE_URL)}</link>",
        (
            "    <description>Actualizaciones y noticias para "
            "inversores de Roche</description>"
        ),
        "    <language>en</language>",
        f"    <lastBuildDate>{escape(ahora)}</lastBuildDate>",
        (
            '    <atom:link href="roche-investors.xml" '
            'rel="self" type="application/rss+xml"/>'
        ),
    ]

    for noticia in ordenadas:
        partes.extend([
            "    <item>",
            f"      <title>{escape(noticia['title'])}</title>",
            f"      <link>{escape(noticia['link'])}</link>",
            (
                "      <guid isPermaLink=\"true\">"
                f"{escape(noticia['link'])}</guid>"
            ),
            (
                "      <description>"
                f"{escape(noticia['description'])}</description>"
            ),
            f"      <pubDate>{escape(noticia['pubDate'])}</pubDate>",
            "    </item>",
        ])

    partes.extend([
        "  </channel>",
        "</rss>",
        "",
    ])

    OUTPUT_FILE.write_text(
        "\n".join(partes),
        encoding="utf-8"
    )

    print(
        f"RSS creada correctamente con {len(ordenadas)} publicaciones."
    )


if __name__ == "__main__":
    noticias_roche = obtener_noticias()
    crear_rss(noticias_roche)
