import argparse
import csv
from pathlib import Path


CAMPO_SEMANA = "semana_epidemiologica"
CAMPO_TOTAL = "total_influenza"


def leer_datos(archivo_entrada: Path) -> dict[int, float]:
    with archivo_entrada.open(newline="", encoding="utf-8") as archivo:
        lector = csv.DictReader(archivo)
        campos_requeridos = {CAMPO_SEMANA, CAMPO_TOTAL}
        if not campos_requeridos.issubset(lector.fieldnames or []):
            raise ValueError(
                f"El CSV debe incluir las columnas: {', '.join(sorted(campos_requeridos))}."
            )

        datos = {}
        for numero_fila, fila in enumerate(lector, start=2):
            try:
                semana = int(fila[CAMPO_SEMANA])
                total = float(fila[CAMPO_TOTAL])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Datos inválidos en la fila {numero_fila}.") from error

            if semana < 1:
                raise ValueError(f"La semana debe ser positiva (fila {numero_fila}).")
            if total < 0:
                raise ValueError(f"El total no puede ser negativo (fila {numero_fila}).")
            if semana in datos:
                raise ValueError(f"La semana {semana} está duplicada en el CSV.")
            datos[semana] = total

    if not datos:
        raise ValueError("El CSV no contiene semanas para procesar.")
    return datos


def completar_semanas(datos: dict[int, float]) -> tuple[dict[int, float], set[int]]:
    semanas = sorted(datos)
    completos = dict(datos)
    interpoladas = set()

    for semana_izquierda, semana_derecha in zip(semanas, semanas[1:]):
        valor_izquierdo = datos[semana_izquierda]
        valor_derecho = datos[semana_derecha]
        distancia = semana_derecha - semana_izquierda

        for semana in range(semana_izquierda + 1, semana_derecha):
            proporcion = (semana - semana_izquierda) / distancia
            completos[semana] = valor_izquierdo + (
                valor_derecho - valor_izquierdo
            ) * proporcion
            interpoladas.add(semana)

    return completos, interpoladas


def guardar_csv(archivo_salida: Path, datos: dict[int, float]) -> None:
    with archivo_salida.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(
            archivo,
            fieldnames=[CAMPO_SEMANA, CAMPO_TOTAL],
        )
        escritor.writeheader()
        for semana, total in sorted(datos.items()):
            escritor.writerow(
                {CAMPO_SEMANA: semana, CAMPO_TOTAL: f"{total:g}"}
            )


def guardar_grafica(
    archivo_salida: Path,
    datos: dict[int, float],
) -> None:
    ancho, alto = 1100, 620
    margen_izquierdo, margen_derecho = 80, 30
    margen_superior, margen_inferior = 65, 75
    ancho_grafica = ancho - margen_izquierdo - margen_derecho
    alto_grafica = alto - margen_superior - margen_inferior
    semanas = sorted(datos)
    valores = [datos[semana] for semana in semanas]
    maximo = max(valores)
    escala_y = maximo * 1.1 if maximo > 0 else 1

    def x(semana: int) -> float:
        return margen_izquierdo + (
            (semana - semanas[0]) / max(1, semanas[-1] - semanas[0])
        ) * ancho_grafica

    def y(valor: float) -> float:
        return margen_superior + alto_grafica * (1 - valor / escala_y)

    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" '
        f'viewBox="0 0 {ancho} {alto}">',
        "<style>text{font-family:Arial,sans-serif;fill:#263238}"
        ".grid{stroke:#d9e0e5;stroke-width:1}"
        ".axis{stroke:#455a64;stroke-width:1.5}"
        ".serie{fill:none;stroke:#1565c0;stroke-width:3}"
        ".dato{fill:#1565c0}</style>",
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="550" y="32" text-anchor="middle" font-size="21">'
        "Casos de influenza por semana epidemiológica</text>",
    ]

    divisiones_y = 5
    for division in range(divisiones_y + 1):
        valor = escala_y * division / divisiones_y
        coordenada_y = y(valor)
        partes.extend(
            [
                f'<line class="grid" x1="{margen_izquierdo}" y1="{coordenada_y:.1f}" '
                f'x2="{ancho - margen_derecho}" y2="{coordenada_y:.1f}"/>',
                f'<text x="{margen_izquierdo - 12}" y="{coordenada_y + 5:.1f}" '
                f'text-anchor="end" font-size="12">{valor:g}</text>',
            ]
        )

    partes.extend(
        [
            f'<line class="axis" x1="{margen_izquierdo}" y1="{margen_superior}" '
            f'x2="{margen_izquierdo}" y2="{alto - margen_inferior}"/>',
            f'<line class="axis" x1="{margen_izquierdo}" y1="{alto - margen_inferior}" '
            f'x2="{ancho - margen_derecho}" y2="{alto - margen_inferior}"/>',
            f'<text x="22" y="{alto / 2}" transform="rotate(-90 22 {alto / 2})" '
            'text-anchor="middle" font-size="14">Casos</text>',
            f'<text x="{ancho / 2}" y="{alto - 20}" text-anchor="middle" '
            'font-size="14">Semana epidemiológica</text>',
        ]
    )

    semanas_etiquetadas = set(range(semanas[0], semanas[-1] + 1, 4))
    semanas_etiquetadas.update((semanas[0], semanas[-1]))
    for semana in sorted(semanas_etiquetadas):
        coordenada_x = x(semana)
        partes.extend(
            [
                f'<line class="grid" x1="{coordenada_x:.1f}" y1="{margen_superior}" '
                f'x2="{coordenada_x:.1f}" y2="{alto - margen_inferior}"/>',
                f'<text x="{coordenada_x:.1f}" y="{alto - margen_inferior + 22}" '
                f'text-anchor="middle" font-size="11">{semana}</text>',
            ]
        )

    puntos = " ".join(
        f"{x(semana):.1f},{y(datos[semana]):.1f}" for semana in semanas
    )
    partes.append(f'<polyline class="serie" points="{puntos}"/>')
    for semana in semanas:
        partes.append(
            f'<circle class="dato" cx="{x(semana):.1f}" '
            f'cy="{y(datos[semana]):.1f}" r="4"/>'
        )

    partes.append("</svg>")
    archivo_salida.write_text("\n".join(partes), encoding="utf-8")


def procesar_csv(
    archivo_entrada: Path,
    archivo_csv_salida: Path,
    archivo_grafica: Path,
) -> int:
    datos = leer_datos(archivo_entrada)
    completos, interpoladas = completar_semanas(datos)
    guardar_csv(archivo_csv_salida, completos)
    guardar_grafica(archivo_grafica, completos)
    return len(interpoladas)


def main() -> None:
    carpeta = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Completa semanas faltantes del CSV y genera una gráfica SVG."
    )
    parser.add_argument(
        "--entrada",
        type=Path,
        default=carpeta / "influenza_rm_isp.csv",
        help="CSV de entrada (por defecto: influenza_rm_isp.csv).",
    )
    parser.add_argument(
        "--salida-csv",
        type=Path,
        default=carpeta / "influenza_rm_isp_completo.csv",
        help="Ruta del CSV completado.",
    )
    parser.add_argument(
        "--grafica",
        type=Path,
        default=carpeta / "influenza_rm_isp.svg",
        help="Ruta de la gráfica SVG.",
    )
    argumentos = parser.parse_args()
    cantidad = procesar_csv(
        argumentos.entrada,
        argumentos.salida_csv,
        argumentos.grafica,
    )
    print(
        f"Listo: {cantidad} semanas completadas. "
        f"CSV: {argumentos.salida_csv}; gráfica: {argumentos.grafica}"
    )


if __name__ == "__main__":
    main()
