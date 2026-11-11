import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


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
    semanas = sorted(datos)
    semanas_etiquetadas = set(range(semanas[0], semanas[-1] + 1, 4))
    semanas_etiquetadas.update((semanas[0], semanas[-1]))
    valores = [datos[semana] for semana in semanas]
    escala_y = max(valores) * 1.1 if max(valores) > 0 else 1
    figura, eje = plt.subplots(figsize=(11, 6.2), dpi=100)
    eje.bar(semanas, valores, width=0.8, color="#1565c0", zorder=3)
    eje.set(
        title="Casos de influenza por semana epidemiológica",
        xlabel="Semana epidemiológica",
        ylabel="Casos",
        xlim=(semanas[0] - 0.5, semanas[-1] + 0.5),
        ylim=(0, escala_y),
    )
    eje.set_xticks(sorted(semanas_etiquetadas))
    eje.grid(axis="y", color="#d9e0e5", zorder=0)
    eje.set_axisbelow(True)
    figura.tight_layout()
    figura.savefig(archivo_salida, format="png", facecolor="white")
    plt.close(figura)


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
        description="Completa semanas faltantes del CSV y genera una gráfica PNG."
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
        default=carpeta / "influenza_rm_isp.png",
        help="Ruta de la gráfica PNG.",
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
