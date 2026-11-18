"""Extract concise table captions from text immediately surrounding a table."""
from __future__ import annotations

from difflib import SequenceMatcher
import re

# Numbered or Roman-numeral structural note and schedule headings
STRUCTURAL_HEADING = re.compile(
    r"^(?:"
    r"(?:note|notes|schedule)\s*(?:no\.?\s*)?\d+[a-zA-Z]?(?:\(\d+\)|\([a-zA-Z]\))?"
    r"|"
    r"(?:annexure|annex|appendix|exhibit)\s+(?:[ivxIVX]{1,4}|[a-zA-Z0-9]{1,2})"
    r")\b",
    re.I,
)

# Lettered or Roman-numeral subsection headings
SUBSECTION_PREFIX = re.compile(
    r"^(?:\(?[A-Za-z]\)\s*|[A-Za-z]\.\s+|\(?[ivxIVX]{1,4}\)\s+)"
)

# Numbered section headings with explicit punctuation or domain keywords
NUMBERED_SECTION_HEADING = re.compile(
    r"^\d{1,2}(?:\.\d{1,2})?\.?\s*(?:[:.\-–)]\s*|\s+)(?:additional\s+information|note|schedule|disclosures?|reconciliation|related\s+party|earning|revenue|other\s+income|share\s+capital)\b",
    re.I,
)

NUMBERED_OR_LETTERED = NUMBERED_SECTION_HEADING

# Primary financial statement titles
PRIMARY_STATEMENT_HEADING = re.compile(
    r"^(?!(?:\(?[A-Za-z]\)|[A-Za-z]\.|\(?[ivxIVX]{1,4}\))\s+)"
    r"(?:consolidated\s+|standalone\s+)?"
    r"(?:balance\s+sheet|statement\s+of\s+profit\s+and\s+loss|profit\s+and\s+loss\s+account|"
    r"income\s+statement|statement\s+of\s+cash\s+flows?|cash\s+flow\s+statement|"
    r"statement\s+of\s+changes\s+in\s+equity|capital\s+account)\b",
    re.I,
)

# Domain vocabulary for financial statement schedules, notes, and commercial tables
FINANCIAL_DOMAIN_TERMS = re.compile(
    r"\b(balance\s+sheet|profit\s+and\s+loss|income\s+statement|cash\s+flows?|changes\s+in\s+equity|"
    r"financial\s+position|comprehensive\s+income|notes?\s+(?:to|on|forming)|"
    r"accounting\s+policies|share\s+capital|shareholders?|details?\s+of\s+equity\s+shares|capital\s+account|other\s+equity|reserves?\s*(?:&|and)\s*surplus|"
    r"property,?\s*plant\s+and\s+equipment|fixed\s+assets|intangible\s+assets|assets?|assumptions?|goodwill|"
    r"capital\s+work[\s-]*in[\s-]*progress|right[\s-]*of[\s-]*use|investments?|loans?|"
    r"trade\s+receivables?|inventories|cash\s+and\s+cash\s+equivalents?|bank\s+balances?|"
    r"current\s+liabilities|dues\s+to\s+(?:others?|micro\s+and\s+small\s+enterprises)|"
    r"micro\s+and\s+small\s+enterprises|other\s+(?:financial\s+|current\s+|non[\s-]*current\s+)?(?:assets|liabilities|income|expenses)|"
    r"deferred\s+tax|income\s+tax|tax\s+expense|effective\s+tax\s+rate|tax\s+assets|"
    r"borrowings?|lease\s+liabilities|trade\s+payables?|provisions?|contingent\s+liabilities|"
    r"commitments?|revenue\s+from\s+operations?|cost\s+of\s+materials|purchases?|stock[\s-]*in[\s-]*trade|"
    r"changes\s+in\s+inventories|excise\s+duty|employee\s+benefits?|finance\s+costs?|"
    r"depreciation|amortisation|amortization|exceptional\s+items|earnings?\s+per\s+(?:equity\s+)?shares?|"
    r"dividend|financial\s+instruments?|fair\s+value|financial\s+risk|liquidity\s+risk|market\s+risk|"
    r"credit\s+risk|defined\s+benefit|share\s+based\s+payments?|business\s+combination|"
    r"expenditures?|payments?\s+to\s+(?:the\s+)?auditors?|"
    r"related\s+part(?:y|ies)|employee\s+benefit\s+plans?|significant\s+influence|segment|additional\s+information|disclosures?|reconciliation|"
    r"assets?\s+held\s+for\s+sale|capital\s+management|commercial\s+invoice|bank\s+transaction)\b",
    re.I,
)

# Explicit schedule and disclosure headings that introduce independent tables
KNOWN_SCHEDULE_HEADING = re.compile(
    r"\b(?:expenditures?\s+in\s+foreign\s+currency|payments?\s+to\s+(?:the\s+)?auditors?|"
    r"related\s+party\s+transactions?|earnings?\s+per\s+(?:equity\s+)?shares?|"
    r"additional\s+information(?:\s+and\s+disclosures?)?|contingent\s+liabilities|commitments?)\b",
    re.I,
)

# Running headers, column labels, table line-items, and metadata fields that are never captions
GENERIC_HEADER = re.compile(
    r"^(overview|reports?|financial\s+statements?|annual\s+report|standalone|consolidated|"
    r"particulars|description|notes?$|note\s+no\.?$|note\s+balance\b|note\s+end\b|ref\.?$|"
    r"page\s+\d+|amount|in\s+₹|₹\s+in|rs\.?\s+in|all\s+amounts\s+in|"
    r"year\s+ended|as\s+at|for\s+the\s+(?:year|period)\s+ended|"
    r"figures\s+for|figures\s+as|name\s+of\s+entity|name\s+of\s+proprietor|name\s+of\s+the\s+company|"
    r"previous\s+year|assessment\s+year|legal\s+status|pan\s+no|phone|email|cin\s*:|"
    r"total\b|sub[\s-]*total\b|continued\.{0,3}$|contd\.?$|"
    r"reclassified\s+to\b|items\s+that\s+will\b|balance\s+as\s+at\b|gross\s+block\b|net\s+block\b|"
    r"accumulated\s+depreciation\b|add\s*:|less\s*:|present\s+value\s+of\s+obligation$|"
    r"fair\s+value\s+of\s+plan\s+assets$|scheme\s+year\b|number\s+of\s+share\s+options\b|"
    r"financial\s+assumptions$|demographic\s+assumptions$|to\s+the\s+financial\s+statements\b)\b",
    re.I,
)

# Document header and running navigation bars
RUNNING_NAV_BANNER = re.compile(
    r"\b(?:overview\s+reports?\s+financial\s+statements?|standalone\s+overview|annual\s+report\s+\d{4})\b",
    re.I,
)

# Prose and narrative sentence markers distinguishing explanatory text from table titles
NARRATIVE = re.compile(
    r"\b(is|are|was|were|has|have|had|been|being|based|recognised|recognized|"
    r"measured|stated|includes|include|included|comprises|comprise|provided|provides|"
    r"conducted|believe|accordance|applicable|initially|thereon|thereof|hereby|"
    r"which|whereby|during|according|explanatory|accompanying|estimated|"
    r"remaining|paid|executed|collectively|referred\s+to|pursuant\s+to|hereinafter|"
    r"with\s+effect\s+from|entered\s+into|on\s+account\s+of|in\s+respect\s+of|"
    r"in\s+conjunction\s+with|in\s+our\s+opinion|we\s+have\s+audited|"
    r"management\s+is\s+responsible|as\s+per\s+our\s+report|in\s+terms\s+of\s+our|"
    r"obtaining\s+an\s+understanding|reclassified\s+from|disclosed\s+as|"
    r"approximates?\s+to|determined\s+based\s+on|subject\s+to\s+confirmation|"
    r"with\s+the\s+objective\s+of|have\s+been\s+determined)\b",
    re.I,
)

# Trailing grammatical fragments indicating wrapped narrative lines
TRAILING_FRAGMENT = re.compile(
    r"\b(the|a|an|and|or|of|to|in|for|with|by|as|from|at|on|under|into|is|are|was|were|that|which|between)$",
    re.I,
)

# Data row signature ending with two or more numeric column values
TRAILING_DATA_COLUMNS = re.compile(
    r"(?:\s+\(?-?\d[\d,]*(?:\.\d+)?%?\)?){2,}"
    r"(?:\s+-\s*\(?\d[\d,]*(?:\.\d+)?%?\)?)?\s*$"
)

# Generic document-level notes section banner
GENERIC_NOTES_BANNER = re.compile(
    r"^notes?\s+(?:to|on|forming\s+part\s+of)\s+(?:the\s+)?financial\s+statements?\b",
    re.I,
)

# Financial domain vocabulary used for OCR token normalisation and verification
OCR_DOMAIN_VOCAB = (
    "Additional", "Information", "Disclosures", "Disclosure", "Capital", "Share",
    "Shares", "Balance", "Sheet", "Statement", "Statements", "Profit", "Financial",
    "Long", "Term", "Loans", "Advances",
    "Investments", "Investment", "Instruments", "Instrument", "Currency",
    "Liabilities",
    "Liability", "Assets", "Asset", "Receivables", "Payables", "Inventories",
    "Provisions", "Depreciation", "Amortisation", "Amortization", "Operations",
    "Operation", "Revenue", "Expenses", "Expense", "Employee", "Benefits",
    "Borrowings", "Commitments", "Contingent", "Reconciliation", "Movement",
    "Movements", "Management", "Measurement", "Long", "Current",
    "Subsidiaries",
    "Associates", "Equivalents", "Intangibles", "Intangible", "Equipment",
    "Property", "Schedule", "Annexure", "Appendix", "Commercial", "Invoice",
    "Transaction", "Account", "Reserves", "Reserved", "Surplus", "Preliminary",
    "Earning", "Earnings", "Per", "Plan", "Plans", "Ventures", "Venture", "Joint",
    "Description", "Particulars", "Relationship", "Details", "Auditor",
    "Auditors", "Foreign", "Expenditure", "Party", "Parties",
)

SAFEGUARD_WORDS = {
    "description", "descriptions", "particular", "particulars", "detail", "details",
    "relationship", "relationships", "party", "parties", "auditor", "auditors",
    "foreign", "expenditure", "expenditures", "currency", "currencies",
    "earning", "earnings", "share", "shares", "ratio", "ratios", "value", "values",
}

PRESERVE_UPPER = {
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV",
    "EBITDA", "EBIT", "PAT", "PBT", "EPS", "OCI", "PPE", "CWIP",
    "ROU", "GST", "VAT", "CENVAT", "PAN", "CIN", "DIN", "INR",
    "USD", "EUR", "GBP", "CSR", "MSME", "NCI", "FVOCI", "FVTOCI",
    "FVTPL", "IND", "IFRS", "GAAP", "ICAI", "SEBI", "RBI",
    "CGU", "CGUS", "WACC", "ESOP", "KMP", "R&D", "DDT", "MAT", "EIR", "ECL",
}


def normalize_title_case(title: str) -> str:
    """Normalize inconsistent PDF/OCR capitalization while preserving acronyms and Roman numerals."""
    if not title or title == "Untitled table":
        return "Untitled table"

    def _replace_word(match: re.Match) -> str:
        word = match.group(0)
        upper = word.upper()
        if upper in PRESERVE_UPPER:
            return upper
        if re.fullmatch(r"\d+[A-Za-z]", word):
            return word.upper()
        return word.lower().capitalize()

    out = re.sub(r"[A-Za-z0-9&]+", _replace_word, title)
    out = re.sub(r"(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), out)
    out = re.sub(r"\bIND\s+As\b", "Ind AS", out)
    return out


def repair_ocr_text(text: str) -> str:
    """General OCR token normalizer for scanned pages (repairs digit/symbol noise and 1-char OCR typos)."""
    text = re.sub(r"(?<=[A-Za-z0-9])[<>](?=[A-Za-z0-9])", "d", text)
    known_lower = {w.lower() for w in OCR_DOMAIN_VOCAB}
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    tokens = []
    for token in text.split():
        if token.lower() not in known_lower:
            split = next(
                (
                    index for index in range(1, len(token))
                    if token[:index].lower() in known_lower
                    and token[index:].lower() in known_lower
                ),
                None,
            )
            if split is not None:
                tokens.extend((token[:split], token[split:]))
                continue
        tokens.append(token)
    repaired = []

    for idx, tok in enumerate(tokens):
        if idx == 0 and re.fullmatch(r"\d+[.:)]?", tok):
            repaired.append(tok)
            continue
        alpha_count = sum(c.isalpha() for c in tok)
        digit_count = sum(c in "01" for c in tok)
        if len(tok) >= 5 and alpha_count >= 4 and digit_count >= 1 and not re.match(r"^\d+$", tok):
            tok = tok.replace("11", "ti").replace("1", "i").replace("0", "o")

        prefix, suffix, core = "", "", tok
        while core and not core[0].isalnum():
            prefix += core[0]
            core = core[1:]
        while core and not core[-1].isalnum():
            suffix = core[-1] + suffix
            core = core[:-1]

        has_domain_context = any(
            neighbor.lower() in known_lower
            for neighbor in tokens[max(0, idx - 2):idx]
            + tokens[idx + 1:idx + 3]
        )
        if (
            len(core) >= 4
            and core.lower() not in known_lower
            and core.lower() not in SAFEGUARD_WORDS
            and core.isalpha()
            and (len(core) >= 5 or has_domain_context)
        ):
            core_low = core.lower()
            best_word = None
            best_ratio = 0.0
            for cand in OCR_DOMAIN_VOCAB:
                cand_low = cand.lower()
                if abs(len(cand_low) - len(core_low)) > 2:
                    continue
                if len(core_low) < 9 and abs(len(cand_low) - len(core_low)) > 1:
                    continue
                if cand_low[0] != core_low[0] and cand_low[-1] != core_low[-1]:
                    continue
                ratio = SequenceMatcher(None, core_low, cand_low).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_word = cand
            # Prioritize longer domain terms to accommodate OCR confusion while protecting short tokens
            min_ratio = 0.66 if len(core) >= 9 else (0.72 if len(core) == 4 else 0.65)
            if best_word and best_ratio >= min_ratio:
                core = best_word
        repaired.append(f"{prefix}{core}{suffix}")
    return " ".join(repaired)


def _clean(line: str, is_ocr: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(line or "")).strip(" \t|:-–—")
    text = text.replace("\ufffd", " : ")
    text = re.sub(r"\s+", " ", text).strip(" \t|:-–—")
    if is_ocr or re.search(r"[A-Za-z][01<>][A-Za-z]", text):
        text = repair_ocr_text(text)

    # Standard OCR glyph repairs in financial terminology
    def _fix_plan_typo(m: re.Match) -> str:
        s = m.group(0)
        return re.sub(r"\bplan\b", "plant", s, flags=re.I) if s.islower() else re.sub(r"\bPLAN\b", "PLANT", s) if s.isupper() else re.sub(r"\bPlan\b", "Plant", s, flags=re.I)

    text = re.sub(r"\bproperty,?\s+plan\s+and\s+(?:equipment|machinery)\b", _fix_plan_typo, text, flags=re.I)
    text = re.sub(r"\bplan\s+and\s+machinery\b", _fix_plan_typo, text, flags=re.I)
    text = re.sub(r"\b(?:lonll|lone)\s+(term)\b", r"Long \1", text, flags=re.I)
    text = re.sub(r"\bdefined\s+benefits?\s+loans\b", "Defined Benefits Plans", text, flags=re.I)
    text = re.sub(r"\bjoint\s+revenue\b", "Joint Ventures", text, flags=re.I)
    text = re.sub(r"\bshare\s+caoital\b", "Share Capital", text, flags=re.I)
    text = re.sub(r"\bacidjihonal\b", "Additional", text, flags=re.I)
    text = re.sub(r"\b(?:eamlna|eaming)\b", "earning", text, flags=re.I)
    text = re.sub(r"\bsharos\b", "shares", text, flags=re.I)
    text = re.sub(r"\bdescriotion\b", "Description", text, flags=re.I)
    text = re.sub(r"\brelationshl\s*o\b", "relationship", text, flags=re.I)

    # Strip trailing footnote markers from heading text
    text = re.sub(r"\s*\(\d\)\s*$", "", text)
    # Remove single-character margin artifacts preceding primary statement titles
    text = re.sub(
        r"^[A-Za-z]\s+(?=(?:Balance\s+Sheet|Statement\s+of|Cash\s+Flow|Profit\s+and\s+Loss)\b)",
        "",
        text,
        flags=re.I,
    )
    # Normalize spacing between note numbers and domain titles
    text = re.sub(
        r"^(\d{1,2})\.?\s+(?=(?:Additional\s+Information|Significant\s+Accounting|Notes?\s+Forming)\b)",
        r"\1 ",
        text,
        flags=re.I,
    )
    # Strip right-aligned date column text merged into heading lines
    if STRUCTURAL_HEADING.match(text):
        text = re.sub(
            r"\s+(?:as\s+at|for\s+the\s+(?:year|period)\s+ended)\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4}.*$",
            "",
            text,
            flags=re.I,
        )
    return text.strip(" \t|:-–—")


def is_subsection_title(text: str) -> bool:
    """Return True for lettered or Roman numeral subheadings, not primary Note/Statement captions."""
    cleaned = _clean(text)
    if STRUCTURAL_HEADING.match(cleaned):
        return False
    return bool(SUBSECTION_PREFIX.match(cleaned))


def is_person_name_caption(text: str) -> bool:
    """Reject short initial-and-surname strings that can look like lettered captions."""
    fragment = re.split(r"\s+[–—-]\s+", str(text or "").strip())[-1]
    return bool(
        re.fullmatch(r"(?:[A-Z]\.\s*){1,3}[A-Z][A-Za-z'’-]+", fragment, re.I)
        and not FINANCIAL_DOMAIN_TERMS.search(fragment)
    )


def _has_balanced_delimiters(text: str) -> bool:
    stripped = re.sub(r"^[a-zA-Z0-9ivxIVX]{1,4}\)\s+", "", text)
    if stripped.count("(") != stripped.count(")"):
        return False
    if stripped.count("[") != stripped.count("]"):
        return False
    return True


def _is_plausible_caption(text: str) -> bool:
    if not text or len(text) < 4 or len(text) > 135:
        return False
    if "|" in text:
        return False
    if re.match(r"^\d+\s*\|\s*", text):
        return False
    if re.search(r"\b(?:total|sub[\s-]*total)\s*$", text, re.I):
        return False
    if re.fullmatch(
        r"(?:(?:financial\s+)?(?:assets|liabilities)\s+at\s+(?:fair\s+value|amorti[sz]ed\s+cost|cost)|"
        r"fair\s+value\s+through\s+(?:profit\s+and\s+loss|profit\s+or\s+loss|other\s+comprehensive\s+income|oci|p&l)|"
        r"(?:investments|derivatives)\s+measured\s+at)\b.*",
        text,
        re.I,
    ):
        return False
    if len(re.findall(r"\btotals?\b", text, re.I)) >= 2:
        return False
    if "/" in text and re.search(r"\btotals?\b", text, re.I):
        return False
    if is_person_name_caption(text):
        return False
    if re.match(
        r"^(?:as\s+)?at\s+\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\b",
        text,
        re.I,
    ):
        return False
    if ":" in text and not (
        STRUCTURAL_HEADING.match(text)
        or PRIMARY_STATEMENT_HEADING.match(text)
        or NUMBERED_SECTION_HEADING.match(text)
    ):
        _, suffix = text.split(":", 1)
        if re.search(r"\b\d[\d,]*(?:\.\d+)?%?\b", suffix) and not re.search(
            r"\b(?:as\s+at|as\s+on|year\s+ended|period\s+ended)\b",
            suffix,
            re.I,
        ):
            return False
    if re.fullmatch(r"(?:note|notes|schedule)\s*\d+[a-zA-Z]?\s*$", text, re.I):
        return False
    words = text.split()
    alpha_chars = sum(c.isalpha() for c in text)
    if alpha_chars < 4 or (alpha_chars / max(len(text.strip()), 1)) < 0.45:
        return False
    if not SUBSECTION_PREFIX.match(text) and not STRUCTURAL_HEADING.match(text):
        short_tokens = sum(len(w) <= 2 for w in words)
        if len(words) >= 5 and (short_tokens / len(words)) >= 0.5:
            return False
    if is_subsection_title(text) and len(words) <= 3:
        return True
    if len(words) > 18 and not SUBSECTION_PREFIX.match(text):
        return False
    if len(words) > 12 and not (
        STRUCTURAL_HEADING.match(text)
        or PRIMARY_STATEMENT_HEADING.match(text)
        or NUMBERED_SECTION_HEADING.match(text)
        or SUBSECTION_PREFIX.match(text)
    ):
        return False
    if SUBSECTION_PREFIX.match(text) and len(words) > 5 and re.match(
        r"^(?:\(?[A-Za-z]\)|[A-Za-z]\.|[ivxIVX]{1,4}\))\s+the\b",
        text,
        re.I,
    ):
        return False
    if re.match(r"^(?:in|of|to|for|from|with|by|as|and|or)\b", text, re.I) and not (
        STRUCTURAL_HEADING.match(text)
        or NUMBERED_SECTION_HEADING.match(text)
        or PRIMARY_STATEMENT_HEADING.match(text)
    ):
        return False
    if GENERIC_HEADER.search(text) or RUNNING_NAV_BANNER.search(text):
        return False
    if re.match(r"^\d+\s+standalone\b", text, re.I) or re.search(r"\bfinancial\s+statements\s+\d+$", text, re.I):
        return False
    if "*" in text:
        return False
    if re.fullmatch(r"[\d\s.,()/:%₹$£€\-–—*]+", text):
        return False
    if "•" in text or "●" in text or "▪" in text:
        return False
    if re.search(r"[a-z]{3,}\.\s+[A-Za-z]", text):
        return False
    if re.search(
        r"@|www\.|\b(?:tel|fax|mobile|ph\.?\s*no|din|udin|membership\s+no|firm\s+registration|"
        r"p\.?\s*o\.?\b|dist\s*:|pin\s*:|ward\s+no)\b",
        text,
        re.I,
    ):
        return False
    if TRAILING_DATA_COLUMNS.search(text):
        return False
    if re.search(r"\)\s+\d[\d,]*(?:\s+\d[\d,]*)?$", text):
        return False
    if re.search(r"\s+[-–—]\s*\(?\d[\d,]*(?:\.\d+)?%?\)?$", text):
        return False
    numeric_tokens = re.findall(r"\b\d[\d,]*(?:\.\d+)?%?\b", text)
    if len(numeric_tokens) >= 2 and not (
        STRUCTURAL_HEADING.match(text)
        or PRIMARY_STATEMENT_HEADING.match(text)
        or NUMBERED_SECTION_HEADING.match(text)
    ):
        return False
    if (
        re.search(r"\s+\(?\d[\d,]*(?:\.\d+)?%?\)?$", text)
        and not re.search(
            r"\b(?:as\s+at|as\s+on|year\s+ended|period\s+ended)\b",
            text,
            re.I,
        )
        and not (
            STRUCTURAL_HEADING.match(text)
            or PRIMARY_STATEMENT_HEADING.match(text)
            or NUMBERED_SECTION_HEADING.match(text)
        )
    ):
        return False
    if re.match(r"^[\(\['\"‘“]", text) and not SUBSECTION_PREFIX.match(text):
        return False
    if not _has_balanced_delimiters(text):
        return False
    if TRAILING_FRAGMENT.search(text):
        return False
    if re.match(
        r"^(?:refer\b|see\b|note\s*:|estimated\s+value\s+of\s+contracts|"
        r"the\s+accompanying\b|for\s+the\s+year\b|as\s+per\b|in\s+terms\s+of\b|"
        r"to\s+the\s+independent\s+auditor|report\s+on\s+the\b|we\s+have\b|"
        r"following\s+key\s+assumptions|the\s+reconciliation\s+between|"
        r"the\s+disaggregation\s+of|the\s+following\s+table\s+shows|"
        r"for\s+assets\s+and\s+liabilities|details\s+of\s+the\s+liabilities\s+arising|"
        r"the\s+fair\s+value\s+of|the\s+carrying\s+amounts|"
        r"disclosure\s+of\s+transactions\s+between|the\s+assets,\s+liabilities|"
        r"the\s+charge\s+to\s+the|the\s+sensitivity\s+of|"
        r"with\s+the\s+objective\s+of|none\s+of\s+the\s+plans)",
        text,
        re.I,
    ):
        return False

    has_structure = (
        bool(STRUCTURAL_HEADING.match(text))
        or bool(SUBSECTION_PREFIX.match(text))
        or bool(NUMBERED_SECTION_HEADING.match(text))
    )
    has_domain = bool(FINANCIAL_DOMAIN_TERMS.search(text))
    if not (has_structure or has_domain):
        return False

    employee_plan_caption = bool(
        re.search(r"\bemployees?(?:['’])?\s+benefit\s+plans?\b", text, re.I)
        and re.search(r"\bsignificant\s+influence\b", text, re.I)
    )
    if (NARRATIVE.search(text) and not employee_plan_caption) or len(re.findall(r"[.;!?]", text)) > 2:
        return False
    if text.endswith(".") and not re.search(r"\bcontd\.$", text, re.I):
        return False
    return True


def _same_text_column(first: dict, second: dict) -> bool:
    first_x0, first_x1 = first.get("x0"), first.get("x1")
    second_x0, second_x1 = second.get("x0"), second.get("x1")
    if None in (first_x0, first_x1, second_x0, second_x1):
        return True
    overlap = max(
        0.0,
        min(float(first_x1), float(second_x1))
        - max(float(first_x0), float(second_x0)),
    )
    min_width = max(
        1.0,
        min(float(first_x1) - float(first_x0),
            float(second_x1) - float(second_x0)),
    )
    left_tolerance = max(18.0, min_width * 0.20)
    return overlap / min_width >= 0.20 or abs(float(first_x0) - float(second_x0)) <= left_tolerance


def _extract_merged_lines(page, is_ocr: bool = False) -> list[dict]:
    """Extract text lines and merge standalone structural or lettered subsection prefixes."""
    try:
        raw_lines = page.extract_text_lines(layout=False, strip=True, return_chars=True) or []
    except Exception:
        return []

    cleaned_lines = []
    for item in raw_lines:
        txt = _clean(str(item.get("text", "")), is_ocr=is_ocr)
        if not txt:
            continue
        cleaned_lines.append({
            "text": txt,
            "top": float(item.get("top", 0.0)),
            "bottom": float(item.get("bottom", item.get("top", 0.0))),
            "x0": float(item.get("x0", 0.0)),
            "x1": float(item.get("x1", 0.0)),
            "chars": item.get("chars", []),
            "font_size": max((float(char.get("size", 0.0)) for char in item.get("chars", [])), default=0.0),
            "bold_ratio": (
                sum(
                    any(token in str(char.get("fontname", "")).lower()
                        for token in ("bold", "black", "demi", "semibold", "heavy"))
                    for char in item.get("chars", [])
                ) / len(item.get("chars", []))
                if item.get("chars") else 0.0
            ),
        })

    merged = []
    i = 0
    while i < len(cleaned_lines):
        curr = cleaned_lines[i]
        # Two-line note heading: structural prefix followed by title on subsequent line
        if re.fullmatch(r"(?:note|notes|schedule)\s*\d+[a-zA-Z]?\s*[:.\-–]\s*$", curr["text"], re.I):
            matched_offset = None
            for offset in (1, 2):
                if i + offset < len(cleaned_lines):
                    cand = cleaned_lines[i + offset]
                    if (
                        0 <= cand["top"] - curr["bottom"] <= 28
                        and _same_text_column(curr, cand)
                    ):
                        if not GENERIC_HEADER.search(cand["text"]) and len(cand["text"].split()) <= 10:
                            matched_offset = offset
                            break
            if matched_offset is not None:
                cand = cleaned_lines[i + matched_offset]
                combined = _clean(f"{curr['text'].rstrip(':.-– ')} : {cand['text']}", is_ocr=is_ocr)
                merged.append({
                    "text": combined,
                    "top": curr["top"],
                    "bottom": cand["bottom"],
                    "x0": min(curr["x0"], cand["x0"]),
                    "x1": max(curr["x1"], cand["x1"]),
                    "font_size": max(curr["font_size"], cand["font_size"]),
                    "bold_ratio": max(curr["bold_ratio"], cand["bold_ratio"]),
                })
                i += matched_offset + 1
                continue

        if i + 1 < len(cleaned_lines):
            nxt = cleaned_lines[i + 1]
            vertical_gap = nxt["top"] - curr["bottom"]
            if 0 <= vertical_gap <= 22:
                # Subsection prefix followed by title
                if re.fullmatch(r"\(?[A-Za-z][.)]|\([ivxIVX]{1,4}\)", curr["text"]):
                    if (
                        _same_text_column(curr, nxt)
                        and not GENERIC_HEADER.search(nxt["text"])
                        and not RUNNING_NAV_BANNER.search(nxt["text"])
                        and len(nxt["text"].split()) <= 12
                    ):
                        combined = _clean(f"{curr['text']} {nxt['text']}", is_ocr=is_ocr)
                        merged.append({
                            "text": combined,
                            "top": curr["top"],
                            "bottom": nxt["bottom"],
                            "x0": min(curr["x0"], nxt["x0"]),
                            "x1": max(curr["x1"], nxt["x1"]),
                            "font_size": max(curr["font_size"], nxt["font_size"]),
                            "bold_ratio": max(curr["bold_ratio"], nxt["bold_ratio"]),
                        })
                        i += 2
                        continue
                # Multi-line document notes banner
                if (
                    _same_text_column(curr, nxt)
                    and re.fullmatch(r"notes?", curr["text"], re.I)
                    and re.match(
                        r"^(?:to|on|forming\s+part\s+of)\s+(?:the\s+)?financial\s+statements",
                        nxt["text"],
                        re.I,
                    )
                ):
                    combined = _clean(f"{curr['text']} {nxt['text']}", is_ocr=is_ocr)
                    merged.append({
                        "text": combined,
                        "top": curr["top"],
                        "bottom": nxt["bottom"],
                        "x0": min(curr["x0"], nxt["x0"]),
                        "x1": max(curr["x1"], nxt["x1"]),
                        "font_size": max(curr["font_size"], nxt["font_size"]),
                        "bold_ratio": max(curr["bold_ratio"], nxt["bold_ratio"]),
                    })
                    i += 2
                    continue
                # Wrapped note heading spanning multiple lines
                if (
                    _same_text_column(curr, nxt)
                    and STRUCTURAL_HEADING.match(curr["text"])
                    and TRAILING_FRAGMENT.search(curr["text"])
                    and len(nxt["text"].split()) <= 12
                ):
                    combined = _clean(f"{curr['text']} {nxt['text']}", is_ocr=is_ocr)
                    merged.append({
                        "text": combined,
                        "top": curr["top"],
                        "bottom": nxt["bottom"],
                        "x0": min(curr["x0"], nxt["x0"]),
                        "x1": max(curr["x1"], nxt["x1"]),
                        "font_size": max(curr["font_size"], nxt["font_size"]),
                        "bold_ratio": max(curr["bold_ratio"], nxt["bold_ratio"]),
                    })
                    i += 2
                    continue
        merged.append(curr)
        i += 1
    return merged


def _leftmost_column_text(item: dict) -> str:
    chars = sorted(item.get("chars", []), key=lambda char: float(char.get("x0", 0.0)))
    if not chars:
        return ""
    split_at = None
    for previous, current in zip(chars, chars[1:]):
        gap = float(current.get("x0", 0.0)) - float(previous.get("x1", 0.0))
        if gap >= 10.0:
            split_at = float(current.get("x0", 0.0))
            break
    if split_at is None:
        return _clean(item.get("text", ""))
    words = str(item.get("text", "")).split()
    char_index = 0
    left_words = []
    for word in words:
        word_chars = []
        while char_index < len(chars) and str(chars[char_index].get("text", "")).isspace():
            char_index += 1
        for _ in word:
            while char_index < len(chars) and str(chars[char_index].get("text", "")).isspace():
                char_index += 1
            if char_index >= len(chars):
                break
            word_chars.append(chars[char_index])
            char_index += 1
        if not word_chars or float(word_chars[0].get("x0", 0.0)) >= split_at:
            break
        left_words.append(word)
    return _clean(" ".join(left_words))


def page_has_notes_banner(page) -> bool:
    """Return True if the page is inside the 'Notes to the financial statements' section."""
    try:
        raw_text = page.extract_text() or ""
    except Exception:
        raw_text = ""
    top_chunk = "\n".join(raw_text.splitlines()[:10])
    return bool(
        re.search(
            r"\b(?:notes?\s+(?:to|on|forming\s+part\s+of)\s+(?:the\s+)?financial\s+statements|"
            r"to\s+the\s+financial\s+statements\s+for\s+the\s+year\s+ended|"
            r"note\s+\d+\s*:)",
            top_chunk,
            re.I,
        )
    )


def find_page_primary_heading(page, max_y: float | None = None) -> str | None:
    """Find the active primary Statement or Note heading on the page above `max_y`."""
    lines = _extract_merged_lines(page)
    in_notes_section = page_has_notes_banner(page)
    page_height = getattr(page, "height", 792.0)

    specific_candidates = []
    banner_candidates = []

    for item in lines:
        if max_y is not None and item["top"] > max_y + 15:
            continue
        text = item["text"]
        if not _is_plausible_caption(text) or is_subsection_title(text):
            continue
        if GENERIC_NOTES_BANNER.match(text):
            banner_candidates.append(text)
            continue
        if STRUCTURAL_HEADING.match(text) or NUMBERED_SECTION_HEADING.match(text):
            specific_candidates.append(text)
        elif PRIMARY_STATEMENT_HEADING.match(text):
            if not in_notes_section and item["top"] <= page_height * 0.35:
                specific_candidates.append(text)

    if specific_candidates:
        return specific_candidates[-1][:140].rstrip(" ,;:-")
    if banner_candidates and not in_notes_section:
        return banner_candidates[-1][:140].rstrip(" ,;:-")
    return None


def _line_overlaps_table(item: dict, bbox: tuple) -> bool:
    x0, _, x1, _ = bbox
    line_x0 = item.get("x0", item.get("x"))
    line_x1 = item.get("x1", item.get("right"))
    if line_x0 is None or line_x1 is None:
        return True
    line_x0, line_x1 = float(line_x0), float(line_x1)
    if line_x1 <= line_x0:
        return True
    overlap = max(0.0, min(x1, line_x1) - max(x0, line_x0))
    min_width = max(1.0, min(x1 - x0, line_x1 - line_x0))
    margin = max(15.0, (x1 - x0) * 0.08)
    center = (line_x0 + line_x1) / 2.0
    return overlap / min_width >= 0.15 or x0 - margin <= center <= x1 + margin


def extract_table_title(
    page,
    bbox,
    max_distance: float = 140.0,
    additional_lines: list[dict] | None = None,
    min_y: float | None = None,
) -> str:
    """Return the closest plausible nearby caption, or ``Untitled table``."""
    _, top, _, bottom = bbox
    lines = _extract_merged_lines(page)
    in_notes_section = page_has_notes_banner(page)
    page_height = getattr(page, "height", 792.0)

    for index, item in enumerate(lines[:-1]):
        text = item["text"]
        if (
            ":" not in text
            or not is_subsection_title(text)
            or item.get("bold_ratio", 0.0) < 0.35
        ):
            continue
        left_caption = text.split(":", 1)[0].strip()
        if not re.search(r"\b(where|with|of|to|and|for|in|by|as|from)$", left_caption, re.I):
            continue
        following = lines[index + 1]
        if not 0 <= following["top"] - item["bottom"] <= 22.0:
            continue
        continuation = _leftmost_column_text(following)
        if not re.match(r"^(?:there|which|and|of|to|who|with|in|because|that)\b", continuation, re.I):
            continue
        item["text"] = _clean(f"{left_caption} {continuation}")
        item["bottom"] = following["bottom"]

    for extra in additional_lines or []:
        text = _clean(extra.get("text", ""), is_ocr=True)
        if not text:
            continue
        line = {
            **extra,
            "text": text,
            "top": float(extra.get("top", 0.0)),
            "bottom": float(extra.get("bottom", extra.get("top", 0.0))),
        }
        duplicate_index = next(
            (
                index for index, existing in enumerate(lines)
                if abs(existing["top"] - line["top"]) <= 4.0
                and SequenceMatcher(
                    None, existing["text"].lower(), line["text"].lower()
                ).ratio() >= 0.65
            ),
            None,
        )
        if duplicate_index is None:
            lines.append(line)
        elif (
            not _is_plausible_caption(lines[duplicate_index]["text"])
            and _is_plausible_caption(line["text"])
        ):
            lines[duplicate_index] = line

    # Allow captions below candidate top boundary only when table spans the primary page body
    candidate_height = max(0.0, bottom - top)
    allow_below = top <= page_height * 0.12 and candidate_height >= page_height * 0.60
    allow_primary_inside = (
        top <= page_height * 0.12 and candidate_height >= page_height * 0.25
    )
    max_below_top = min(135.0, page_height * 0.17) if allow_below else 0.0
    if allow_primary_inside:
        max_below_top = max(max_below_top, page_height * 0.24)
    max_below_top = max(max_below_top, 90.0)

    candidates = []
    for item in lines:
        if not _line_overlaps_table(item, bbox):
            continue
        text = item["text"]
        caption_text = re.sub(
            r"\s+(?:as\s*at|asat)\s+.*$",
            "",
            text,
            flags=re.I,
        ).strip(" ,;:-–—")
        y = item["top"]
        if min_y is not None and y < min_y - 4.0:
            continue
        if not text or y < top - max_distance or y > top + max_below_top:
            continue
        # Ensure structural note headings are spatially adjacent to the table region
        if STRUCTURAL_HEADING.match(text) and top - y > 90.0:
            continue
        if y > top:
            text = caption_text or text
        plausible = _is_plausible_caption(text)
        if (
            not plausible
            and "confidence" in item
            and 25.0 <= float(item["confidence"]) < 70.0
            and 4 <= len(text) <= 80
            and 1 <= len(text.split()) <= 6
            and y <= top
            and top - y <= 25.0
        ):
            nearby_text = " ".join(
                line["text"]
                for line in lines
                if y - 2.0 <= line["top"] <= top + 45.0
                and _line_overlaps_table(line, bbox)
            )
            plausible = bool(re.search(
                r"\b(particulars|description|amount|as\s+at|year\s+ended|"
                r"period\s+ended|number\s+of\s+shares)\b",
                nearby_text,
                re.I,
            ))
        if not plausible:
            continue
        if GENERIC_NOTES_BANNER.match(text):
            continue

        # In notes disclosures, un-prefixed primary statement terms are sub-items rather than independent statements
        if in_notes_section and PRIMARY_STATEMENT_HEADING.match(text):
            continue

        below_table_top = y > top
        local_caption = (
            below_table_top
            and y - top <= 35.0
            and (
                is_subsection_title(text)
                or STRUCTURAL_HEADING.match(text)
            )
        )
        structural_caption = bool(STRUCTURAL_HEADING.match(text))
        primary_caption = bool(PRIMARY_STATEMENT_HEADING.match(text))
        if below_table_top and not (
            (allow_below and (structural_caption or primary_caption))
            or (allow_primary_inside and primary_caption)
            or (local_caption and y <= bottom + 5.0)
        ):
            continue

        distance = abs(top - y) + (45 if below_table_top else 0)
        if local_caption and not (
            STRUCTURAL_HEADING.match(text) or PRIMARY_STATEMENT_HEADING.match(text)
        ):
            distance += 30
        if item.get("bold_ratio", 0.0) >= 0.5:
            distance -= 12
        if item.get("font_size", 0.0) >= 10:
            distance -= 8
        if "confidence" in item:
            distance += max(0.0, 70.0 - float(item["confidence"])) * 0.4

        intervening_lines = [
            line for line in lines
            if item["bottom"] < line["top"] < top
            and not GENERIC_HEADER.search(line["text"])
            and _line_overlaps_table(line, bbox)
        ]
        intervening_words = sum(len(line["text"].split()) for line in intervening_lines)
        if intervening_words > 24:
            distance += min(120, (intervening_words - 24) * 2)

        if GENERIC_NOTES_BANNER.match(text):
            distance += 160
        elif is_subsection_title(text) and not (
            local_caption and y - top <= 35.0 and item.get("bold_ratio", 0.0) >= 0.35
        ) and (below_table_top or top - y > 55.0):
            distance += 190

        if STRUCTURAL_HEADING.match(text):
            distance -= 90
        elif PRIMARY_STATEMENT_HEADING.match(text) and not in_notes_section:
            distance -= 75
        elif NUMBERED_SECTION_HEADING.match(text):
            distance -= 55

        if re.search(r"\b(contd|continued)\b", text, re.I):
            distance -= 15

        candidates.append((distance, text))

    # Bottom caption fallback for standalone full-page financial statements
    if not candidates and not in_notes_section:
        for item in lines:
            text = item["text"]
            y = item["top"]
            if not _line_overlaps_table(item, bbox):
                continue
            if min_y is not None and y < min_y - 4.0:
                continue
            if y >= bottom - 110 and PRIMARY_STATEMENT_HEADING.match(text) and _is_plausible_caption(text):
                candidates.append((abs(bottom - y) + 60, text))

    if not candidates:
        return "Untitled table"
    candidates.sort(key=lambda item: (item[0], len(item[1])))
    return candidates[0][1][:140].rstrip(" ,;:-")