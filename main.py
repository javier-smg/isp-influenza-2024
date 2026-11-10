import csv
import re
import ssl
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import pypdf

URL_INFORMES = (
    "https://www.ispch.gob.cl/biomedico/vigilancia-de-laboratorio/"
    "ambitos-de-vigilancia/vigilancia-virus-respiratorios/"
    "informes-virus-respiratorios/"
)


class EnlacesInformeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.enlaces_semanales = []
        self.enlaces_pdf = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()
        if tag == "a":
            href = attrs.get("href", "")
            if re.search(r"/documento/semana-\d{1,2}-\d{4}/?", href, re.IGNORECASE):
                self.enlaces_semanales.append(href)
        for atributo in ("href", "src", "data"):
            enlace = attrs.get(atributo, "")
            if urlsplit(enlace).path.lower().endswith(".pdf"):
                self.enlaces_pdf.append(enlace)


def abrir_url(url: str, headers: dict[str, str] | None = None) -> bytes:
    solicitud = Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(solicitud, timeout=30) as respuesta:
            return respuesta.read()
    except Exception as error:
        if not isinstance(error, (ssl.SSLError, OSError)) and "CERTIFICATE_VERIFY_FAILED" not in str(error):
            raise
        context = ssl._create_unverified_context()
        with urlopen(solicitud, context=context, timeout=30) as respuesta:
            return respuesta.read()


def descargar_texto(url: str) -> str:
    return abrir_url(url).decode("utf-8", errors="replace")


def limpiar_entero(texto_num: str) -> int:
    limpio = re.sub(r'[^\d]', '', texto_num)
    return int(limpio) if limpio else 0

def extraer_santiago_p2(p2_text: str, nombre_virus: str) -> int:
    """Extrae el valor de 'Santiago (X)' para un virus desde el texto de la Página 2."""
    texto_plano = re.sub(r'\s+', ' ', p2_text)
    m_bloque = re.search(rf'{nombre_virus}\s+en\s+([^\.]+)\.', texto_plano, re.IGNORECASE)
    if not m_bloque:
        return 0
    m_stgo = re.search(r'Santiago\s*\(\s*([\d\.]+)\s*\)', m_bloque.group(1), re.IGNORECASE)
    return limpiar_entero(m_stgo.group(1)) if m_stgo else 0

def extraer_tabla2_rm(reader: pypdf.PdfReader):
    """Suma las 10 filas de la R.M. y Santiago en la Tabla Nº2 usando alineación horizontal."""
    for page in reader.pages[2:7]:
        txt_layout = page.extract_text(extraction_mode="layout")
        if not re.search(r'Tabla\s*N[º°o]?\s*2', txt_layout, re.IGNORECASE):
            continue
        
        lines = txt_layout.splitlines()
        header_line = next((l for l in lines if "Hospital Centinela" in l and "Inf A" in l), None)
        if not header_line:
            continue
            
        col_names = [
            "Total de casos", "casos positivos", "VRS", "Ad", "Para",
            "Inf A", "Inf B", "Meta", "SarsCov-2", "Rino", "Otros"
        ]
        col_centers = {
            c: (m.start() + m.end()) / 2
            for c in col_names
            if (m := re.search(re.escape(c), header_line, re.IGNORECASE))
        }
        
        # Filas correspondientes a la Región Metropolitana en Tabla 2
        patron_rm = re.compile(r'^\s*(R\.M\.|Santiago,|Otros\s+R\.M)', re.IGNORECASE)
        start_idx = max(0, header_line.find("Total de casos") - 5)
        
        muestras, positivos, inf_a, inf_b = 0, 0, 0, 0
        for line in lines:
            if patron_rm.match(line):
                for m_num in re.finditer(r'\d+', line[start_idx:]):
                    pos = start_idx + (m_num.start() + m_num.end()) / 2
                    val = int(m_num.group(0))
                    col = min(col_centers.keys(), key=lambda c: abs(col_centers[c] - pos))
                    if col == "Total de casos":
                        muestras += val
                    elif col == "casos positivos":
                        positivos += val
                    elif col == "Inf A":
                        inf_a += val
                    elif col == "Inf B":
                        inf_b += val
        return muestras, positivos, inf_a, inf_b
    return None, None, None, None

def extraer_tabla5_privados_rm(reader: pypdf.PdfReader):
    """Suma los 3 subtotales (hospitalizados, ambulatorios, urgencia) de centros privados de Santiago (Tabla Nº5)."""
    for page in reader.pages[5:]:
        txt = page.extract_text()
        if not re.search(r'Tabla\s*N[º°o]?\s*5', txt, re.IGNORECASE):
            continue
        muestras, positivos, inf_a, inf_b = 0, 0, 0, 0
        for m_tot in re.finditer(r'Total\s+pacientes\s+\w+\s+((?:\d+\s+)+)', txt, re.IGNORECASE):
            nums = [int(x) for x in m_tot.group(1).split()]
            # Orden fijo Tabla 5: [0: Total casos, 1: Positivos, 2: VRS, 3: Ad, 4: Para, 5: Inf A, 6: Inf B, ...]
            if len(nums) >= 7:
                muestras += nums[0]
                positivos += nums[1]
                inf_a += nums[5]
                inf_b += nums[6]
        return muestras, positivos, inf_a, inf_b
    return 0, 0, 0, 0

def procesar_pdf_rm(pdf_data: bytes, nombre_archivo: str) -> dict:
    reader = pypdf.PdfReader(BytesIO(pdf_data))
    p1_text = reader.pages[0].extract_text(extraction_mode="layout")
    p2_text = reader.pages[1].extract_text() if len(reader.pages) > 1 else ""

    # Semana Epidemiológica (SE) y Año
    se, anio = None, None
    m_se = re.search(r'SE\.?\s*N[º°o]?\s*(\d+)\s+del\s+(\d{4})', p1_text, re.IGNORECASE)
    if m_se:
        se, anio = int(m_se.group(1)), int(m_se.group(2))
    else:
        m_fname = re.search(r'SE\s*0*(\d+).*?(20\d{2})', nombre_archivo, re.IGNORECASE)
        if m_fname:
            se, anio = int(m_fname.group(1)), int(m_fname.group(2))

    # 1. Red Centinela Pública RM (Página 2 y Tabla 2)
    inf_a_p2 = extraer_santiago_p2(p2_text, "Influenza A")
    inf_b_p2 = extraer_santiago_p2(p2_text, "Influenza B")
    muestras_t2, pos_t2, inf_a_t2, inf_b_t2 = extraer_tabla2_rm(reader)

    rm_pub_inf_a = inf_a_t2 if inf_a_t2 is not None else inf_a_p2
    rm_pub_inf_b = inf_b_t2 if inf_b_t2 is not None else inf_b_p2
    validacion_ok = (inf_a_t2 == inf_a_p2 and inf_b_t2 == inf_b_p2) if inf_a_t2 is not None else True

    # 2. Centros Privados RM (Tabla 5: Bupa Lab, Clínica Las Condes, Clínica Santa María)
    muestras_priv, pos_priv, inf_a_priv, inf_b_priv = extraer_tabla5_privados_rm(reader)

    return {
        "anio": anio,
        "semana_epidemiologica": se,
        # Red Centinela Pública RM (Tabla 2 / Pág. 2)
        "rm_publico_muestras": muestras_t2,
        "rm_publico_positivos": pos_t2,
        "rm_publico_inf_a": rm_pub_inf_a,
        "rm_publico_inf_b": rm_pub_inf_b,
        "rm_publico_inf_total": rm_pub_inf_a + rm_pub_inf_b,
        # Centros Privados RM (Tabla 5)
        "rm_privado_muestras": muestras_priv,
        "rm_privado_positivos": pos_priv,
        "rm_privado_inf_a": inf_a_priv,
        "rm_privado_inf_b": inf_b_priv,
        "rm_privado_inf_total": inf_a_priv + inf_b_priv,
        # Consolidado Total RM (Público + Privado)
        "rm_total_muestras": (muestras_t2 or 0) + (muestras_priv or 0),
        "rm_total_positivos": (pos_t2 or 0) + (pos_priv or 0),
        "rm_total_inf_a": rm_pub_inf_a + inf_a_priv,
        "rm_total_inf_b": rm_pub_inf_b + inf_b_priv,
        "rm_total_influenza": (rm_pub_inf_a + rm_pub_inf_b) + (inf_a_priv + inf_b_priv),
        "validacion_cruzada_ok": validacion_ok,
        "archivo": nombre_archivo,
    }


def obtener_enlaces_semanales(anio: int, pagina_local: Path | None = None) -> list[tuple[int, str]]:
    url_indice = f"{URL_INFORMES}?y={anio}"
    html = None
    if pagina_local is not None:
        html = pagina_local.read_text(encoding="utf-8", errors="replace")
    else:
        for candidata in Path(__file__).parent.glob("*.htm*"):
            texto = candidata.read_text(encoding="utf-8", errors="replace")
            parser = EnlacesInformeParser()
            parser.feed(texto)
            if parser.enlaces_semanales:
                html = texto
                break

    if html is None:
        try:
            html = descargar_texto(url_indice)
        except Exception as error:
            raise RuntimeError(
                f"No se pudo consultar la página de informes: {url_indice}. "
                "Guarda la página como .htm en la carpeta del script o permite "
                "la conexión a internet."
            ) from error

    parser = EnlacesInformeParser()
    parser.feed(html)
    semanas = {}
    for enlace in parser.enlaces_semanales:
        coincidencia = re.search(
            r"/documento/semana-(\d{1,2})-(\d{4})/?",
            enlace,
            re.IGNORECASE,
        )
        if coincidencia and int(coincidencia.group(2)) == anio:
            semana = int(coincidencia.group(1))
            semanas[semana] = urljoin(url_indice, enlace)

    if not semanas:
        raise RuntimeError(f"No se encontraron enlaces semanales para {anio} en la página de informes.")
    if anio == 2024 and sorted(semanas) != list(range(1, 53)):
        faltantes = sorted(set(range(1, 53)) - set(semanas))
        raise RuntimeError(f"La página no contiene las 52 semanas de 2024; faltan: {faltantes}.")
    return sorted(semanas.items())


def obtener_enlace_pdf(url_informe: str) -> str:
    try:
        html = descargar_texto(url_informe)
    except Exception as error:
        raise RuntimeError(f"No se pudo consultar la página del informe: {url_informe}") from error

    parser = EnlacesInformeParser()
    parser.feed(html)
    enlaces = []
    for enlace in parser.enlaces_pdf:
        url_pdf = urljoin(url_informe, enlace)
        if "codigo-etica-isp" in urlsplit(url_pdf).path.lower():
            continue
        enlaces.append(url_pdf)
    enlaces = list(dict.fromkeys(enlaces))
    if not enlaces:
        raise RuntimeError(f"No se encontró un enlace PDF válido en la página: {url_informe}")
    return enlaces[0]


def procesar_informes_isp(
    anio: int = 2024,
    archivo_salida: str = "influenza_rm_isp.csv",
    pagina_local: str | None = None,
):
    registros_por_semana = {}
    indice = Path(pagina_local) if pagina_local else None
    enlaces_semanales = obtener_enlaces_semanales(anio, indice)

    for semana_esperada, url_informe in enlaces_semanales:
        try:
            url_pdf = obtener_enlace_pdf(url_informe)
            pdf_data = abrir_url(url_pdf)
            registro = procesar_pdf_rm(pdf_data, Path(urlsplit(url_pdf).path).name)
        except Exception as error:
            print(
                f"Advertencia: se omite la semana {semana_esperada} ({url_informe}) "
                f"porque no se pudo descargar o procesar el informe: {error}"
            )
            continue

        semana = registro["semana_epidemiologica"]
        if registro["anio"] != anio or semana != semana_esperada:
            raise ValueError(
                f"El PDF de la semana {semana_esperada} no coincide con su contenido "
                f"(año={registro['anio']}, semana={semana})."
            )
        if semana in registros_por_semana:
            raise ValueError(f"Hay más de un informe publicado para la semana {semana} de {anio}.")

        registros_por_semana[semana] = {
            "semana_epidemiologica": semana,
            "total_influenza": registro["rm_total_influenza"],
        }

    if not registros_por_semana:
        raise RuntimeError(f"No se pudo descargar ni procesar ningún informe del año {anio}.")

    registros = sorted(
        registros_por_semana.values(),
        key=lambda registro: registro["semana_epidemiologica"],
    )
    with open(archivo_salida, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(
            archivo,
            fieldnames=["semana_epidemiologica", "total_influenza"],
        )
        escritor.writeheader()
        escritor.writerows(registros)
    print(f"Listo: {len(registros)} semanas procesadas -> {archivo_salida}")

if __name__ == "__main__":
    procesar_informes_isp(2024, "influenza_rm_isp.csv")