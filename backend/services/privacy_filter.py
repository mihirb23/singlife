# privacy_filter.py — PII masking layer before LLM calls
# rules engine processes RAW data (needs real NRIC to match).
# only the LLM-facing data gets sanitized through this filter.
# keeps a mapping so we can restore PII in the final output for ops staff.

import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# what to mask — toggle each type on/off
MASK_CONFIG = {
    "nric": True,        # Singapore NRIC/FIN (S/T/F/G + 7 digits + letter)
    "email": True,       # email addresses
    "phone": True,       # 8+ digit phone numbers
    "credit_card": True, # 13-19 digit card numbers
    "name_fields": True, # known name fields in structured data
    "address": True,     # address fields in structured data
}

# fields that contain names (case-insensitive key matching)
NAME_FIELD_KEYS = {
    "customer_name", "client_name", "name", "full_name", "surname",
    "given_name", "sub_surname", "sub_given_name", "l400_surname",
    "l400_given_name", "curr_surname", "curr_givname", "sub_givname",
    "cpf_holder_name", "cardholder_name",
}

# fields that contain addresses
ADDRESS_FIELD_KEYS = {
    "address", "residential_address", "correspondence_address",
    "cltaddr01", "cltaddr02", "cltaddr03", "cltaddr04", "cltaddr05",
    "l400_address", "l400_address_line1", "l400_address_line2",
    "l400_address_line3", "l400_address_line4", "l400_address_line5",
    "street_name", "block", "building_name",
}

# regex patterns
NRIC_PATTERN = re.compile(r'[STFG]\d{7}[A-Z]', re.IGNORECASE)
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_PATTERN = re.compile(r'\b[689]\d{7}\b')  # SG phone: starts with 6/8/9, 8 digits
CREDIT_CARD_PATTERN = re.compile(r'\b\d{13,19}\b')


class PrivacyFilter:
    """masks PII before sending data to the LLM.
    keeps a restore map so ops staff can see original values in output."""

    def __init__(self):
        self.pii_map = {}  # masked_value -> original_value
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"[{prefix}_{self._counter}]"

    def _mask_nric(self, nric: str) -> str:
        """S8483123I -> S****123I"""
        if not NRIC_PATTERN.match(nric):
            return nric
        masked = f"{nric[0]}****{nric[5:]}"
        self.pii_map[masked] = nric
        return masked

    def _mask_email(self, email: str) -> str:
        """john.doe@email.com -> j***@email.com"""
        at_idx = email.find('@')
        if at_idx <= 0:
            return email
        masked = f"{email[0]}***{email[at_idx:]}"
        self.pii_map[masked] = email
        return masked

    def _mask_phone(self, phone: str) -> str:
        """98765432 -> 987***32"""
        if len(phone) < 8:
            return phone
        masked = f"{phone[:3]}***{phone[-2:]}"
        self.pii_map[masked] = phone
        return masked

    def _mask_name(self, name: str) -> str:
        """Replace with placeholder"""
        if not name or name.strip() in ('', '-', 'None', 'null'):
            return name
        placeholder = self._next_id("NAME")
        self.pii_map[placeholder] = name
        return placeholder

    def _mask_address(self, addr: str) -> str:
        """Replace with placeholder, keep postcode if present"""
        if not addr or addr.strip() in ('', '-', 'None', 'null'):
            return addr
        # try to extract postcode (6 digits for SG)
        postcode_match = re.search(r'\b\d{6}\b', str(addr))
        postcode = f" (postcode: {postcode_match.group()})" if postcode_match else ""
        placeholder = f"[MASKED_ADDRESS{postcode}]"
        self.pii_map[placeholder] = addr
        return placeholder

    def sanitize_text(self, text: str) -> str:
        """mask PII patterns in free text (for RAG context, prompts, etc.)"""
        if not text or not isinstance(text, str):
            return text

        result = text

        if MASK_CONFIG.get("nric"):
            for match in NRIC_PATTERN.findall(result):
                result = result.replace(match, self._mask_nric(match))

        if MASK_CONFIG.get("email"):
            for match in EMAIL_PATTERN.findall(result):
                result = result.replace(match, self._mask_email(match))

        if MASK_CONFIG.get("phone"):
            for match in PHONE_PATTERN.findall(result):
                result = result.replace(match, self._mask_phone(match))

        if MASK_CONFIG.get("credit_card"):
            for match in CREDIT_CARD_PATTERN.findall(result):
                if len(match) >= 13:
                    masked = f"{match[:4]}****{match[-4:]}"
                    self.pii_map[masked] = match
                    result = result.replace(match, masked)

        return result

    def sanitize_dict(self, data: dict) -> dict:
        """mask PII in structured data (dicts). recursive for nested dicts/lists."""
        if not isinstance(data, dict):
            return data

        sanitized = {}
        for key, value in data.items():
            key_lower = key.lower()

            if isinstance(value, dict):
                sanitized[key] = self.sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self.sanitize_dict(v) if isinstance(v, dict)
                    else self.sanitize_text(str(v)) if isinstance(v, str)
                    else v
                    for v in value
                ]
            elif isinstance(value, str):
                # check if this is a known PII field
                if MASK_CONFIG.get("name_fields") and key_lower in NAME_FIELD_KEYS:
                    sanitized[key] = self._mask_name(value)
                elif MASK_CONFIG.get("address") and key_lower in ADDRESS_FIELD_KEYS:
                    sanitized[key] = self._mask_address(value)
                else:
                    # general text sanitization (catches NRIC, email, phone in any field)
                    sanitized[key] = self.sanitize_text(value)
            else:
                sanitized[key] = value

        return sanitized

    def sanitize_for_llm(self, data) -> object:
        """main entry point — sanitize any data type before sending to LLM"""
        if isinstance(data, dict):
            return self.sanitize_dict(data)
        elif isinstance(data, str):
            return self.sanitize_text(data)
        elif isinstance(data, list):
            return [self.sanitize_for_llm(item) for item in data]
        return data

    def restore_pii(self, text: str) -> str:
        """restore masked values in output text so ops staff can see originals"""
        if not text:
            return text
        result = text
        for masked, original in self.pii_map.items():
            result = result.replace(masked, original)
        return result

    def get_mask_log(self) -> list:
        """return what was masked (types only, not values) for audit"""
        log = []
        for masked in self.pii_map:
            if masked.startswith('[NAME'):
                log.append({"type": "name", "masked_as": masked})
            elif masked.startswith('[MASKED_ADDRESS'):
                log.append({"type": "address", "masked_as": masked})
            elif '****' in masked and '@' in masked:
                log.append({"type": "email", "masked_as": masked})
            elif NRIC_PATTERN.match(masked.replace('*', '0')):
                log.append({"type": "nric", "masked_as": masked})
            else:
                log.append({"type": "other", "masked_as": masked})
        return log

    def reset(self):
        """clear the PII map between requests"""
        self.pii_map = {}
        self._counter = 0
