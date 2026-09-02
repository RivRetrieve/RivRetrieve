"""private GRDC email verification : PrivateEmlBytes → RedactedVerificationRecord (pure)."""

from __future__ import annotations

import hashlib
import re
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import PrivateStatementVerification
from rivretrieve._internal.issues import FatalContractError

FORWARDED_EMAIL_BYTES = 228_628
FORWARDED_EMAIL_SHA256 = "6ffc840e3a371cc7731fdd587e3d3a3918e47aa73c0e7e1c1251e54494054742"
WORKBOOK_BYTES = 116_301
WORKBOOK_SHA256 = "dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf"
WORKBOOK_FILENAME = "Metadata_GRDC_30.10.2025.xlsx"
STATEMENT_ID = "pl_imgw.grdc.inclusion"
STATEMENT_SHA256 = "a95a0e6b9f0f26c87b2d04e02098b3c0dbc24525bdd75b17dfddfa0cd0c443c2"

PrivateEmailVerificationRecord = PrivateStatementVerification


def serialize_private_email_verification(record: PrivateEmailVerificationRecord) -> str:
    """Serialize only the redacted fields of a successful private verification."""
    return record.model_dump_json()


def validate_private_email_verification_pin(
    record: PrivateEmailVerificationRecord,
) -> PrivateEmailVerificationRecord:
    """Validate every public binding of the provider-specific forwarded-copy pin."""
    expected_evidence = (FORWARDED_EMAIL_SHA256, FORWARDED_EMAIL_BYTES)
    expected = (
        record.statement_id == STATEMENT_ID
        and record.evidence_kind == "forwarded_copy"
        and record.limitation == "original_byte_identity_not_established"
        and (record.evidence_sha256, record.evidence_byte_count) == expected_evidence
        and record.workbook_sha256 == WORKBOOK_SHA256
        and record.workbook_byte_count == WORKBOOK_BYTES
        and record.statement_sha256 == STATEMENT_SHA256
        and record.decoded_text_plain_occurrence_count == 1
        and record.decoded_text_html_occurrence_count == 1
        and record.verified is True
    )
    if not expected:
        raise FatalContractError("pl_imgw redacted private verification record identity mismatch")
    return record


def parse_private_email_verification(body: bytes) -> PrivateEmailVerificationRecord:
    """Parse and pin a redacted record before canonical provenance consumes it."""
    try:
        record = PrivateEmailVerificationRecord.model_validate_json(body)
    except ValidationError as exc:
        raise FatalContractError("pl_imgw redacted private verification record is invalid") from exc
    return validate_private_email_verification_pin(record)


class _PrivateHtmlText(HTMLParser):
    """Extract text from a private HTML MIME part without retaining metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _quotation_pattern(expected_exact_text: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(part) for part in expected_exact_text.split()))


def _verify_workbook_attachment(workbook_payloads: list[bytes], *, evidence_label: str) -> None:
    if len(workbook_payloads) != 1:
        raise FatalContractError(
            f"pl_imgw private {evidence_label} email must contain exactly one {WORKBOOK_FILENAME} attachment"
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


def verify_forwarded_grdc_email(body: bytes, expected_exact_text: str) -> PrivateEmailVerificationRecord:
    """Verify the pinned forwarded copy without claiming original-message identity.

    Parameters
    ----------
    body
        Exact bytes of the authorized private forwarded RFC 822 message.
    expected_exact_text
        Private excerpt checked locally and omitted from the redacted result.

    Returns
    -------
    PrivateEmailVerificationRecord
        Redacted forwarded-copy evidence with an explicit identity limitation.

    Raises
    ------
    FatalContractError
        If outer identity, quotation multiplicity, or workbook identity differs.
    """
    statement_digest = hashlib.sha256(expected_exact_text.encode("utf-8")).hexdigest()
    if statement_digest != STATEMENT_SHA256:
        raise FatalContractError(f"pl_imgw private statement {STATEMENT_ID}: exact words do not match the pin")
    if len(body) != FORWARDED_EMAIL_BYTES:
        raise FatalContractError(
            f"pl_imgw private forwarded email byte count mismatch: expected {FORWARDED_EMAIL_BYTES}, observed {len(body)}"
        )
    observed = hashlib.sha256(body).hexdigest()
    if observed != FORWARDED_EMAIL_SHA256:
        raise FatalContractError(
            f"pl_imgw private forwarded email digest mismatch: expected {FORWARDED_EMAIL_SHA256}, observed {observed}"
        )
    try:
        message = BytesParser(policy=policy.default).parsebytes(body)
    except Exception as exc:
        raise FatalContractError("pl_imgw private forwarded email cannot be parsed") from exc

    text_by_type: dict[str, list[str]] = {"text/plain": [], "text/html": []}
    workbook_payloads: list[bytes] = []
    for part in message.walk():
        payload = part.get_payload(decode=True)
        if part.get_filename() == WORKBOOK_FILENAME and isinstance(payload, bytes):
            workbook_payloads.append(payload)
        content_type = part.get_content_type()
        if content_type not in text_by_type:
            continue
        try:
            content = part.get_content()
        except Exception as exc:
            raise FatalContractError("pl_imgw private forwarded email text cannot be decoded") from exc
        if not isinstance(content, str):
            raise FatalContractError("pl_imgw private forwarded email text cannot be decoded")
        if content_type == "text/html":
            parser = _PrivateHtmlText()
            parser.feed(content)
            content = " ".join(parser.parts)
        text_by_type[content_type].append(content)

    quotation = _quotation_pattern(expected_exact_text)
    for content_type, parts in text_by_type.items():
        count = sum(len(quotation.findall(part.replace("\r\n", "\n"))) for part in parts)
        if count != 1:
            raise FatalContractError(
                f"pl_imgw private statement {STATEMENT_ID}: exact quotation must occur exactly once in {content_type}"
            )
    _verify_workbook_attachment(workbook_payloads, evidence_label="forwarded")
    return PrivateEmailVerificationRecord(
        schema_version=2,
        statement_id=STATEMENT_ID,
        evidence_kind="forwarded_copy",
        limitation="original_byte_identity_not_established",
        evidence_sha256=FORWARDED_EMAIL_SHA256,
        evidence_byte_count=FORWARDED_EMAIL_BYTES,
        workbook_sha256=WORKBOOK_SHA256,
        workbook_byte_count=WORKBOOK_BYTES,
        statement_sha256=statement_digest,
        decoded_text_plain_occurrence_count=1,
        decoded_text_html_occurrence_count=1,
        verified=True,
    )
