import pytest
from pydantic import ValidationError

from triage.v1.extractor import Extractor, ExtractorConfig
from triage.v1.settings import V1Config


@pytest.fixture(scope="module")
def extractor(v1_config: V1Config) -> Extractor:
    return Extractor(v1_config.parsing.extractor)


def test_finds_every_identifier_in_subject_and_text(extractor: Extractor) -> None:
    fields = extractor.extract(
        subject="Laptop CH-LT-00042 won't sign in",
        text="Employee E123456 gets AADSTS50076, then 0x80070005 and ERR-4012.",
    )

    assert fields.employee_ids == ("E123456",)
    assert fields.asset_tags == ("CH-LT-00042",)
    assert fields.error_codes == ("AADSTS50076", "0x80070005", "ERR-4012")


def test_duplicates_are_removed_keeping_first_seen_order(extractor: Extractor) -> None:
    fields = extractor.extract("", "CH-WOW-00007 and CH-SCN-00003, again CH-WOW-00007")

    assert fields.asset_tags == ("CH-WOW-00007", "CH-SCN-00003")


def test_identifier_case_is_normalised(extractor: Extractor) -> None:
    fields = extractor.extract("", "id e654321 on ch-prn-00011")

    assert fields.employee_ids == ("E654321",)
    assert fields.asset_tags == ("CH-PRN-00011",)


@pytest.mark.parametrize(
    "text",
    ["E12345", "E1234567", "XE123456", "CH-XX-00001", "CH-LT-0042", "0x1234", "ERR-12"],
)
def test_near_misses_are_not_extracted(extractor: Extractor, text: str) -> None:
    fields = extractor.extract("", text)

    assert fields.employee_ids == fields.asset_tags == fields.error_codes == ()


def test_invalid_regex_in_config_is_rejected() -> None:
    with pytest.raises(ValidationError, match="invalid regex"):
        ExtractorConfig(employee_id="(", asset_tag="x", error_code="y")
