"""patch_vba_binary.py - patches VBA in .xlsm without Excel or win32com."""
import math, os, struct, sys, zipfile
from io import BytesIO
from typing import Dict, Tuple
from oletools.olevba import decompress_stream

# ── VBA code for modules (Cyrillic as \xNN latin-1 escapes) ──────────────────
_PATCH_VBA: Dict[str, str] = {}

# Лист2 code (БД stored as \xc1\xc4 = CP1251 for "БД")
_PATCH_VBA["Лист2"] = (
    'Attribute VB_Name = "\xcb\xe8\xf1\xf22"\r\n'
    'Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"\r\n'
    'Attribute VB_GlobalNameSpace = False\r\n'
    'Attribute VB_Creatable = False\r\n'
    'Attribute VB_PredeclaredId = True\r\n'
    'Attribute VB_Exposed = True\r\n'
    'Attribute VB_TemplateDerived = False\r\n'
    'Attribute VB_Customizable = True\r\n'
    'Option Explicit\r\n'
    '\r\n'
    'Private Sub Worksheet_Change(ByVal Target As Range)\r\n'
    '    If Not EnableMyMacro Then Exit Sub\r\n'
    '    Dim intersectRange As Range\r\n'
    '    Set intersectRange = Intersect(Target, Me.Columns(2))\r\n'
    '    If intersectRange Is Nothing Then Exit Sub\r\n'
    '    On Error GoTo CleanUp\r\n'
    '    Application.EnableEvents = False\r\n'
    '    Application.ScreenUpdating = False\r\n'
    '    Dim wsData As Worksheet\r\n'
    '    Set wsData = ThisWorkbook.Sheets("\xc1\xc4")\r\n'
    '    Dim lastRow As Long\r\n'
    '    lastRow = wsData.Cells(wsData.Rows.Count, "B").End(xlUp).Row\r\n'
    '    If lastRow < 2 Then GoTo CleanUp\r\n'
    '    Dim arrData As Variant\r\n'
    '    arrData = wsData.Range("B1:J" & lastRow).Value\r\n'
    '    Dim tCell As Range\r\n'
    '    For Each tCell In intersectRange\r\n'
    '        If Not IsEmpty(tCell.Value) Then\r\n'
    '            Dim strSearch As String\r\n'
    '            strSearch = LCase$(Trim$(CStr(tCell.Value)))\r\n'
    '            If Len(strSearch) = 0 Then GoTo NextCell\r\n'
    '            Dim matches As Collection\r\n'
    '            Dim matchIndices As Collection\r\n'
    '            Set matches = New Collection\r\n'
    '            Set matchIndices = New Collection\r\n'
    '            Dim exactMatchIdx As Long\r\n'
    '            exactMatchIdx = 0\r\n'
    '            Dim i As Long\r\n'
    '            For i = 1 To UBound(arrData, 1)\r\n'
    '                Dim ValB As String, valC As String\r\n'
    '                ValB = CStr(arrData(i, 1))\r\n'
    '                valC = CStr(arrData(i, 2))\r\n'
    '                If LCase$(ValB) = strSearch Or LCase$(valC) = strSearch Then\r\n'
    '                    exactMatchIdx = i\r\n'
    '                    Exit For\r\n'
    '                End If\r\n'
    '                If InStr(1, ValB, strSearch, vbTextCompare) > 0 Or _\r\n'
    '                   InStr(1, valC, strSearch, vbTextCompare) > 0 Then\r\n'
    '                    matches.Add arrData(i, 1) & " - " & valC\r\n'
    '                    matchIndices.Add i\r\n'
    '                End If\r\n'
    '            Next i\r\n'
    '            If exactMatchIdx > 0 Then\r\n'
    '                Call UpdateWVRow(tCell, _\r\n'
    '                    CStr(arrData(exactMatchIdx, 1)), _\r\n'
    '                    CStr(arrData(exactMatchIdx, 2)), _\r\n'
    '                    CStr(arrData(exactMatchIdx, 3)), _\r\n'
    '                    CStr(arrData(exactMatchIdx, 9)))\r\n'
    '            ElseIf matches.Count > 0 Then\r\n'
    '                Dim frm As UserForm1\r\n'
    '                Set frm = New UserForm1\r\n'
    '                frm.lstMatches.Clear\r\n'
    '                Dim matchItem As Variant\r\n'
    '                For Each matchItem In matches\r\n'
    '                    frm.lstMatches.AddItem matchItem\r\n'
    '                Next matchItem\r\n'
    '                Dim result As String\r\n'
    '                result = frm.GetSelectedValue\r\n'
    '                Unload frm\r\n'
    '                If result <> "" Then\r\n'
    '                    Dim selectedIdx As Long\r\n'
    '                    selectedIdx = 0\r\n'
    '                    Dim j As Long\r\n'
    '                    For j = 1 To matches.Count\r\n'
    '                        If matches(j) = result Then\r\n'
    '                            selectedIdx = matchIndices(j)\r\n'
    '                            Exit For\r\n'
    '                        End If\r\n'
    '                    Next j\r\n'
    '                    If selectedIdx > 0 Then\r\n'
    '                        Call UpdateWVRow(tCell, _\r\n'
    '                            CStr(arrData(selectedIdx, 1)), _\r\n'
    '                            CStr(arrData(selectedIdx, 2)), _\r\n'
    '                            CStr(arrData(selectedIdx, 3)), _\r\n'
    '                            CStr(arrData(selectedIdx, 9)))\r\n'
    '                    Else\r\n'
    '                        tCell.Value = Split(result, " - ")(0)\r\n'
    '                    End If\r\n'
    '                End If\r\n'
    '            End If\r\n'
    'NextCell:\r\n'
    '        End If\r\n'
    '    Next tCell\r\n'
    'CleanUp:\r\n'
    '    Application.EnableEvents = True\r\n'
    '    Application.ScreenUpdating = True\r\n'
    'End Sub\r\n'
    '\r\n'
    'Private Sub UpdateWVRow(tCell As Range, article As String, name As String, unit As String, brand As String)\r\n'
    '    Dim r As Long\r\n'
    '    r = tCell.Row\r\n'
    '    Me.Cells(r, 1).Value = brand\r\n'
    '    tCell.Value           = article\r\n'
    '    Me.Cells(r, 3).Value = name\r\n'
    '    Me.Cells(r, 4).Value = unit\r\n'
    '    Me.Cells(r, 7).Value = ""\r\n'
    'End Sub\r\n'
    '\r\n'
    'Private Sub Worksheet_SelectionChange(ByVal Target As Range)\r\n'
    '    If Target.Cells.CountLarge > 1 Then Exit Sub\r\n'
    '    If Application.CutCopyMode = xlCopy Or Application.CutCopyMode = xlCut Then Exit Sub\r\n'
    '    Target.Calculate\r\n'
    'End Sub\r\n'
    '\r\n'
    'Private Sub Worksheet_Activate()\r\n'
    '    If Application.CutCopyMode = xlCopy Or Application.CutCopyMode = xlCut Then Exit Sub\r\n'
    '    On Error Resume Next\r\n'
    '    Application.EnableEvents = False\r\n'
    '    Application.ScreenUpdating = False\r\n'
    '    Me.Calculate\r\n'
    '    Application.CalculateFull\r\n'
    '    Application.ScreenUpdating = True\r\n'
    '    Application.EnableEvents = True\r\n'
    '    On Error GoTo 0\r\n'
    'End Sub\r\n'
)

# ToggleMacroRus uses Ctrl+й (\xe9 in CP1251)
_PATCH_VBA["\xe2\xea\xeb_\xe2\xfb\xea\xeb_\xec\xe0\xea\xf0\xee\xf1"] = (
    'Attribute VB_Name = "\xe2\xea\xeb_\xe2\xfb\xea\xeb_\xec\xe0\xea\xf0\xee\xf1"\r\n'
    'Option Explicit\r\n'
    '\r\n'
    'Public EnableMyMacro As Boolean\r\n'
    '\r\n'
    'Sub EnableMacro()\r\n'
    '    EnableMyMacro = True\r\n'
    '    MsgBox "\xcc\xe0\xea\xf0\xee\xf1 \xe2\xea\xeb\xfe\xf7\xb8\xed", vbInformation, "\xd1\xf2\xe0\xf2\xf3\xf1"\r\n'
    'End Sub\r\n'
    '\r\n'
    'Sub DisableMacro()\r\n'
    '    EnableMyMacro = False\r\n'
    '    MsgBox "\xcc\xe0\xea\xf0\xee\xf1 \xee\xf2\xea\xeb\xfe\xf7\xb8\xed", vbInformation, "\xd1\xf2\xe0\xf2\xf3\xf1"\r\n'
    'End Sub\r\n'
    '\r\n'
    'Sub ToggleMacroEng()\r\n'
    'Attribute ToggleMacroEng.VB_ProcData.VB_Invoke_Func = "q\\n14"\r\n'
    '    If EnableMyMacro Then\r\n'
    '        Call DisableMacro\r\n'
    '    Else\r\n'
    '        Call EnableMacro\r\n'
    '    End If\r\n'
    'End Sub\r\n'
    '\r\n'
    'Sub ToggleMacroRus()\r\n'
    'Attribute ToggleMacroRus.VB_ProcData.VB_Invoke_Func = "\xe9\\n14"\r\n'
    '    If EnableMyMacro Then\r\n'
    '        Call DisableMacro\r\n'
    '    Else\r\n'
    '        Call EnableMacro\r\n'
    '    End If\r\n'
    'End Sub\r\n'
)

# Keys are already CP1251-as-latin1 strings (how dir stream stores them)
_MODULE_ENCODING = "latin-1"


# ── LZ77 MS-OVBA compressor ───────────────────────────────────────────────────

def _copy_token_help(n):
    ob = max(4, min(12, math.floor(math.log2(max(n-1,1)))+1)) if n>1 else 4
    lb = 16 - ob
    lm = (1 << lb) - 1
    om = (1 << ob) - 1
    return lm, om, lb, lm + 3

def _compress_chunk(data):
    dc, tokens = 0, bytearray()
    while dc < len(data):
        fb = len(tokens)
        tokens.append(0)
        flags = 0
        for bit in range(8):
            if dc >= len(data): break
            lm, om, lb, ml = _copy_token_help(dc)
            bl, bp = 0, dc
            for i in range(max(0, dc-om-1), dc):
                m = 0
                while m < min(ml, len(data)-dc) and data[i+m] == data[dc+m]:
                    m += 1
                if m > bl: bl, bp = m, i
            if bl >= 3:
                flags |= 1 << bit
                tok = ((dc-bp-1) << lb | (bl-3) & lm) & 0xFFFF
                tokens += struct.pack("<H", tok)
                dc += bl
            else:
                tokens.append(data[dc]); dc += 1
        tokens[fb] = flags
    hdr = struct.pack("<H", (len(tokens)-1)&0x0FFF | 0b011<<12 | 1<<15)
    return bytes(hdr) + bytes(tokens)

def compress_vba(src):
    out = bytearray([0x01])
    pos = 0
    while pos < len(src):
        end = min(pos+4096, len(src))
        chunk = src[pos:end]
        comp = _compress_chunk(chunk)
        if len(comp)-2 >= len(chunk):
            pad = bytearray(chunk) + bytearray(4096-len(chunk))
            out += struct.pack("<H", 0x0FFF|0b011<<12|0<<15) + pad
        else:
            out += comp
        pos = end
    return bytes(out)


# ── OLE Compound File ─────────────────────────────────────────────────────────

SECT_END  = 0xFFFFFFFE
SECT_FREE = 0xFFFFFFFF
DE_SIZE   = 128

class OLEPatcher:
    def __init__(self, raw):
        self.raw = raw
        self._parse_header()
        self._load_fat()
        self._load_dir()
        self._load_minifat()

    def _parse_header(self):
        h = self.raw
        self.ss   = 1 << struct.unpack_from("<H", h, 30)[0]  # sector size (512)
        self.mss  = 1 << struct.unpack_from("<H", h, 32)[0]  # mini sector size (64)
        self.fdir = struct.unpack_from("<I", h, 48)[0]       # first dir sector
        self.cutoff = struct.unpack_from("<I", h, 56)[0]     # mini stream cutoff (4096)
        self.fmini = struct.unpack_from("<I", h, 60)[0]      # first miniFAT sector
        self.difat = list(struct.unpack_from("<109I", h, 76))

    def _load_fat(self):
        fat_data = bytearray()
        for s in self.difat:
            if s in (SECT_FREE, SECT_END): break
            fat_data += self._rsect(s)
        n = len(fat_data) // 4
        self.fat = list(struct.unpack_from(f"<{n}I", fat_data))

    def _load_dir(self):
        dir_data = self._rchain(self.fdir)
        n = len(dir_data) // DE_SIZE
        self.dir_entries = []
        for i in range(n):
            o = i * DE_SIZE
            r = dir_data[o:o+DE_SIZE]
            nl = struct.unpack_from("<H", r, 64)[0]
            name = r[:max(0, nl-2)].decode("utf-16-le", "replace")
            self.dir_entries.append({
                "sid": i,
                "name": name,
                "type": r[66],
                "isect_start": struct.unpack_from("<I", r, 116)[0],
                "size": struct.unpack_from("<I", r, 120)[0],
            })

    def _load_minifat(self):
        if self.fmini in (SECT_FREE, SECT_END):
            self.minifat = []; self._ministream = b""; return
        mf = bytearray()
        s = self.fmini
        while s not in (SECT_END, SECT_FREE) and s < len(self.fat):
            mf += self._rsect(s); s = self.fat[s]
        n = len(mf) // 4
        self.minifat = list(struct.unpack_from(f"<{n}I", mf))
        root = self.dir_entries[0]
        self._ministream = self._rchain(root["isect_start"])

    def _soff(self, s): return self.ss + s * self.ss
    def _rsect(self, s): o = self._soff(s); return bytes(self.raw[o:o+self.ss])

    def _chain(self, start):
        ch, s = [], start
        while s not in (SECT_END, SECT_FREE) and s < len(self.fat):
            ch.append(s); s = self.fat[s]
        return ch

    def _rchain(self, start):
        data = bytearray()
        for s in self._chain(start): data += self._rsect(s)
        return bytes(data)

    def _mini_chain(self, start):
        ch, s = [], start
        while s not in (SECT_END, SECT_FREE) and s < len(self.minifat):
            ch.append(s); s = self.minifat[s]
        return ch

    def _is_mini(self, e):
        return 0 < e["size"] < self.cutoff

    def read_stream(self, e):
        if self._is_mini(e):
            ch = self._mini_chain(e["isect_start"])
            data = bytearray()
            for s in ch:
                o = s * self.mss
                data += self._ministream[o:o+self.mss]
            return bytes(data[:e["size"]])
        return self._rchain(e["isect_start"])[:e["size"]]

    def find_entry(self, name):
        """Find stream by name. Accepts both Unicode and CP1251-as-latin1 names."""
        for e in self.dir_entries:
            if e["type"] != 2: continue
            if e["name"] == name: return e
            try:
                if e["name"].encode("cp1251").decode("latin-1") == name:
                    return e
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return None

    def patch_stream(self, name, new_data):
        e = self.find_entry(name)
        if e is None:
            print(f"  WARN: stream {name!r} not found"); return False
        if self._is_mini(e):
            print(f"  WARN: {name!r} is mini-stream, skip"); return False
        chain = self._chain(e["isect_start"])
        cap = len(chain) * self.ss
        if len(new_data) > cap:
            print(f"  ERR: {name!r}: {len(new_data)} > capacity {cap}"); return False
        padded = new_data + b'\x00' * (cap - len(new_data))
        for i, s in enumerate(chain):
            o = self._soff(s)
            self.raw[o:o+self.ss] = padded[i*self.ss:(i+1)*self.ss]
        # Update size in directory
        dc = self._chain(self.fdir)
        epp = self.ss // DE_SIZE
        ts = dc[e["sid"] // epp]
        ao = self._soff(ts) + (e["sid"] % epp) * DE_SIZE + 120
        struct.pack_into("<I", self.raw, ao, len(new_data))
        print(f"  OK: {name!r}: {e['size']} -> {len(new_data)} bytes")
        return True


# ── VBA dir stream parser → textoffsets ──────────────────────────────────────

def parse_dir_offsets(data):
    buf = BytesIO(data)
    offsets, cur, sname = {}, None, None
    while True:
        hdr = buf.read(6)
        if len(hdr) < 6: break
        rid, sz = struct.unpack_from("<HI", hdr)
        d = buf.read(sz)
        if rid == 0x0009: buf.read(2)   # PROJECTVERSION extra bytes
        if rid == 0x0019:
            cur = d.decode("latin-1", "replace"); sname = cur
        elif rid == 0x001A and cur:
            sname = d.decode("latin-1", "replace")
            pk = buf.read(6)
            if len(pk) == 6:
                r2, s2 = struct.unpack_from("<HI", pk)
                buf.read(s2) if r2 == 0x0032 else buf.seek(-6, 1)
        elif rid == 0x0031 and cur and len(d) >= 4:
            offsets[sname] = struct.unpack("<I", d[:4])[0]
        elif rid == 0x002B:
            cur = None; sname = None
    return offsets


# ── Find matching stream name ─────────────────────────────────────────────────

def _find_stream_name(ole, text_offsets, module_name):
    """
    module_name is a Unicode string (e.g. 'Лист2').
    text_offsets keys are latin-1 encoded CP1251 (e.g. 'Ëèñò2').
    Returns the key in text_offsets that matches module_name.
    """
    # Direct match (ASCII modules like 'Module1')
    if module_name in text_offsets:
        return module_name
    # CP1251->latin1 conversion
    try:
        k = module_name.encode("cp1251").decode("latin-1")
        if k in text_offsets:
            return k
    except Exception:
        pass
    # Also try: module_name might already be latin-1 encoded
    # (if keys in _PATCH_VBA use \xNN sequences)
    try:
        k2 = module_name.encode("latin-1").decode("cp1251").encode("cp1251").decode("latin-1")
        if k2 in text_offsets:
            return k2
    except Exception:
        pass
    return None


# ── Main patch function ───────────────────────────────────────────────────────

def patch_xlsm(src_path, dst_path):
    print(f"Source : {src_path}")
    print(f"Output : {dst_path}")

    with zipfile.ZipFile(src_path, "r") as z:
        vba_raw = bytearray(z.read("xl/vbaProject.bin"))

    ole = OLEPatcher(vba_raw)

    # Read VBA dir stream (mini-stream, ~1KB)
    de = ole.find_entry("dir")
    if de is None: raise RuntimeError("VBA dir stream not found")
    dir_comp = ole.read_stream(de)
    dir_decomp = decompress_stream(bytearray(dir_comp))
    text_offsets = parse_dir_offsets(dir_decomp)
    print(f"  VBA modules: {list(text_offsets.keys())}")

    patched = False
    for mod_name, new_code in _PATCH_VBA.items():
        sname = _find_stream_name(ole, text_offsets, mod_name)
        if sname is None:
            print(f"  WARN: {mod_name!r} not in dir stream"); continue
        toff = text_offsets[sname]
        e = ole.find_entry(sname)
        if e is None:
            print(f"  WARN: OLE stream {sname!r} not found"); continue

        old_stream = ole.read_stream(e)
        header = old_stream[:toff]
        new_bytes = new_code.encode(_MODULE_ENCODING)
        new_comp = compress_vba(new_bytes)
        new_stream = header + new_comp
        chain = ole._chain(e["isect_start"])
        cap = len(chain) * ole.ss
        print(f"  {sname!r}: toff={toff}, old={e['size']}, new={len(new_stream)}, cap={cap}, fits={len(new_stream)<=cap}")
        if ole.patch_stream(sname, new_stream):
            patched = True

    if not patched:
        print("  No changes made."); return

    import tempfile, shutil, os as _os
    # Write to temp file first (handles inplace mode where src==dst)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.xlsm')
    _os.close(tmp_fd)
    try:
        with zipfile.ZipFile(src_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = bytes(ole.raw) if item.filename == "xl/vbaProject.bin" else zin.read(item.filename)
                zout.writestr(item, data)
        shutil.move(tmp_path, dst_path)
    except Exception:
        _os.unlink(tmp_path)
        raise

    print(f"Done! File saved: {dst_path}")


def main():
    inplace = "--inplace" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        src = args[0]
    else:
        d = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(d, "client", "assets", "WV_template.xlsm"),
            os.path.join(d, "WV_template.xlsm"),
        ]
        src = next((p for p in candidates if os.path.exists(p)), None)
        if not src:
            print("Usage: python patch_vba_binary.py [--inplace] path/to/file.xlsm")
            sys.exit(1)
    if not os.path.exists(src):
        print(f"File not found: {src}"); sys.exit(1)
    dst = src if inplace else os.path.splitext(src)[0] + "_patched" + os.path.splitext(src)[1]
    patch_xlsm(src, dst)


# ── Mini-stream patching (appended fix) ──────────────────────────────────────
import math as _math

def _patch_mini_stream(ole, e, new_data):
    """
    Patch a mini-stream entry in-place, allocating extra mini-sectors if needed.
    Updates: mini-FAT chain, mini-sector data in raw bytes, dir entry size.
    Returns True on success.
    """
    chain = ole._mini_chain(e["isect_start"])
    needed = _math.ceil(len(new_data) / ole.mss)
    current = len(chain)

    if needed > current:
        extra = needed - current
        free = [i for i, v in enumerate(ole.minifat) if v == 0xFFFFFFFF]
        if len(free) < extra:
            print(f"  ERR: not enough free mini-sectors ({len(free)} < {extra})")
            return False
        new_sects = free[:extra]
        # Extend chain: last current -> new_sects[0] -> ... -> ENDOFCHAIN
        extended = chain + new_sects
        for i, s in enumerate(extended):
            nxt = extended[i+1] if i+1 < len(extended) else 0xFFFFFFFE
            # Write mini-FAT entry at byte s*4 in the miniFAT sectors
            entry_off = s * 4
            mfat_chain = ole._chain(ole.fmini)
            si = entry_off // ole.ss
            so = entry_off % ole.ss
            if si < len(mfat_chain):
                struct.pack_into("<I", ole.raw, ole._soff(mfat_chain[si]) + so, nxt)
        chain = extended
        # May need to extend Root Entry size
        new_ms_end = (max(chain) + 1) * ole.mss
        if new_ms_end > ole.dir_entries[0]["size"]:
            root_sid = 0
            dc = ole._chain(ole.fdir)
            epp = ole.ss // DE_SIZE
            ts = dc[root_sid // epp]
            ao = ole._soff(ts) + (root_sid % epp) * DE_SIZE + 120
            struct.pack_into("<I", ole.raw, ao, new_ms_end)
            ole.dir_entries[0]["size"] = new_ms_end

    # Write data to mini-sectors
    padded = new_data + b'\x00' * (len(chain) * ole.mss - len(new_data))
    root = ole.dir_entries[0]
    root_chain = ole._chain(root["isect_start"])
    for i, ms in enumerate(chain):
        byte_off = ms * ole.mss
        si = byte_off // ole.ss
        so = byte_off % ole.ss
        if si >= len(root_chain):
            print(f"  ERR: mini-sector {ms} out of root chain range")
            return False
        file_off = ole._soff(root_chain[si]) + so
        ole.raw[file_off:file_off + ole.mss] = padded[i*ole.mss:(i+1)*ole.mss]

    # Update directory entry size
    dc = ole._chain(ole.fdir)
    epp = ole.ss // DE_SIZE
    ts = dc[e["sid"] // epp]
    ao = ole._soff(ts) + (e["sid"] % epp) * DE_SIZE + 120
    struct.pack_into("<I", ole.raw, ao, len(new_data))
    print(f"  OK mini: {e['name']!r}: {e['size']} -> {len(new_data)} bytes")
    return True

# Monkey-patch OLEPatcher.patch_stream to also handle mini-streams
_orig_patch_stream = OLEPatcher.patch_stream

def _new_patch_stream(self, name, new_data):
    e = self.find_entry(name)
    if e is None:
        print(f"  WARN: stream {name!r} not found"); return False
    if self._is_mini(e):
        return _patch_mini_stream(self, e, new_data)
    return _orig_patch_stream(self, name, new_data)

OLEPatcher.patch_stream = _new_patch_stream

if __name__ == "__main__":
    main()
