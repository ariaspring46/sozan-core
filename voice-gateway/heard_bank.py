"""One hundred phone sentences and accent-shifted ways they are heard.

The canonical line is what the caller meant. The heard lines are how
Persian phone audio often comes back: Tehran short forms, and the
wreckage Whisper and the line already produced. The holdout line is
kept out of the index so a test can ask if a new garble still lands.
"""

from __future__ import annotations

_SWAPS = (
    ("سوزان", "سودان"),
    ("سوزان", "سوزون"),
    ("فروشگاه", "فوشکا"),
    ("فروشگاه", "فرشکا"),
    ("چیست", "چیه"),
    ("نمی‌شود", "نمیشه"),
    ("نمی‌شود", "نیشه"),
    ("نمی‌خواهم", "نمیخوام"),
    ("نمی‌خوام", "نمیخوام"),
    ("می‌خواهم", "میخوام"),
    ("چطور", "چطوری"),
    ("دایرکت", "دایرک"),
    ("اینستاگرام", "اینستا"),
    ("را ", "رو "),
    ("هستم", "هسم"),
    ("بگو", "بگی"),
    ("پنل", "پنلِ"),
    ("پول", "پولِ"),
    ("رایگان", "رایگانه"),
    ("سلام", "سلم"),
)

CANONICAL: tuple[str, ...] = (
    'سوزان چیست',
    'سوزان چه کار می\u200cکند',
    'سوزان پنل است',
    'سوزان آدم نیست',
    'برای معرفی سوزان زنگ زدی',
    'فروشگاه را از توی چت می\u200cسازی',
    'ساخت فروشگاه پول نمی\u200cخواهد',
    'اول حس فروشگاه را بگو',
    'بعد رنگ را بگو',
    'بعد بنویس بساز',
    'حسش گرم باشد',
    'رنگش سرمه\u200cای باشد',
    'فروشگاه من ساخته نمی\u200cشود',
    'چطور فروشگاه بسازم',
    'ساخت فروشگاه چقدر طول می\u200cکشد',
    'کالا از کپشن پیج می\u200cآید',
    'دایرکت اینستاگرام را نمی\u200cخواند',
    'لینک فروشگاه را بگو',
    'نشانی فروشگاه چیست',
    'دامنه را چطور وصل کنم',
    'کد ورود نمی\u200cآید',
    'پرو چقدر است',
    'پرو برای خواندن دایرکت است',
    'چهارصد و نود هزار تومان',
    'نمی\u200cخواهم بخرم',
    'گران است',
    'وقت ندارم',
    'بعداً زنگ بزن',
    'اشتباه گرفتی',
    'کی هستی',
    'اسمت چیست',
    'حالت چطور است',
    'خوبی',
    'خداحافظ',
    'دوباره بگو',
    'متوجه نشدم',
    'یک لحظه صبر کن',
    'فروشگاه را رایگان می\u200cسازی',
    'برنامه\u200cنویس لازم نیست',
    'از اینستاگرام کالا می\u200cآید',
    'پیج را لازم نیست ببینی',
    'رنگ و دوخت را تعریف نکن',
    'اگر بله بگویم چه می\u200cشود',
    'لینک را در این تماس نفرست',
    'وارد پنل چطور شوم',
    'شماره موبایل برای ورود است',
    'رمز یکبارمصرف کجاست',
    'هرزنامه را نگاه کنم',
    'پیش\u200cنمایش را نمی\u200cبینم',
    'کادر چت بسته شده',
    'استودیو پست می\u200cسازد',
    'تلگرام را چطور وصل کنم',
    'اینستاگرام وصل نمی\u200cشود',
    'انبار کجاست',
    'موجودی را کجا عوض کنم',
    'پرداخت آزمایشی است',
    'درگاه را چطور روشن کنم',
    'اشتراک پرو را چطور بخرم',
    'زرین\u200cپال چیست',
    'سایت بالا نمی\u200cآید',
    'نام فروشگاه را از کجا بگذارم',
    'لوگو را کجا بگذارم',
    'سلام فروشگاه نمی\u200cسازد',
    'بساز را کجا بنویسم',
    'حس و رنگ را نگفتم',
    'چند دقیقه طول می\u200cکشد',
    'وقتی آماده شد کجا ببینم',
    'نشانی سوزان خط کور چیست',
    'اپ سوزان کجاست',
    'دایرکت را چرا نمی\u200cخوانی',
    'پول ساخت چقدر است',
    'رایگان است یا نه',
    'پرو لازم است یا نه',
    'فقط معرفی کن',
    'تبلیغ نکن',
    'فروشگاه آماده داری',
    'نمی\u200cخواهم فروشگاه',
    'مشتری هستم نه فروشنده',
    'پیج اینستاگرام دارم',
    'کپشن قیمت دارد',
    'رنگ لباس را نگو',
    'مدل را نگو',
    'دیدی پیج را',
    'دروغ نگو',
    'کارت نخواه',
    'شماره نپرس',
    'قطع کن',
    'تمام شد',
    'باشه بساز',
    'آره می\u200cخواهم',
    'نه نمی\u200cخواهم',
    'فردا تماس بگیر',
    'الان وقت دارم',
    'بیست ثانیه بگو',
    'سوزان را ساده بگو',
    'یک مثال بزن',
    'حسش گرم باشد و رنگش سرمه\u200cای',
    'همین را می\u200cخواهم',
    'لینک را بعداً بفرست',
    'در دایرکت نفرست',
)


def _heard_forms(text: str) -> list[str]:
    found: list[str] = []
    for src, dst in _SWAPS:
        if src in text:
            found.append(text.replace(src, dst, 1))
    if not found:
        words = text.split()
        if len(words) > 2:
            found.append(" ".join(words[:-1]))
            found.append(words[0] + " " + words[-1])
        else:
            found.append(text + " ه")
            found.append(text[: max(2, len(text) - 1)])
    uniq: list[str] = []
    for item in found:
        if item != text and item not in uniq:
            uniq.append(item)
    return uniq


def should_repair(heard: str, canonical: str, score: float, phrase_min: float = 0.72) -> bool:
    """Map a garbled line only when it is clearly the same sentence.

    A short clear question must stay as heard. «دایرکت چی» is not the
    long complaint about Instagram DMs, even if the vectors sit near it.
    """
    if score < phrase_min:
        return False
    heard_words = heard.split()
    canon_words = canonical.split()
    if heard_words == canon_words:
        return False
    if len(heard_words) > len(canon_words) + 1:
        return False
    content = [word for word in heard_words if len(word) >= 3]
    shared = sum(1 for word in content if word in canon_words)
    outside = len(content) - shared
    if outside >= 2 and score < 0.92:
        return False
    if len(canon_words) == 1 and outside >= 1 and score < 0.92:
        return False
    if len(heard_words) <= 2 and len(canon_words) > len(heard_words) and shared < 2 and score < 0.9:
        return False
    much_longer = len(canon_words) > len(heard_words) + 1
    if shared <= 1 and much_longer and score < 0.88:
        return False
    if shared == 0 and score < 0.86:
        return False
    return True


def heard_rows() -> list[tuple[str, tuple[str, ...], str]]:
    rows: list[tuple[str, tuple[str, ...], str]] = []
    for text in CANONICAL:
        forms = _heard_forms(text)
        train = tuple(forms[:-1] or forms[:1])
        holdout = forms[-1]
        if holdout in train:
            holdout = text[: max(3, len(text) - 2)]
        rows.append((text, train, holdout))
    return rows
