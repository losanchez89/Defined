from __future__ import annotations

import base64
import logging
import re
import json
import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import (
    ALLOWED_EXTENSIONS,
    CREDENTIALS_FILE,
    GMAIL_SCOPES,
    GMAIL_SEARCH_QUERY,
    RAW_DIR,
    REPORT_FILE_MAPPING,
    RINGCENTRAL_URL_FRAGMENT,
    TOKEN_FILE,
)


@dataclass
class DownloadSummary:
    emails_found: int = 0
    downloaded_files: list[Path] = field(default_factory=list)
    skipped_duplicates: list[str] = field(default_factory=list)
    unmatched_subjects: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

def get_gmail_service():
    creds = None

    token_json = os.getenv("GMAIL_TOKEN_JSON", "").strip()
    credentials_json = os.getenv("GMAIL_CREDENTIALS_JSON", "").strip()

    # Railway: cargar token directamente desde variable de entorno
    if token_json:
        try:
            token_info = json.loads(token_json)
            creds = Credentials.from_authorized_user_info(
                token_info,
                GMAIL_SCOPES,
            )
        except Exception as exc:
            raise ValueError(
                "GMAIL_TOKEN_JSON no contiene un JSON válido."
            ) from exc

    # Local: usar token.json
    elif TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_FILE),
            GMAIL_SCOPES,
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        else:
            # Railway no puede abrir el navegador para autorizar Gmail
            if os.getenv("RAILWAY_ENVIRONMENT"):
                raise RuntimeError(
                    "El token de Gmail no es válido o no contiene "
                    "refresh_token. Actualiza GMAIL_TOKEN_JSON en Railway."
                )

            # Ejecución local interactiva
            if credentials_json:
                try:
                    client_config = json.loads(credentials_json)
                except Exception as exc:
                    raise ValueError(
                        "GMAIL_CREDENTIALS_JSON no contiene un JSON válido."
                    ) from exc

                flow = InstalledAppFlow.from_client_config(
                    client_config,
                    GMAIL_SCOPES,
                )

            else:
                if not CREDENTIALS_FILE.exists():
                    raise FileNotFoundError(
                        f"No se encontró el archivo: {CREDENTIALS_FILE}"
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_FILE),
                    GMAIL_SCOPES,
                )

            creds = flow.run_local_server(port=0)

            TOKEN_FILE.write_text(
                creds.to_json(),
                encoding="utf-8",
            )

    return build(
        "gmail",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )


def normalize_subject(subject: str) -> str:
    normalized = subject.strip().lower()
    normalized = re.sub(r"^\s*(rv|fw|fwd)\s*:\s*", "", normalized)
    normalized = re.sub(r"\s*-\s*streamlit\s*$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def get_standard_filename(subject: str, original_filename: str) -> str:
    normalized = normalize_subject(subject)

    mapped_name = REPORT_FILE_MAPPING.get(normalized)
    if mapped_name:
        return mapped_name

    cleaned = re.sub(r'[<>:"/\\|?*]', "_", original_filename.strip())
    return cleaned or "attachment"


def get_header(headers: list[dict[str, Any]], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return str(header.get("value", ""))
    return ""


def decode_base64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def iter_attachment_parts(payload: dict[str, Any]):
    for part in payload.get("parts", []):
        filename = str(part.get("filename", ""))
        body = part.get("body", {})

        if filename and body.get("attachmentId"):
            yield part

        if part.get("parts"):
            yield from iter_attachment_parts(part)


def decode_part_data(part: dict[str, Any]) -> str:
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    return decode_base64url(data).decode("utf-8", errors="replace")


def find_html_part(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/html":
        return decode_part_data(payload)

    for part in payload.get("parts", []):
        html = find_html_part(part)
        if html:
            return html

    return ""


def find_ringcentral_report_url(html: str) -> str | None:
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        url = str(anchor["href"]).strip()
        if RINGCENTRAL_URL_FRAGMENT in url:
            return url

    return None


def get_ringcentral_output_filename(html: str) -> str:
    """Determina el nombre local según la suscripción de RingCentral.

    - Subscription name: pbi         -> Users_Dashboard.xlsx
    - Subscription name: daily calls -> daily_calls.xlsx
    """
    if not html:
        raise ValueError(
            "El correo de RingCentral no contiene cuerpo HTML."
        )

    soup = BeautifulSoup(html, "html.parser")
    body_text = soup.get_text("\n", strip=True)

    match = re.search(
        r"subscription\s+name\s*:\s*([^\n\r]+)",
        body_text,
        flags=re.IGNORECASE,
    )

    if not match:
        raise ValueError(
            "No se encontró 'Subscription name' en el correo de RingCentral."
        )

    subscription_name = re.sub(
        r"\s+",
        " ",
        match.group(1),
    ).strip().lower()

    if subscription_name == "pbi":
        return "Users_Dashboard.xlsx"

    if subscription_name == "daily calls":
        return "daily_calls.xlsx"

    raise ValueError(
        f"Suscripción de RingCentral no reconocida: {subscription_name}"
    )


def filename_from_content_disposition(
    content_disposition: str,
) -> str | None:
    if not content_disposition:
        return None

    utf_match = re.search(
        r"filename\*=UTF-8''([^;]+)",
        content_disposition,
        flags=re.IGNORECASE,
    )
    if utf_match:
        return unquote(utf_match.group(1))

    normal_match = re.search(
        r'filename="?([^";]+)"?',
        content_disposition,
        flags=re.IGNORECASE,
    )
    if normal_match:
        return normal_match.group(1)

    return None


def download_attachment(
    service,
    message_id: str,
    part: dict[str, Any],
    subject: str,
    output_dir: Path,
) -> Path | None:
    original_filename = str(part.get("filename", "attachment"))
    original_extension = Path(original_filename).suffix.lower()

    if original_extension not in ALLOWED_EXTENSIONS:
        return None

    output_filename = get_standard_filename(subject, original_filename)
    output_path = output_dir / output_filename

    attachment_id = part.get("body", {}).get("attachmentId")
    if not attachment_id:
        return None

    attachment = (
        service.users()
        .messages()
        .attachments()
        .get(
            userId="me",
            messageId=message_id,
            id=attachment_id,
        )
        .execute()
    )

    raw_data = attachment.get("data")
    if not raw_data:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(decode_base64url(raw_data))
    return output_path


def download_ringcentral_report(
    report_url: str,
    output_dir: Path,
    output_filename: str,
) -> Path | None:
    response = requests.get(
        report_url,
        timeout=60,
        allow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150 Safari/537.36"
            )
        },
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    disposition = response.headers.get("Content-Disposition", "")

    is_excel = (
        "spreadsheet" in content_type
        or "excel" in content_type
        or ".xlsx" in disposition.lower()
        or ".xls" in disposition.lower()
    )

    if not is_excel:
        raise ValueError(
            "El enlace de RingCentral no devolvió un archivo Excel."
        )

    _ = filename_from_content_disposition(disposition)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename
    output_path.write_bytes(response.content)
    return output_path


def list_matching_messages(service) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    page_token = None

    while True:
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=GMAIL_SEARCH_QUERY,
                maxResults=100,
                pageToken=page_token,
            )
            .execute()
        )

        messages.extend(response.get("messages", []))
        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return messages


def download_reports() -> DownloadSummary:
    summary = DownloadSummary()
    service = get_gmail_service()
    messages = list_matching_messages(service)
    summary.emails_found = len(messages)

    if not messages:
        print("No se encontraron reportes recientes.")
        return summary

    processed_message_files: set[str] = set()
    processed_ringcentral_urls: set[str] = set()
    processed_ringcentral_files: set[str] = set()

    print(f"Correos encontrados: {len(messages)}")
    print("-" * 60)

    for item in messages:
        message_id = item["id"]
        subject = ""

        try:
            message = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="full",
                )
                .execute()
            )

            payload = message.get("payload", {})
            headers = payload.get("headers", [])

            subject = get_header(headers, "Subject")

            normalized_subject = normalize_subject(subject)

            # Ignorar cualquier correo cuyo asunto no corresponda
            # a un reporte que conocemos.
            if (
                normalized_subject not in REPORT_FILE_MAPPING
                and "ringcentral" not in normalized_subject
            ):
                continue

            sender = get_header(headers, "From")
            date = get_header(headers, "Date")
            normalized_subject = normalize_subject(subject)

            print(f"Asunto: {subject}")
            print(f"De: {sender}")
            print(f"Fecha: {date}")

            if normalized_subject not in REPORT_FILE_MAPPING:
                summary.unmatched_subjects.append(subject)

            message_downloads = 0

            for part in iter_attachment_parts(payload):
                standard_name = get_standard_filename(
                    subject,
                    str(part.get("filename", "attachment")),
                )

                if standard_name in processed_message_files:
                    summary.skipped_duplicates.append(standard_name)
                    print(f"Duplicado omitido: {standard_name}")
                    continue

                output_path = download_attachment(
                    service=service,
                    message_id=message_id,
                    part=part,
                    subject=subject,
                    output_dir=RAW_DIR,
                )

                if output_path:
                    processed_message_files.add(output_path.name)
                    summary.downloaded_files.append(output_path)
                    message_downloads += 1
                    print(f"Descargado como: {output_path.name}")

            if (
                message_downloads == 0
                and normalized_subject
                == "scheduled reports from ringcentral"
            ):
                html = find_html_part(payload)
                report_url = find_ringcentral_report_url(html)
                output_filename = get_ringcentral_output_filename(html)

                if not report_url:
                    raise ValueError(
                        "No se encontró el enlace del reporte de RingCentral."
                    )

                # Gmail devuelve primero los correos más recientes. Así se guarda
                # solamente el reporte más nuevo de cada suscripción y se omiten
                # los del día anterior aunque tengan una URL diferente.
                if output_filename in processed_ringcentral_files:
                    summary.skipped_duplicates.append(output_filename)
                    print(
                        f"Duplicado de RingCentral omitido: "
                        f"{output_filename}"
                    )
                elif report_url in processed_ringcentral_urls:
                    summary.skipped_duplicates.append(output_filename)
                    print("Enlace duplicado de RingCentral omitido.")
                else:
                    processed_ringcentral_urls.add(report_url)
                    processed_ringcentral_files.add(output_filename)

                    ringcentral_file = download_ringcentral_report(
                        report_url=report_url,
                        output_dir=RAW_DIR,
                        output_filename=output_filename,
                    )
                    if ringcentral_file:
                        summary.downloaded_files.append(
                            ringcentral_file
                        )
                        message_downloads += 1
                        print(
                            f"Descargado como: "
                            f"{ringcentral_file.name}"
                        )

            if message_downloads == 0:
                print("No se descargaron archivos desde este correo.")

        except Exception as exc:
            error = f"{subject or message_id}: {exc}"
            summary.errors.append(error)
            logging.exception(error)
            print(f"ERROR: {error}")

        print("-" * 60)

    print()
    print(
        f"Total de archivos descargados: "
        f"{len(summary.downloaded_files)}"
    )
    print(f"Duplicados omitidos: {len(summary.skipped_duplicates)}")
    print(f"Carpeta de destino: {RAW_DIR}")

    return summary


def main() -> None:
    summary = download_reports()

    if summary.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()