"""japan catalogue authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SemanticDigest,
    SourceRecord,
    SourceStatement,
)
from rivretrieve._internal.catalogue_origins import Evidence, Field, NativeColumn, NotPublished

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("観測所記号")),
    "station_id": Field(NativeColumn("観測所記号")),
    "latitude": Field(NativeColumn("世界測地系")),
    "longitude": Field(NativeColumn("世界測地系")),
    "crs": NotPublished(Evidence("http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=301011281104010")),
}

NATIVE_TABLE_SHA256 = "ec892e4bc5bee3e8d5435190f4163ecddd80d2d244a71c810b9cf666d06b5aad"
NATIVE_TABLE_REVISION = "ebeee6673f183a2bd182e81ee2b4bff7d56ee009"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet"
NATIVE_TABLE_SEMANTIC_SHA256 = "f3c42f03fc0280c14910dc4203fc8031b9d5cddcc0cc8a6431c3c9268602aec0"


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build Japan's shared acquisition-provenance document.

    Returns
    -------
    AcquisitionProvenance
        Immutable source records and fact bindings for the Japan provider.
    """
    licence_recording = RecordingReference(
        recording_id="jp_mlit_terms_licence_euc_jp",
        repository_path="tests/test_data/jp_mlit_terms_licence_euc_jp.html",
        source_url="http://www1.river.go.jp/caution.html",
        retrieved_at=datetime.fromisoformat("2026-08-21T09:46:54Z"),
        media_type="text/html; charset=EUC-JP",
        sha256="b35c11981f4ad3a53c25a3746fe676d6f989ee3beae384ec45c735acd62fdc5b",
    )
    citation_recording = RecordingReference(
        recording_id="jp_mlit_terms_citation",
        repository_path="tests/test_data/jp_mlit_terms_citation.pdf",
        source_url="http://www1.river.go.jp/WDBrules_20251210.pdf",
        retrieved_at=datetime.fromisoformat("2026-08-21T09:47:00Z"),
        media_type="application/pdf",
        sha256="1fbe9cccc866b3f496b7be4fcb546124c24e0c89fc3e57ab0a3ceca97107d487",
    )
    return AcquisitionProvenance(
        schema_version=1,
        provider_id="jp_mlit",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            semantic_digest=SemanticDigest(
                name="jp_mlit.native_table_content_sha256",
                sha256=NATIVE_TABLE_SEMANTIC_SHA256,
            ),
        ),
        source_records=(
            SourceRecord(
                source_id="jp_mlit",
                issuer="Ministry of Land, Infrastructure, Transport and Tourism",
                operator="MLIT Water Information System",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="station_register_capture_2026_08_02",
                        method="http_campaign",
                        description=(
                            "1,024 requests seeded by the legacy packaged station identifiers; "
                            "1,023 accepted MLIT station-detail responses and one source-confirmed absence"
                        ),
                        requested_from=("http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=<station_id>",),
                        retrieved_at_start=datetime.fromisoformat("2026-08-02T19:35:42Z"),
                        retrieved_at_end=datetime.fromisoformat("2026-08-02T19:50:45Z"),
                    ),
                    AcquisitionRecord(
                        acquisition_id="observation_request",
                        method="runtime_http_request",
                        description=(
                            "Observation requests are acquired from MLIT DspWaterData pages and "
                            "the referenced Shift-JIS data download; each result retains its runtime calls"
                        ),
                        requested_from=(
                            "http://www1.river.go.jp/cgi-bin/DspWaterData.exe",
                            "http://www1.river.go.jp/dat/dload/download/<published-file>",
                        ),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="jp_mlit_licence_statement",
                        description="MLIT Water Information System terms page recording",
                        recording=licence_recording,
                    ),
                    EvidenceReference(
                        evidence_id="jp_mlit_citation_statement",
                        description="MLIT Public Data License 1.0 PDF recording",
                        recording=citation_recording,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="license",
                        exact_text=(
                            "水文水質データベースをご利用いただく際、掲載しているデータの利用について、"
                            "許可等は必要ありません。 「公共データ利用規約（第1.0版）」に従い、データをご利用ください。"
                        ),
                        recording_id=licence_recording.recording_id,
                    ),
                    SourceStatement(
                        kind="citation",
                        exact_text=(
                            "出典： 国土交通省 水文水質データベース "
                            "（https://www1.river.go.jp/）（○年○月○日に参 照）、"
                            "PDL1.0（http://www1.river.go.jp/）"
                        ),
                        recording_id=citation_recording.recording_id,
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="station_identity_and_location",
                facts=(
                    "station.station_id",
                    "station.latitude",
                    "station.longitude",
                    "station.crs_not_published",
                ),
                source_id="jp_mlit",
                acquisition_id="station_register_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="product_identity",
                facts=("product.native_id", "station_product.availability_not_published"),
                source_id="jp_mlit",
                acquisition_id="station_register_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="observation_acquisition",
                facts=(
                    "observation.request",
                    "observation.response",
                    "observation.value",
                    "observation.quality",
                ),
                source_id="jp_mlit",
                acquisition_id="observation_request",
            ),
        ),
    )
