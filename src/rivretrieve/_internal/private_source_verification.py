"""private GRDC email verification : OriginalEmlBytes → RedactedVerificationRecord (pure)."""

from __future__ import annotations

import hashlib
import re
from email import policy
from email.parser import BytesParser

from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import PrivateStatementVerification
from rivretrieve._internal.issues import FatalContractError

ORIGINAL_EMAIL_BYTES = 188_701
ORIGINAL_EMAIL_SHA256 = "5a12e0fd96d5f2b35e15cc75a76e6e9a62416a87d7d483e28be3d18c03a936e0"
FORWARDED_EMAIL_BYTES = 228_628
FORWARDED_EMAIL_SHA256 = "6ffc840e3a371cc7731fdd587e3d3a3918e47aa73c0e7e1c1251e54494054742"
WORKBOOK_BYTES = 116_301
WORKBOOK_SHA256 = "dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf"
WORKBOOK_FILENAME = "Metadata_GRDC_30.10.2025.xlsx"
STATEMENT_ID = "pl_imgw.grdc.inclusion"
QUOTE_SENTENCES = (
    "I just wanted to send you the metadata for all stations of Poland.",
    "Feel free to include them!",
)


PrivateEmailVerificationRecord = PrivateStatementVerification


def serialize_private_email_verification(record: PrivateEmailVerificationRecord) -> str:
    """Serialize only the redacted fields of a successful private verification."""
    return record.model_dump_json()


def parse_private_email_verification(body: bytes) -> PrivateEmailVerificationRecord:
    """Parse and pin a redacted record before canonical provenance consumes it."""
    try:
        record = PrivateEmailVerificationRecord.model_validate_json(body)
    except ValidationError as exc:
        raise FatalContractError("pl_imgw redacted private verification record is invalid") from exc
    expected = (
        record.statement_id == STATEMENT_ID
        and record.original_email_sha256 == ORIGINAL_EMAIL_SHA256
        and record.original_email_byte_count == ORIGINAL_EMAIL_BYTES
        and record.workbook_sha256 == WORKBOOK_SHA256
        and record.workbook_byte_count == WORKBOOK_BYTES
    )
    if not expected:
        raise FatalContractError("pl_imgw redacted private verification record identity mismatch")
    return record


def verify_original_grdc_email(body: bytes) -> PrivateEmailVerificationRecord:
    """Verify externally supplied original GRDC correspondence without retaining it.

    Parameters
    ----------
    body
        Exact bytes of the original private RFC 822 message.

    Returns
    -------
    PrivateEmailVerificationRecord
        Redacted digest-bound result containing no correspondence or personal data.

    Raises
    ------
    FatalContractError
        If original-message identity, quotation, or workbook attachment differs.
    """
    if len(body) != ORIGINAL_EMAIL_BYTES:
        raise FatalContractError(
            f"pl_imgw private original email byte count mismatch: expected {ORIGINAL_EMAIL_BYTES}, observed {len(body)}"
        )
    observed = hashlib.sha256(body).hexdigest()
    if observed != ORIGINAL_EMAIL_SHA256:
        raise FatalContractError(
            f"pl_imgw private original email digest mismatch: expected {ORIGINAL_EMAIL_SHA256}, observed {observed}"
        )
    try:
        message = BytesParser(policy=policy.default).parsebytes(body)
    except Exception as exc:
        raise FatalContractError("pl_imgw private original email cannot be parsed") from exc

    text_parts: list[str] = []
    workbook_payloads: list[bytes] = []
    for part in message.walk():
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if filename == WORKBOOK_FILENAME and isinstance(payload, bytes):
            workbook_payloads.append(payload)
        if part.get_content_type() == "text/plain":
            try:
                text_parts.append(part.get_content())
            except Exception as exc:
                raise FatalContractError("pl_imgw private original email text cannot be decoded") from exc
    text = "\n".join(text_parts).replace("\r\n", "\n")
    quotation = re.compile(re.escape(QUOTE_SENTENCES[0]) + r"\s+" + re.escape(QUOTE_SENTENCES[1]))
    if quotation.search(text) is None:
        raise FatalContractError(f"pl_imgw private statement {STATEMENT_ID}: exact quotation is absent")
    if len(workbook_payloads) != 1:
        raise FatalContractError(
            f"pl_imgw private original email must contain exactly one {WORKBOOK_FILENAME} attachment"
        )
    workbook = workbook_payloads[0]
    if len(workbook) != WORKBOOK_BYTES:
        raise FatalContractError(
            f"pl_imgw GRDC workbook byte count mismatch: expected {WORKBOOK_BYTES}, observed {len(workbook)}"
        )
    workbook_digest = hashlib.sha256(workbook).hexdigest()
    if workbook_digest != WORKBOOK_SHA256:
        raise FatalContractError(
            f"pl_imgw GRDC workbook digest mismatch: expected {WORKBOOK_SHA256}, observed {workbook_digest}"
        )
    return PrivateEmailVerificationRecord(
        schema_version=1,
        statement_id=STATEMENT_ID,
        original_email_sha256=ORIGINAL_EMAIL_SHA256,
        original_email_byte_count=ORIGINAL_EMAIL_BYTES,
        workbook_sha256=WORKBOOK_SHA256,
        workbook_byte_count=WORKBOOK_BYTES,
        verified=True,
    )
