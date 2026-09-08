from __future__ import annotations

import phonenumbers
from phonenumbers import carrier, geocoder, timezone

from moriarty.domain.models import PhoneAnalysis


class PhoneNumberParseError(ValueError):
    """Raised when a phone number cannot be parsed."""


class PhoneNumbersProvider:
    """Offline phone metadata provider backed by Google's libphonenumber data."""

    @property
    def name(self) -> str:
        return "phonenumbers"

    def analyze(
        self, raw_number: str, default_region: str | None = None
    ) -> PhoneAnalysis:
        cleaned = raw_number.strip()
        if not cleaned:
            raise PhoneNumberParseError("Phone number cannot be empty.")

        region = default_region.upper() if default_region else None
        try:
            parsed = phonenumbers.parse(cleaned, region)
        except phonenumbers.NumberParseException as exc:
            raise PhoneNumberParseError(str(exc)) from exc

        kind=phonenumbers.number_type(parsed)
        names={
            phonenumbers.PhoneNumberType.FIXED_LINE:"fixed_line",phonenumbers.PhoneNumberType.MOBILE:"mobile",
            phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE:"fixed_line_or_mobile",phonenumbers.PhoneNumberType.TOLL_FREE:"toll_free",
            phonenumbers.PhoneNumberType.PREMIUM_RATE:"premium_rate",phonenumbers.PhoneNumberType.SHARED_COST:"shared_cost",
            phonenumbers.PhoneNumberType.VOIP:"voip",phonenumbers.PhoneNumberType.PERSONAL_NUMBER:"personal_number",
            phonenumbers.PhoneNumberType.PAGER:"pager",phonenumbers.PhoneNumberType.UAN:"uan",phonenumbers.PhoneNumberType.VOICEMAIL:"voicemail",
        }
        ndc_length=phonenumbers.length_of_national_destination_code(parsed)
        national=str(phonenumbers.national_significant_number(parsed));ndc=national[:ndc_length] if ndc_length else ""
        return PhoneAnalysis(
            input_number=raw_number,
            e164=phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            ),
            is_possible=phonenumbers.is_possible_number(parsed),
            is_valid=phonenumbers.is_valid_number(parsed),
            region_code=phonenumbers.region_code_for_number(parsed),
            region_description=geocoder.description_for_number(parsed, "en"),
            country_code=parsed.country_code,
            carrier=carrier.name_for_number(parsed, "en"),
            timezones=tuple(timezone.time_zones_for_number(parsed)),
            number_type=names.get(kind,"unknown"),
            national_format=phonenumbers.format_number(parsed,phonenumbers.PhoneNumberFormat.NATIONAL),
            international_format=phonenumbers.format_number(parsed,phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            rfc3966=phonenumbers.format_number(parsed,phonenumbers.PhoneNumberFormat.RFC3966),
            national_destination_code=ndc,subscriber_number=national[ndc_length:] if ndc_length else national,
            is_mobile=kind in {phonenumbers.PhoneNumberType.MOBILE,phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE},
            is_fixed_line=kind in {phonenumbers.PhoneNumberType.FIXED_LINE,phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE},
            is_voip=kind==phonenumbers.PhoneNumberType.VOIP,is_toll_free=kind==phonenumbers.PhoneNumberType.TOLL_FREE,
            is_premium_rate=kind==phonenumbers.PhoneNumberType.PREMIUM_RATE,is_shared_cost=kind==phonenumbers.PhoneNumberType.SHARED_COST,
            is_personal_number=kind==phonenumbers.PhoneNumberType.PERSONAL_NUMBER,
        )
