"""
Diagnostic script for spec PDF parsing.

Run inside the server container:
  docker exec -it apsparcer-server-1 python /app/diag_spec.py /path/to/file.pdf

Or from the project root (if pdfplumber is available locally):
  python diag_spec.py server/uploads/6_8.1____15.04.26-2fd6b1c7.pdf
"""
import io, re, sys
import pdfplumber

# ── minimal copies of helpers (no server imports needed) ───────────────────

_KAZNISA_RE = re.compile(r"^\d{3}-\d{3}")
_UNITS = {"шт","шт.","м","м.","м2","м3","компл","компл.","рул","рул.","кг","км","л","уп","уп.","п.м","п.м.","пм","пог.м","пог.м."}

def _norm(v):
    if v is None: return ""
    return re.sub(r"\s+", " ", str(v).replace("\n"," ").replace("\xa0"," ")).strip().lower()

def _is_pos_value(cell):
    if cell is None: return None
    s = str(cell).strip().rstrip(".")
    if not s: return None
    if s.isdigit(): return s
    if re.match(r"^\d+\.\d+$", s): return s
    return None

def _is_spec_page_text(tl):
    has_poz  = "поз." in tl or "поз " in tl
    has_naim = "наименование" in tl
    has_kol  = "кол-во" in tl or "количество" in tl
    if "спецификация оборудования" in tl:
        is_ved = "ведомость рабочих чертежей" in tl or "ведомость чертежей" in tl
        if is_ved and not (has_poz and has_naim):
            return False
        return True
    if ".со" in tl:
        if has_poz and has_naim and has_kol:
            return True
    return False

# ── main ───────────────────────────────────────────────────────────────────

pdf_path = sys.argv[1] if len(sys.argv) > 1 else "spec.pdf"
with open(pdf_path, "rb") as f:
    pdf_bytes = f.read()

print(f"\n{'='*70}")
print(f"File: {pdf_path}  ({len(pdf_bytes):,} bytes)")

with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    total = len(pdf.pages)
    print(f"Total pages: {total}")

    # ── Phase 1: spec page detection ───────────────────────────────────────
    spec_indices = []
    print(f"\n{'─'*70}")
    print("PHASE 1 — spec page detection")
    print(f"{'─'*70}")
    for idx in range(total):
        try:
            txt = pdf.pages[idx].extract_text() or ""
        except Exception as e:
            txt = ""
        tl = txt.lower()
        is_spec = _is_spec_page_text(tl)
        if is_spec or idx >= total - 5:   # always show last 5 pages
            snip = txt[:120].replace("\n"," ")
            print(f"  p{idx+1:02d}  spec={'YES' if is_spec else 'no ':4}  {snip!r:.120}")
        if is_spec:
            spec_indices.append(idx)

    if spec_indices:
        print(f"\n→ Spec pages (1-based): {[i+1 for i in spec_indices]}")
        page_iter = [(i+1, pdf.pages[i]) for i in spec_indices]
    else:
        print("\n→ No spec pages detected — will process ALL pages")
        page_iter = list(enumerate(pdf.pages, start=1))

    # ── Phase 2: table extraction per spec page ────────────────────────────
    print(f"\n{'─'*70}")
    print("PHASE 2 — table extraction")
    print(f"{'─'*70}")

    total_items = 0
    for page_num, page in page_iter:
        try:
            tables_default    = page.extract_tables() or []
            tables_permissive = page.extract_tables(table_settings={
                "vertical_strategy":      "lines",
                "horizontal_strategy":    "lines",
                "snap_tolerance":         10,
                "join_tolerance":         5,
                "intersection_tolerance": 5,
            }) or []
        except Exception as e:
            print(f"\n  p{page_num}: EXTRACTION ERROR: {e}")
            continue

        rows_d = sum(len(t) for t in tables_default)
        rows_p = sum(len(t) for t in tables_permissive)
        chosen = tables_permissive if rows_p > rows_d else tables_default
        chosen_name = "permissive" if rows_p > rows_d else "default"

        print(f"\n  ── Page {page_num} ──")
        print(f"     default tables={len(tables_default)}, rows={rows_d}")
        print(f"     permissive tables={len(tables_permissive)}, rows={rows_p}")
        print(f"     → using {chosen_name}")

        page_items = 0
        skip_no_pos = 0
        skip_empty  = 0
        for ti, table in enumerate(chosen):
            if not table:
                continue
            ncols = len(table[0]) if table else 0
            print(f"\n     Table {ti}: {len(table)} rows × {ncols} cols")
            # Show first 3 rows for structure inspection
            for ri, row in enumerate(table[:4]):
                cells = [str(c or "")[:30] for c in row]
                print(f"       row[{ri}]: {cells}")
            if len(table) > 4:
                print(f"       ... {len(table)-4} more rows")

            # Count skips
            for row in table:
                if not row: continue
                pos_cell = row[0] if row else None
                pv = _is_pos_value(pos_cell)
                if pv is None:
                    skip_no_pos += 1
                else:
                    # Check name/article/code columns (guess: col1=name, col2=article, col3=code)
                    name = str(row[1] or "").strip() if len(row) > 1 else ""
                    art  = str(row[2] or "").strip() if len(row) > 2 else ""
                    code = str(row[3] or "").strip() if len(row) > 3 else ""
                    if not name and not art and not code:
                        skip_empty += 1
                    else:
                        page_items += 1
                        total_items += 1

        print(f"\n     → approx items: {page_items}  (skipped no-pos: {skip_no_pos}, empty: {skip_empty})")

    print(f"\n{'='*70}")
    print(f"TOTAL approx items across spec pages: {total_items}")
    print(f"{'='*70}\n")
