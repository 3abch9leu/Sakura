"""
BillReader - structured fields from a STEG electricity bill (photo or PDF).

Pipeline (all local, nothing is stored or sent to an external service):
  1. PDF with a text layer  -> pdfplumber words (exact, no OCR)
     PDF scan / photo       -> RapidOCR = PaddleOCR PP-OCR models on onnxruntime (French/Latin model,
                               plus the Arabic model when available)
  2. Words are grouped into lines; fields are found from French and Arabic labels next to their values.
  3. Numbers are normalised (decimal comma, thousands separators, "DT"/"TND"/"د.ت", millimes).
  4. Cross-checks (new index - old index = consumption) mark fields as uncertain instead of guessing.
  5. Personal data (name, address, customer / contract / meter numbers) is detected and dropped:
     only the label of what was redacted is returned.

Optional fallback: Qwen2-VL-2B-Instruct (set ROOTCODE_BILL_VLM=1, weights must already be cached).

    python -m rootcode.bill_reader my_bill.jpg
"""
import io
import os
import re
import threading
import time
import unicodedata

import numpy as np

FIELDS = {
    # name: (kind, French/Latin label patterns, Arabic label patterns)
    "index_previous": ("int", [r"anc(ien)?\.?\s*index", r"index\s*anc", r"index\s*pr[ée]c[ée]dent", r"\bancien\b"],
                       [r"المؤشر\s*القديم", r"القراءة\s*السابقة", r"المؤشر\s*السابق"]),
    "index_current": ("int", [r"nouv(el|eau)?\.?\s*index", r"index\s*nouv", r"index\s*actuel", r"\bnouvel\b"],
                      [r"المؤشر\s*الجديد", r"القراءة\s*الحالية", r"المؤشر\s*الحالي"]),
    "consumption_kwh": ("int", [r"consommation", r"\bconso\b", r"qt[ée]\s*consomm", r"quantit[ée]"],
                        [r"الاستهلاك", r"الكمية\s*المستهلكة"]),
    "subscribed_power_kva": ("float", [r"puissance", r"\bkva\b", r"calibre"], [r"القدرة", r"قدرة"]),
    "energy_amount_tnd": ("money", [r"montant\s*(de\s*la\s*)?consommation", r"montant\s*[ée]nergie", r"prix\s*[ée]nergie",
                                    r"[ée]nergie\s*(hors\s*taxe|ht)", r"montant\s*ht\b"],
                          [r"مبلغ\s*الاستهلاك", r"ثمن\s*الطاقة", r"معلوم\s*الاستهلاك"]),
    "fixed_charges_tnd": ("money", [r"redevance", r"frais\s*fixes", r"prime\s*fixe", r"abonnement"],
                          [r"المعاليم\s*القارة", r"معلوم\s*القدرة", r"الاشتراك", r"الإتاوة"]),
    "taxes_tnd": ("money", [r"total\s*taxes", r"montant\s*taxes", r"\btaxes\b", r"\bt\.?v\.?a\.?\b"],
                  [r"الأداءات", r"الأداء\s*على\s*القيمة\s*المضافة", r"الضرائب"]),
    "electricity_total_tnd": ("money", [r"total\s*([ée]lectricit[ée]|[ée]lec)", r"montant\s*[ée]lectricit[ée]"],
                              [r"مجموع\s*الكهرباء", r"جملة\s*الكهرباء"]),
    "total_tnd": ("money", [r"net\s*[àa]\s*payer", r"montant\s*[àa]\s*payer", r"total\s*[àa]\s*payer", r"total\s*ttc",
                            r"montant\s*total"],
                  [r"المبلغ\s*الجملي", r"المبلغ\s*الصافي", r"الصافي\s*للدفع", r"المبلغ\s*المطلوب", r"المجموع"]),
}

PII = {
    "customer_name": [r"\bnom\b", r"\bm(me|lle|r)?\.\s", r"client\s*:", r"الاسم", r"اللقب", r"الحريف"],
    "address": [r"adresse", r"\brue\b", r"\bavenue\b", r"\bav\.", r"\bcit[ée]\b", r"العنوان", r"نهج", r"شارع"],
    "customer_reference": [r"r[ée]f[ée]rence", r"\bref\b", r"code\s*client", r"n[°o]\s*client", r"المرجع", r"مرجع"],
    "contract_number": [r"contrat", r"police", r"العقد"],
    "meter_number": [r"n[°o]\s*compteur", r"compteur\s*n", r"عدد\s*العداد", r"رقم\s*العداد"],
    "phone": [r"t[ée]l[ée]?phone", r"\btel\b", r"الهاتف"],
}

# a label word shared with another field: skip the line when it also carries one of these
EXCLUDE = {
    "consumption_kwh": [r"مبلغ", r"فترة", r"معلوم", r"montant", r"p[ée]riode", r"prix"],
    "subscribed_power_kva": [r"معلوم\s*القدرة", r"redevance"],
    "total_tnd": [r"الكهرباء", r"[ée]lectricit[ée]"],
}

ESTIMATED = [r"estim", r"تقديري", r"تقديرية", r"forfait"]
READING_LABEL = [r"relev", r"lecture", r"type\s*de\s*(relev|lecture)", r"قراءة", r"القراءة"]
ACTUAL = [r"\br[ée]el(le)?\b", r"relev[ée]\s*r[ée]el", r"حقيقي", r"فعلي", r"فعلية"]

DATE_RE = re.compile(r"(?<!\d)(?:(\d{4})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})"      # 2022-10-06 (ISO)
                     r"|(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2}))(?!\d)")  # 06-10-2022, 06/10/22
NUM_RE = re.compile(r"\d{1,3}(?:[  .,']\d{3})+(?:[.,]\d{1,3})?(?!\d)|\d+(?:[.,]\d{1,3})?(?!\d)")


# ---------------------------------------------------------------- number normalisation
def to_arabic_digits(s):
    """Eastern Arabic / Persian digits -> ASCII, and NFKC normalisation."""
    s = unicodedata.normalize("NFKC", s)
    return s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬،", "01234567890123456789.,,"))


def parse_number(raw, kind="money"):
    """
    Returns (value, uncertain). Handles '1 234,567', '1.234,567', '45,320 DT', '45.320', '45 DT 320'.
    TND amounts have 3 decimals (millimes): '1.234' is 1 dinar 234 millimes for money, 1234 for kWh/index.
    """
    s = to_arabic_digits(str(raw)).strip()
    m = re.search(r"(\d+)\s*(?:dt|tnd|d\.t|د\.?ت|دينار)\s*(\d{1,3})\b", s, re.I)
    if m and kind == "money":                       # "45 DT 320" -> 45.320
        return float(f"{m.group(1)}.{m.group(2).rjust(3, '0')}"), False
    m = NUM_RE.search(s)
    if not m:
        return None, True
    t = m.group(0).replace("'", "").replace(" ", " ")
    if kind in ("int",):
        digits = re.sub(r"[\s.,]", "", t)
        return (int(digits) if digits else None), bool(re.search(r"[.,]\d{1,2}$", t))
    t = t.replace(" ", "")
    uncertain = False
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in t:
        parts = t.split(",")
        t = "".join(parts[:-1]) + "." + parts[-1]
    elif t.count(".") > 1:
        parts = t.split(".")
        t = "".join(parts[:-1]) + "." + parts[-1]
    elif "." in t and kind == "float":
        pass
    if kind == "money" and "." not in t and len(t) > 4:
        uncertain = True                             # e.g. "45320" could be millimes printed without separator
    try:
        return float(t), uncertain
    except ValueError:
        return None, True


def parse_date(s):
    m = DATE_RE.search(to_arabic_digits(s))
    if not m:
        return None
    g = m.groups()
    if g[0]:                                   # year first (ISO, also how Arabic bills print it)
        y, mo, d = int(g[0]), int(g[1]), int(g[2])
    else:                                      # day first (Tunisian / French order)
        d, mo, y = int(g[3]), int(g[4]), int(g[5])
    if y < 100:
        y += 2000
    if not (1 <= d <= 31 and 1 <= mo <= 12 and 2000 <= y <= 2100):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


# ---------------------------------------------------------------- input -> words
def _pdf_words(data):
    """Text-layer PDF -> list of (text, x0, y0, x1, y1, page). Empty list for scanned PDFs."""
    import pdfplumber
    words = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        _pdf_words.page0 = (float(pdf.pages[0].width), float(pdf.pages[0].height)) if pdf.pages else (1.0, 1.0)
        for p, page in enumerate(pdf.pages[:4]):
            for w in page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=[]):
                words.append((w["text"], w["x0"], w["top"] + p * 2000, w["x1"], w["bottom"] + p * 2000, p))
    return words


def _pdf_images(data, max_pages=3):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(data)
    out = []
    for i in range(min(len(doc), max_pages)):
        out.append(np.array(doc[i].render(scale=2.5).to_pil().convert("RGB")))
    return out


def _image(data):
    import cv2
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not a readable image (use JPG, PNG or PDF; convert iPhone HEIC photos to JPG)")
    h, w = img.shape[:2]
    s = 2200 / max(h, w)
    if s < 1:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    elif max(h, w) < 1200:                         # small photos: upscale helps the recogniser
        img = cv2.resize(img, None, fx=min(2.0, 1600 / max(h, w)), fy=min(2.0, 1600 / max(h, w)),
                         interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


_OCR = {}
_OCR_LOCK = threading.Lock()
STATUS = {"ocr_engine": None, "arabic_model": None, "last_error": None}


def _threads():
    # onnxruntime's default (all logical cores) is slower on laptops with hyper-threading: cap at 8
    return max(1, min(8, (os.cpu_count() or 4) // 2))


def _engines():
    """Latin (French PP-OCR) engine and, if available, the Arabic PP-OCR recogniser (recognition only:
    it reads the boxes the Latin detector found, so the page is detected once, not twice)."""
    with _OCR_LOCK:
        if "latin" not in _OCR:
            from rapidocr import RapidOCR
            th = {"EngineConfig.onnxruntime.intra_op_num_threads": _threads(),
                  "EngineConfig.onnxruntime.inter_op_num_threads": 1}
            base = {"Global.log_level": "critical", "Global.use_cls": False,   # bills are upright
                    "Det.limit_type": "max", "Det.limit_side_len": 1600, **th}
            # text_score 0: keep every detected box; low-confidence ones (often Arabic) go to the Arabic model
            latin_params = {**base, "Rec.lang_type": "fr", "Global.text_score": 0.0}
            # the default PP-OCRv6 detector misses most Arabic words; the multilingual detector finds them
            try:
                from rapidocr import LangDet, ModelType as _MT, OCRVersion as _OV
                latin_params.update({"Det.ocr_version": _OV.PPOCRV4, "Det.lang_type": LangDet.MULTI,
                                     "Det.model_type": _MT.MOBILE})
            except Exception:
                pass
            _OCR["latin"] = None
            if os.getenv("ROOTCODE_OCR_GPU", "1") != "0":
                # same PP-OCRv6 detector + recogniser, run by PyTorch on the GPU (~1 s per bill instead of 3-9 s)
                try:
                    import torch
                    if torch.cuda.is_available():
                        from rapidocr import EngineType
                        _OCR["latin"] = RapidOCR(params={**latin_params, "Det.engine_type": EngineType.TORCH,
                                                         "Rec.engine_type": EngineType.TORCH,
                                                         "EngineConfig.torch.use_cuda": True})
                        STATUS["ocr_engine"] = "RapidOCR (PaddleOCR PP-OCR models, PyTorch on CUDA)"
                except Exception as e:
                    _OCR["latin"] = None
                    STATUS["last_error"] = f"GPU OCR unavailable, CPU used: {type(e).__name__}: {e}"[:200]
            if _OCR["latin"] is None:
                try:
                    _OCR["latin"] = RapidOCR(params=latin_params)
                except Exception:
                    _OCR["latin"] = RapidOCR(params={"Global.log_level": "error", **th})
                STATUS["ocr_engine"] = "RapidOCR (PaddleOCR PP-OCR models, onnxruntime CPU)"
            try:
                from rapidocr import LangRec, ModelType, OCRVersion
                _OCR["arabic"] = RapidOCR(params={**base, "Rec.lang_type": LangRec.ARABIC,
                                                  "Rec.ocr_version": OCRVersion.PPOCRV5,
                                                  "Rec.model_type": ModelType.MOBILE})._load_rec_model()
                STATUS["arabic_model"] = "loaded"
            except Exception as e:
                _OCR["arabic"] = None
                STATUS["arabic_model"] = f"unavailable: {type(e).__name__}: {e}"[:200]
    return _OCR["latin"], _OCR["arabic"]


def warm_up():
    """Load the models and run them once on a blank page so the first real bill is not slow
    (onnxruntime's first inference in a process is several times slower than the next ones)."""
    t = time.perf_counter()
    try:
        latin, arabic = _engines()
        img = np.full((900, 640, 3), 255, np.uint8)
        import cv2
        for i, txt in enumerate(("STEG Facture 123,456 DT", "Consommation 250 kWh", "Index 01/2025")):
            cv2.putText(img, txt, (30, 120 + 90 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        for _ in range(2):
            _ocr_words(img)
        STATUS["warm"] = round(time.perf_counter() - t, 1)
    except Exception as e:
        STATUS["last_error"] = f"warm-up: {type(e).__name__}: {e}"[:200]


def _ocr_words(img, page=0):
    latin, arabic = _engines()
    try:
        r = latin(img)
    except Exception as e:                       # GPU busy / out of memory: switch to the CPU engine, keep going
        if "CUDA" not in STATUS.get("ocr_engine", ""):
            raise
        from rapidocr import RapidOCR
        STATUS["last_error"] = f"GPU OCR failed, switched to CPU: {type(e).__name__}"[:200]
        with _OCR_LOCK:
            _OCR["latin"] = RapidOCR(params={"Global.log_level": "critical", "Global.use_cls": False,
                                             "Det.limit_type": "max", "Det.limit_side_len": 1600, "Rec.lang_type": "fr",
                                             "Global.text_score": 0.0,
                                             "EngineConfig.onnxruntime.intra_op_num_threads": _threads()})
            STATUS["ocr_engine"] = "RapidOCR (PaddleOCR PP-OCR models, onnxruntime CPU)"
        latin = _OCR["latin"]
        r = latin(img)
    if r is None or r.boxes is None:
        return []
    words, items = [], []
    h, w = img.shape[:2]
    for box, txt, sc in zip(r.boxes, r.txts, r.scores):
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if txt and txt.strip() and sc >= 0.5:
            words.append((txt.strip(), x0, y0 + page * 4000, x1, y1 + page * 4000, page, float(sc), "latin"))
        items.append((x0, y0, x1, y1, txt or "", float(sc)))
    if arabic is None:
        return words

    def crop(x0, y0, x1, y1):
        return img[max(0, int(y0) - 2):min(h, int(y1) + 3), max(0, int(x0) - 2):min(w, int(x1) + 3)]

    def read_arabic(boxes):
        """Arabic recogniser (one batch) -> [(box, text, score)] where it really read Arabic (2+ letters)."""
        boxes = [b_ for b_ in boxes if crop(*b_[:4]).size]
        if not boxes:
            return []
        from rapidocr.ch_ppocr_rec.typings import TextRecInput
        out = arabic(TextRecInput(img=[crop(*b_[:4]) for b_ in boxes]))
        return [(b_, t, sc) for b_, t, sc in zip(boxes, out.txts or (), out.scores or ())
                if t and len(re.findall(r"[\u0600-\u06FF]", t)) >= 2 and sc >= 0.5]

    try:
        # 1. uncertain Latin readings are the usual Arabic suspects (cheap probe, French bills stop here)
        suspects = [it for it in items if it[5] < 0.9 or not it[4]]
        hits = read_arabic(suspects)
        if hits:
            # 2. the page has Arabic: check the remaining boxes without digits (the Latin model reads Arabic words
            #    as confident garbage), then 3. find Arabic lines the neural detector missed
            rest = [it for it in items if it not in suspects and not re.search(r"\d", it[4])]
            hits += read_arabic(rest)
            hits += read_arabic(_missed_lines(img, items))
        for (x0, y0, x1, y1, ltxt, _), txt, sc in hits:
            words = [x for x in words if not (x[7] == "latin" and x[1] == x0 and x[2] == y0 + page * 4000
                                              and not re.search(r"\d", ltxt))]
            same = [x for x in words if x[7] == "latin" and x[1] == x0 and x[2] == y0 + page * 4000]
            if same:
                # one box holds the Arabic label and its number: keep both (Latin digits + Arabic label)
                nums = " ".join(re.findall(r"\d[\d\s.,]*\d|\d", same[0][0]))
                label = re.sub(r"[\d.,\u060C\u066B\u066C]+", " ", txt).strip()
                words = [x for x in words if x is not same[0]]
                txt = f"{nums} {label}".strip()
            words.append((txt.strip(), x0, y0 + page * 4000, x1, y1 + page * 4000, page, float(sc), "arabic"))
    except Exception as e:
        STATUS["arabic_model"] = f"unavailable: {type(e).__name__}: {e}"[:200]
        _OCR["arabic"] = None
    return words


def _missed_lines(img, items):
    """Printed text lines the neural detector did not box (it misses many Arabic words): binarise, smear
    horizontally, keep line-shaped regions that no detected box already covers. Classic CV, no model."""
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    hs = [it[3] - it[1] for it in items if it[3] - it[1] > 6]
    ch = float(np.median(hs)) if hs else 30.0
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, int(ch * 1.1)), max(1, int(ch * 0.25))))
    blob = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, k)
    n, lab, st, _ = cv2.connectedComponentsWithStats(blob)
    covered = np.zeros(g.shape, bool)
    for x0, y0, x1, y1, *_ in items:
        covered[int(y0):int(y1) + 1, int(x0):int(x1) + 1] = True
    out = []
    for i in range(1, n):
        x, y, bw_, bh, area = st[i]
        if not (0.5 * ch <= bh <= 2.2 * ch and bw_ >= 0.8 * ch and bw_ <= 0.8 * g.shape[1]):
            continue
        if covered[y:y + bh, x:x + bw_].mean() > 0.5:
            continue
        out.append((float(x), float(y), float(x + bw_), float(y + bh), "", 0.0))
    return out


def _iou(a, b):
    ix = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    iy = max(0, min(a[4], b[4]) - max(a[2], b[2]))
    inter = ix * iy
    ua = (a[3] - a[1]) * (a[4] - a[2]) + (b[3] - b[1]) * (b[4] - b[2]) - inter
    return inter / ua if ua > 0 else 0


def _lines(words):
    """Group words into reading lines by vertical overlap, left-to-right."""
    words = sorted(words, key=lambda w: ((w[2] + w[4]) / 2, w[1]))
    lines = []
    for w in words:
        cy, h = (w[2] + w[4]) / 2, max(1.0, w[4] - w[2])
        for L in lines:
            if abs(L["cy"] - cy) < 0.55 * max(h, L["h"]) and L["page"] == w[5]:
                L["words"].append(w)
                L["cy"] = (L["cy"] * (len(L["words"]) - 1) + cy) / len(L["words"])
                break
        else:
            lines.append({"cy": cy, "h": h, "page": w[5], "words": [w]})
    is_ar = lambda t: bool(re.search(r"[\u0600-\u06FF]", t))  # noqa: E731
    for L in lines:
        L["words"].sort(key=lambda w: w[1])
        toks, run = [], []
        for w in L["words"]:                      # reverse each run of consecutive Arabic words
            if is_ar(w[0]):
                run.append(w[0])
            else:
                toks += run[::-1] + [w[0]]
                run = []
        toks += run[::-1]
        L["text"] = " ".join(toks)
        L["conf"] = float(np.mean([w[6] if len(w) > 6 else 1.0 for w in L["words"]]))
        L["box"] = (min(w[1] for w in L["words"]), min(w[2] for w in L["words"]),
                    max(w[3] for w in L["words"]), max(w[4] for w in L["words"]))
    return sorted(lines, key=lambda L: L["cy"])


def _union(*boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


# ---------------------------------------------------------------- field extraction
def _match(text, pats):
    return any(re.search(p, text, re.I) for p in pats)


def _value_after_label(line, label_pats, kind):
    """Number located after (French) or before (Arabic, right-to-left) the label on the same line."""
    text = DATE_RE.sub(" ", to_arabic_digits(line["text"]))
    for p in label_pats:
        m = re.search(p, text, re.I)
        if not m:
            continue
        after = text[m.end():]
        before = text[:m.start()]
        arabic_label = bool(re.search(r"[\u0600-\u06FF]", m.group(0)))
        for chunk in ((before, after) if arabic_label else (after, before)):
            nums = list(NUM_RE.finditer(chunk))
            if nums:
                n = nums[0] if chunk is after else nums[-1]
                raw = chunk[n.start(): n.end() + 8]
                val, unc = parse_number(raw, kind)
                if val is not None:
                    return val, unc, raw.strip()
    return None


def extract_fields(lines):
    fields = {k: {"value": None, "status": "missing", "raw": None, "confidence": 0.0} for k in FIELDS}
    redacted = set()
    for i, L in enumerate(lines):
        low = L["text"]
        for key, pats in PII.items():
            if _match(low, pats):
                redacted.add(key)
                L["pii"] = True
        # a line of 7+ digits with no decimal part, no date and no known label is a reference / meter number,
        # even when its label was not read (common on Arabic bills): treat it as personal data
        plain = DATE_RE.sub(" ", to_arabic_digits(low))
        if (not L.get("pii") and len(re.sub(r"\D", "", plain)) >= 7 and not re.search(r"\d[.,]\d", plain)
                and not any(_match(low, v[1] + v[2]) for v in FIELDS.values())):
            redacted.add("customer_reference")
            L["pii"] = True

    for key, (kind, fr, ar) in FIELDS.items():
        for i, L in enumerate(lines):
            if L.get("pii") and key not in ("total_tnd",):
                continue
            if not (_match(L["text"], fr) or _match(L["text"], ar)):
                continue
            if key in EXCLUDE and _match(L["text"], EXCLUDE[key]):
                continue
            hit = _value_after_label(L, fr + ar, kind)
            if hit is None and i + 1 < len(lines):            # value printed under its label
                nxt = lines[i + 1]
                m = NUM_RE.search(to_arabic_digits(nxt["text"]))
                if m and not _match(nxt["text"], [p for v in FIELDS.values() for p in v[1] + v[2]]):
                    val, unc = parse_number(nxt["text"][m.start():m.end() + 8], kind)
                    if val is not None:
                        hit = (val, True, nxt["text"])
                        L = {**L, "box": _union(L["box"], nxt["box"])}
            if hit is None:
                continue
            val, unc, raw = hit
            if kind == "money" and not (0 <= val < 100000):
                continue
            if key == "subscribed_power_kva" and not (0.5 <= val <= 60):
                continue
            fields[key] = {"value": val, "status": "uncertain" if unc or L["conf"] < 0.8 else "found",
                           "raw": raw[:40], "confidence": round(L["conf"], 2), "_box": L["box"], "_page": L["page"]}
            break

    # period: first line holding two dates (du ... au ... / من ... إلى ...)
    for L in lines:
        ds = [parse_date(m.group(0)) for m in DATE_RE.finditer(to_arabic_digits(L["text"]))]
        ds = [d for d in ds if d]
        if len(ds) >= 2 and ds[0] != ds[1]:
            ds = sorted(ds[:2])
            fields["period_start"] = {"value": ds[0], "status": "found", "raw": None, "confidence": round(L["conf"], 2),
                                      "_box": L["box"], "_page": L["page"]}
            fields["period_end"] = {"value": ds[1], "status": "found", "raw": None, "confidence": round(L["conf"], 2),
                                    "_box": L["box"], "_page": L["page"]}
            break
    else:
        fields["period_start"] = {"value": None, "status": "missing", "raw": None, "confidence": 0.0}
        fields["period_end"] = {"value": None, "status": "missing", "raw": None, "confidence": 0.0}

    # reading type
    reading_L = [L for L in lines if _match(L["text"], READING_LABEL)]
    reading_lines = [L["text"] for L in reading_L]
    est = any(_match(t, ESTIMATED) for t in reading_lines)
    act = any(_match(t, ACTUAL) for t in reading_lines)
    if not (est or act):                     # no labelled line: fall back to the whole page
        text_all = " ".join(L["text"] for L in lines)
        est, act = _match(text_all, ESTIMATED), _match(text_all, ACTUAL)
    if est and not act:
        rt = {"value": "estimated", "status": "found"}
    elif act and not est:
        rt = {"value": "actual", "status": "found"}
    elif est and act:
        rt = {"value": None, "status": "uncertain"}
    else:
        rt = {"value": None, "status": "missing"}
    fields["reading_type"] = {**rt, "raw": None, "confidence": 1.0 if rt["status"] == "found" else 0.0}
    hit_L = [L for L in reading_L if _match(L["text"], ESTIMATED + ACTUAL)]
    if hit_L:
        fields["reading_type"].update(_box=hit_L[0]["box"], _page=hit_L[0]["page"])

    # cross-checks
    ip, ic, c = (fields[k]["value"] for k in ("index_previous", "index_current", "consumption_kwh"))
    if ip is not None and ic is not None:
        if ic < ip:
            for k in ("index_previous", "index_current"):
                fields[k]["status"] = "uncertain"
        elif c is None:
            fields["consumption_kwh"] = {"value": ic - ip, "status": "uncertain", "raw": "new - old index",
                                         "confidence": 0.5}
        elif abs((ic - ip) - c) <= 0.5:
            for k in ("index_previous", "index_current", "consumption_kwh"):
                fields[k]["status"] = "found"
        else:
            fields["consumption_kwh"]["status"] = "uncertain"
    return fields, sorted(redacted)


# ---------------------------------------------------------------- optional VLM fallback
def _vlm_available():
    if os.getenv("ROOTCODE_BILL_VLM", "0") != "1":
        return False, "disabled (set ROOTCODE_BILL_VLM=1 to enable the Qwen2-VL-2B fallback)"
    cache = os.getenv("ROOTCODE_HF_CACHE", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "hf_cache")))
    if not os.path.isdir(os.path.join(cache, "models--Qwen--Qwen2-VL-2B-Instruct")):
        return False, "Qwen2-VL-2B-Instruct weights not cached"
    return True, cache


def _vlm_extract(img, missing):
    """Ask Qwen2-VL-2B (local GPU) only for the fields OCR could not find. Values come back uncertain."""
    import json
    import torch
    from PIL import Image
    from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
    ok, cache = _vlm_available()
    if not ok:
        return {}
    model_id = "Qwen/Qwen2-VL-2B-Instruct"
    model = Qwen2VLForConditionalGeneration.from_pretrained(model_id, torch_dtype=torch.float16, device_map="auto",
                                                            cache_dir=cache, local_files_only=True)
    proc = AutoProcessor.from_pretrained(model_id, cache_dir=cache, local_files_only=True)
    q = ("This is a Tunisian STEG electricity bill. Return only JSON with these keys (number or null, "
         "never guess): " + ", ".join(missing))
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": q}]}]
    prompt = proc.apply_chat_template(msgs, add_generation_prompt=True)
    inp = proc(text=[prompt], images=[Image.fromarray(img)], return_tensors="pt").to(model.device)
    out = model.generate(**inp, max_new_tokens=200, do_sample=False)
    txt = proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0]
    m = re.search(r"\{.*\}", txt, re.S)
    del model
    torch.cuda.empty_cache()
    return json.loads(m.group(0)) if m else {}


# ---------------------------------------------------------------- annotated preview
def _preview(data, source, images, lines, fields, max_side=1400):
    """
    Page-1 image for the annotated view, with personal-data lines blurred on the server, plus normalised
    boxes (0-1) for each field. Fields keep only 'box' (public); internal _box/_page keys are removed.
    """
    import base64
    import cv2
    try:
        if source == "pdf_text":
            img = _pdf_images(data, 1)[0]
            pw, ph = getattr(_pdf_words, "page0", (1.0, 1.0))
        else:
            img = images[0]
            ph, pw = img.shape[:2]
    except Exception:
        img, pw, ph = None, 1.0, 1.0

    def norm(b, pad=0.004):
        x0, y0, x1, y1 = b
        return [round(float(max(0.0, x0 / pw - pad)), 4), round(float(max(0.0, y0 / ph - pad)), 4),
                round(float(min(1.0, x1 / pw + pad)), 4), round(float(min(1.0, y1 / ph + pad)), 4)]

    for f in fields.values():
        b, pg = f.pop("_box", None), f.pop("_page", None)
        f["box"] = norm(b) if b is not None and pg == 0 else None
    if img is None:
        return None
    out = img.copy()
    H, W = out.shape[:2]
    pii = [norm(L["box"], 0.006) for L in lines if L.get("pii") and L["page"] == 0]
    for x0, y0, x1, y1 in pii:
        a, b, c, d = int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)
        if c > a and d > b:
            roi = out[b:d, a:c]
            k = max(15, (min(roi.shape[:2]) // 2) | 1)
            out[b:d, a:c] = cv2.GaussianBlur(cv2.resize(cv2.resize(roi, (max(1, roi.shape[1] // 12), max(1, roi.shape[0] // 12))),
                                                        (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_NEAREST), (k, k), 0)
    s = min(1.0, max_side / max(H, W))
    if s < 1:
        out = cv2.resize(out, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
    return {"jpeg_base64": base64.b64encode(buf.tobytes()).decode() if ok else None,
            "width": int(out.shape[1]), "height": int(out.shape[0]), "blurred_regions": len(pii)}


# ---------------------------------------------------------------- entry point
_CACHE = {}            # sha256(file) -> result. Memory only, PII-free results, last 16 bills, 30 min
_CACHE_TTL = 1800


def read_bill(data, filename="", content_type=""):
    """Cached wrapper: the same file uploaded again (retry, language switch, back button) answers instantly."""
    import copy
    import hashlib
    key = hashlib.sha256(data).hexdigest()
    now = time.time()
    for k in [k for k, (ts, _) in _CACHE.items() if now - ts > _CACHE_TTL]:
        _CACHE.pop(k, None)
    if key in _CACHE:
        out = copy.deepcopy(_CACHE[key][1])
        out["cached"] = True
        out["seconds"] = 0.0
        return out
    out = _read_bill(data, filename, content_type)
    if len(_CACHE) >= 16:
        _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)
    _CACHE[key] = (now, copy.deepcopy(out))
    return out


def _read_bill(data, filename="", content_type=""):
    """
    data: bytes of a JPG/PNG/PDF. Returns a JSON-safe dict:
      fields{name: {value, status: found|uncertain|missing, raw, confidence}}, source, redacted[], warnings[]
    Nothing is written to disk; personal data lines are never returned.
    """
    t = time.perf_counter()
    is_pdf = data[:5] == b"%PDF-" or filename.lower().endswith(".pdf") or "pdf" in (content_type or "")
    warnings, source, images = [], None, []
    words = []
    if is_pdf:
        try:
            words = _pdf_words(data)
        except Exception as e:
            raise ValueError(f"unreadable PDF: {e}")
        if len(words) >= 15:
            words = [(w[0], w[1], w[2], w[3], w[4], w[5], 1.0, "pdf") for w in words]
            source = "pdf_text"
        else:
            images = _pdf_images(data)
            source = "ocr"
    else:
        images = [_image(data)]
        source = "ocr"
    if images:
        for p, img in enumerate(images):
            words += _ocr_words(img, p)
    if not words:
        raise ValueError("no text found: retake the photo flat, in good light, with the whole bill visible")

    lines = _lines(words)
    fields, redacted = extract_fields(lines)
    preview = _preview(data, source, images, lines, fields)
    missing = [k for k, v in fields.items() if v["status"] == "missing" and k not in ("electricity_total_tnd",)]

    vlm_note = None
    if images and len(missing) >= 3:
        ok, why = _vlm_available()
        if ok:
            try:
                for k, v in _vlm_extract(images[0], missing).items():
                    if k in fields and fields[k]["status"] == "missing" and isinstance(v, (int, float)):
                        fields[k] = {"value": v, "status": "uncertain", "raw": "Qwen2-VL", "confidence": 0.3}
                vlm_note = "Qwen2-VL-2B fallback used for missing fields (marked uncertain)"
            except Exception as e:
                vlm_note = f"Qwen2-VL fallback failed: {type(e).__name__}"
        else:
            vlm_note = f"VLM fallback {why}"

    found = sum(v["status"] == "found" for v in fields.values())
    if found == 0:
        warnings.append("We could not recognise any bill field. Is this a STEG electricity bill? "
                        "You can still type the values by hand.")
    if fields["reading_type"]["status"] != "found":
        warnings.append("We could not tell whether the meter reading is actual or estimated: please choose.")
    has_arabic = any(re.search(r"[؀-ۿ]", L["text"]) for L in lines)
    return {
        "fields": fields,
        "preview": preview,
        "source": source,
        "engine": STATUS["ocr_engine"] if source == "ocr" else "pdfplumber (text layer)",
        "arabic_text_detected": has_arabic,
        "arabic_model": STATUS["arabic_model"],
        "redacted": redacted,
        "privacy": "Processed in memory on this server; the file is not stored and personal details are not returned.",
        "vlm": vlm_note,
        "warnings": warnings,
        "n_lines": len(lines),
        "seconds": round(time.perf_counter() - t, 2),
    }


if __name__ == "__main__":
    import json
    import sys
    with open(sys.argv[1], "rb") as f:
        r = read_bill(f.read(), sys.argv[1])
    print(json.dumps(r, indent=2, ensure_ascii=False))
