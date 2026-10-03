"""Resolve explicit retained members into catalogue build support at composition."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import file_digest
from pathlib import Path

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    ArchiveMemberReference,
    CatalogueBuildInputs,
    CodeReference,
    RetainedInputReceipt,
    RetainedInputUse,
    RetainedSupportUse,
)
from rivretrieve._internal.issues import FatalContractError

_PUBLIC_REPOSITORY = "https://github.com/RivRetrieve/RivRetrieve"


def _archive_identity(reference: ArchiveMemberReference) -> ArchiveMemberReference:
    return ArchiveMemberReference.model_validate(
        {name: getattr(reference, name) for name in ArchiveMemberReference.model_fields}
    )


def verify_retained_input_files(receipt: RetainedInputReceipt, evidence_root: Path) -> None:
    """Verify exact composed bytes without treating this handoff as archive authority."""
    root = evidence_root.resolve(strict=True)
    for reference in (*receipt.inputs, *receipt.declaration_inputs):
        path = (root / reference.consumer_path).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise FatalContractError("Retained catalogue input escapes its explicit root")
        with path.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        if path.stat().st_size != reference.byte_size or digest != reference.sha256:
            raise FatalContractError("Retained catalogue input differs from its resolved archive identity")


def select_catalogue_build_inputs(
    provenance: AcquisitionProvenance,
    receipt: RetainedInputReceipt,
    native_acquisition_ids: Sequence[str],
    declaration_locations: Sequence[tuple[str, str | None]],
    *,
    recording_artifact_sha256: Mapping[str, str] | None = None,
    supporting_inputs: Mapping[str, Sequence[str]] | None = None,
) -> CatalogueBuildInputs:
    """Select native materialisation and exact recordings from explicit archived members.

    The native acquisition declaration identifies existing historical source facts
    represented by the native table. Its use does not certify missing originals.
    Recording paths are historical public consumer identities, resolved only in
    the supplied receipt. No source checkout or archive inventory is searched.
    """
    if receipt.code_revision != receipt.declaration_revision:
        raise FatalContractError("This build requires explicitly selected declarations at the executed code revision")
    native = provenance.native_table
    if native is None:
        raise FatalContractError("Catalogue publication requires an established native input identity")
    selected = {item.consumer_path: item for item in receipt.inputs}
    try:
        native_reference = selected[native.repository_path]
    except KeyError:
        raise FatalContractError("Selected archive inputs omit the declared native table") from None
    if native_reference.sha256 != native.sha256 or (
        native.byte_size is not None and native_reference.byte_size != native.byte_size
    ):
        raise FatalContractError("Selected native member differs from the historical native identity")
    known = {
        acquisition.acquisition_id
        for source in provenance.source_records
        for acquisition in source.acquisitions
        if acquisition.method != "runtime_http_request"
    }
    if not native_acquisition_ids or not set(native_acquisition_ids) <= known:
        raise FatalContractError("Native materialisation acquisition declaration does not resolve")
    native_facts = tuple(
        fact
        for binding in provenance.fact_bindings
        if binding.transformation is None and binding.acquisition_id in native_acquisition_ids
        for fact in binding.facts
    )
    if not native_facts:
        raise FatalContractError("Native materialisation has no explicit source fact support")
    uses = [RetainedInputUse(reference=_archive_identity(native_reference), usage="native_table", facts=native_facts)]
    facts_by_acquisition: dict[tuple[str, str], list[str]] = defaultdict(list)
    for binding in provenance.fact_bindings:
        if binding.source_id is not None and binding.acquisition_id is not None:
            facts_by_acquisition[(binding.source_id, binding.acquisition_id)].extend(binding.facts)
    recording_facts: dict[str, list[str]] = defaultdict(list)
    for source in provenance.source_records:
        recordings = {item.recording.recording_id: item.recording for item in source.evidence}
        for acquisition in source.acquisitions:
            facts = facts_by_acquisition[(source.source_id, acquisition.acquisition_id)]
            if not facts:
                continue
            for recording_id in acquisition.recording_ids:
                recording = recordings[recording_id]
                try:
                    reference = selected[recording.repository_path]
                except KeyError:
                    raise FatalContractError("Selected archive inputs omit a declared source recording") from None
                # A retained recording envelope and its decoded publisher body
                # have separate identities. An explicit matching material record
                # identifies the envelope; never replace the recorded body digest.
                material = acquisition.material
                envelope = material is not None and material.filename in {
                    recording.repository_path,
                    Path(recording.repository_path).name,
                }
                expected_sha256 = material.sha256 if envelope and material is not None else recording.sha256
                if recording_artifact_sha256 is not None and recording.repository_path in recording_artifact_sha256:
                    expected_sha256 = recording_artifact_sha256[recording.repository_path]
                if reference.sha256 != expected_sha256 or (
                    envelope and material is not None and reference.byte_size != material.byte_count
                ):
                    raise FatalContractError("Selected recording member differs from its historical byte identity")
                recording_facts[recording.repository_path].extend(facts)
    for path, facts in sorted(recording_facts.items()):
        uses.append(
            RetainedInputUse(
                reference=_archive_identity(selected[path]), usage="recording", facts=tuple(dict.fromkeys(facts))
            )
        )
    for path, supported_facts in (supporting_inputs or {}).items():
        try:
            reference = selected[path]
        except KeyError:
            raise FatalContractError("Selected archive inputs omit an explicit supporting declaration") from None
        uses.append(
            RetainedInputUse(
                reference=_archive_identity(reference), usage="reviewed_support", facts=tuple(supported_facts)
            )
        )
    grouped: dict[tuple[ArchiveMemberReference, str], RetainedInputUse] = {}
    for use in uses:
        key = (use.reference, use.usage)
        previous = grouped.get(key)
        grouped[key] = RetainedInputUse(
            reference=use.reference,
            usage=use.usage,
            facts=tuple(dict.fromkeys((*(previous.facts if previous else ()), *use.facts))),
        )
    uses = list(grouped.values())
    provider_path = f"src/rivretrieve/_internal/providers/{provenance.provider_id}"

    def code(path: str, symbol: str | None, revision: str) -> CodeReference:
        return CodeReference(repository=_PUBLIC_REPOSITORY, revision=revision, repository_path=path, symbol=symbol)

    authored = {item.consumer_path: item.declaration for item in receipt.declaration_inputs}
    declarations = []
    for path, symbol in declaration_locations:
        if path.startswith("src/"):
            declarations.append(code(path, symbol, receipt.declaration_revision))
        else:
            try:
                declaration = authored[path]
            except KeyError:
                raise FatalContractError("Selected inputs omit a required reviewed declaration") from None
            if symbol is not None:
                raise FatalContractError("Authored evidence inputs must identify whole declaration files")
            declarations.append(declaration)
    return CatalogueBuildInputs(
        build=code(provider_path + "/generate_catalogue.py", "write_catalogue", receipt.code_revision),
        declarations=tuple(declarations),
        inputs=tuple(uses),
    )


def select_catalogue_support(
    provenance: AcquisitionProvenance,
    receipt: RetainedInputReceipt,
    *,
    family: str,
    locations: Mapping[str, Sequence[str]],
    verifier_location: tuple[str, str],
) -> tuple[RetainedSupportUse, ...]:
    """Link explicit reviewed ledger locators to already verified archive support.

    No support body is opened here. The receipt supplies only members from
    successful complete governing checks. A nested archive selector identifies
    an inner source material, never an independently manifested archive member.
    """
    available = {item.verifier_path: item for item in receipt.support_inputs if item.provider_id == family}
    acquisitions = {}
    facts = defaultdict(list)
    for source in provenance.source_records:
        for acquisition in source.acquisitions:
            if acquisition.acquisition_id in locations:
                if acquisition.acquisition_id in acquisitions:
                    raise FatalContractError("A support locator has ambiguous source acquisition ownership")
                acquisitions[acquisition.acquisition_id] = acquisition
    for binding in provenance.fact_bindings:
        if binding.acquisition_id in locations:
            facts[binding.acquisition_id].extend(binding.facts)
    if set(locations) != set(acquisitions) or any(not facts[key] for key in locations):
        raise FatalContractError("A support locator does not resolve an existing acquired source fact")
    verifier = CodeReference(
        repository="https://github.com/RivRetrieve/verification-evidence",
        revision=receipt.archive_code_revision,
        repository_path=verifier_location[0],
        symbol=verifier_location[1],
    )
    result = []
    for acquisition_id, locators in locations.items():
        acquisition = acquisitions[acquisition_id]
        if acquisition.method == "runtime_http_request" or not locators:
            raise FatalContractError("Reviewed support must name retained material for a historical acquisition")
        for locator in dict.fromkeys(locators):
            outer, separator, inner = locator.partition("!")
            if separator and (not inner or "!" in inner):
                raise FatalContractError("Invalid nested source material selector")
            try:
                selected = available[outer]
            except KeyError:
                raise FatalContractError(
                    "Complete governing support omits a required reviewed ledger locator"
                ) from None
            material = acquisition.material
            if separator:
                if material is None or material.filename != locator:
                    raise FatalContractError("Nested support differs from the recorded inner material identity")
            elif (
                material is not None
                and material.filename in {outer, Path(outer).name}
                and (material.sha256 != selected.sha256 or material.byte_count != selected.byte_size)
            ):
                raise FatalContractError("Selected support differs from the historical source material")
            reference = ArchiveMemberReference.model_validate(
                {name: getattr(selected, name) for name in ArchiveMemberReference.model_fields}
            )
            result.append(
                RetainedSupportUse(
                    reference=reference,
                    facts=tuple(dict.fromkeys(facts[acquisition_id])),
                    member_selector=inner if separator else None,
                    verification_kind=selected.verification_kind,
                    verifier=verifier,
                )
            )
    return tuple(result)


def verify_recording_envelopes(
    provenance: AcquisitionProvenance,
    receipt: RetainedInputReceipt,
    evidence_root: Path,
) -> dict[str, str]:
    """Keep archived recording-envelope bytes distinct from their publisher body.

    Historical references can identify decoded RecordingEnvelope content. When
    that digest differs from the selected archive member, verify both exact
    identities before exposing the outer artifact as retained support.
    """
    from rivretrieve._internal.recordings import read_recording

    selected = {item.consumer_path: item for item in receipt.inputs}
    identities = {}
    for source in provenance.source_records:
        for evidence in source.evidence:
            recording = evidence.recording
            reference = selected.get(recording.repository_path)
            if reference is None or reference.sha256 == recording.sha256:
                continue
            established_envelopes = (
                acquisition.material
                for acquisition in source.acquisitions
                if recording.recording_id in acquisition.recording_ids and acquisition.material is not None
            )
            if any(
                material.filename in {recording.repository_path, Path(recording.repository_path).name}
                and material.sha256 == reference.sha256
                and material.byte_count == reference.byte_size
                for material in established_envelopes
            ):
                continue
            subset = receipt.model_copy(update={"inputs": (reference,), "support_inputs": ()})
            verify_retained_input_files(subset, evidence_root)
            try:
                envelope = read_recording(evidence_root / reference.consumer_path)
            except (ValueError, OSError, FatalContractError):
                raise FatalContractError(
                    "Selected recording is neither the exact source body nor its declared envelope"
                ) from None
            if (
                envelope.sha256 != recording.sha256
                or envelope.retrieved_at != recording.retrieved_at
                or envelope.request.url != recording.source_url
            ):
                raise FatalContractError(
                    "Selected recording envelope differs from the historical source body or acquisition"
                )
            identities[reference.consumer_path] = reference.sha256
    return identities
