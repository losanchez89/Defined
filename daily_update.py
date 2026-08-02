from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, LOG_DIR
from download_gmail_reports import download_reports


def configure_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_path = LOG_DIR / (
        f"daily_update_{datetime.now():%Y%m%d}.log"
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    return log_path


def run_etl() -> int:
    etl_script = BASE_DIR / "upload_daily_csvs.py"

    if not etl_script.exists():
        raise FileNotFoundError(
            f"No se encontró el ETL: {etl_script}"
        )

    result = subprocess.run(
        [sys.executable, str(etl_script)],
        cwd=BASE_DIR,
        check=False,
    )

    return result.returncode


def main() -> None:
    log_path = configure_logging()

    logging.info("Iniciando actualización diaria.")
    logging.info("Descargando reportes desde Gmail.")

    summary = download_reports()

    if summary.errors:
        logging.error(
            "La descarga terminó con %s error(es).",
            len(summary.errors),
        )

        for error in summary.errors:
            logging.error(error)

        raise SystemExit(1)

    logging.info(
        "Correos encontrados: %s.",
        summary.emails_found,
    )

    logging.info(
        "Archivos descargados: %s.",
        len(summary.downloaded_files),
    )

    for downloaded_file in summary.downloaded_files:
        logging.info(
            "Archivo guardado: %s",
            downloaded_file.name,
        )

    if summary.skipped_duplicates:
        logging.info(
            "Duplicados omitidos: %s.",
            len(summary.skipped_duplicates),
        )

    if summary.unmatched_subjects:
        logging.warning(
            "Asuntos sin mapeo: %s",
            summary.unmatched_subjects,
        )

    if not summary.downloaded_files:
        logging.error(
            "No se descargó ningún archivo. "
            "El ETL no se ejecutará para evitar cargar reportes antiguos."
        )
        raise SystemExit(1)

    logging.info("Ejecutando upload_daily_csvs.py.")

    exit_code = run_etl()

    if exit_code != 0:
        logging.error(
            "El ETL terminó con código de salida %s.",
            exit_code,
        )
        raise SystemExit(exit_code)

    logging.info(
        "Actualización diaria completada correctamente."
    )
    logging.info(
        "Log guardado en: %s",
        log_path,
    )


if __name__ == "__main__":
    main()