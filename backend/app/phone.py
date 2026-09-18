import re

IRAN_MOBILE = re.compile(r"^09\d{9}$")
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_phone(raw: str) -> str:
    mapped = (raw or "").translate(_DIGIT_MAP)
    digits = re.sub(r"\D", "", mapped)
    if digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    if not IRAN_MOBILE.match(digits):
        raise ValueError("شماره موبایل نامعتبر است")
    return digits
