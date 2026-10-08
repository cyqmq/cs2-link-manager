"""Best-effort .NET dependency inspection for CounterStrikeSharp plugins.

This module has two jobs:

* ``read_dotnet_assembly_version`` — parse the Assembly version out of a .NET
  DLL using only the standard library. It is a minimal, defensive ECMA-335
  metadata reader: on any parse error it returns ``None`` so callers can
  degrade gracefully.
* ``read_api_dependency`` — read the ``CounterStrikeSharp.API`` version
 declared by a plugin's ``.deps.json`` file.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

CSS_API_ASSEMBLY = "CounterStrikeSharp.API"


def read_dotnet_assembly_version(dll_path: str | Path) -> str | None:
    """Read ``major.minor.build.revision`` from a .NET assembly.

    Returns ``None`` when the file is not a readable .NET assembly or any
    parsing step fails. This is best-effort and never raises.
    """
    try:
        data = Path(dll_path).read_bytes()
    except OSError:
        return None
    return _parse_assembly_version(data)

def _parse_assembly_version(data: bytes) -> str | None:
    try:
        if len(data) < 0x40 or data[:2] != b"MZ":
            return None
        pe_off = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_off + 24 > len(data) or data[pe_off : pe_off + 4] != b"PE\0\0":
            return None
        coff = pe_off + 4
        num_sections = struct.unpack_from("<H", data, coff + 2)[0]
        opt = coff + 20
        magic = struct.unpack_from("<H", data, opt)[0]
        if magic not in (0x10B, 0x20B):  # PE32 / PE32+
            return None
        # Data directories start at the same offset (96) for both formats.
        dd_start = opt + 96
        if dd_start + 16 * 8 > len(data):
            return None
        cli_rva = struct.unpack_from("<I", data, dd_start + 14 * 8)[0]
        if cli_rva == 0:
            return None
        sec_start = dd_start + 16 * 8
        cli_off = _rva_to_offset(data, cli_rva, num_sections, sec_start)
        if cli_off is None:
            return None
        # IMAGE_COR20_HEADER: cb(4) major(2) minor(2) MetaData RVA(4) at +8.
        meta_rva = struct.unpack_from("<I", data, cli_off + 8)[0]
        meta_off = _rva_to_offset(data, meta_rva, num_sections, sec_start)
        if meta_off is None:
            return None
        return _parse_metadata_root(data, meta_off)
    except (struct.error, IndexError, ValueError):
        return None


def _rva_to_offset(
    data: bytes, rva: int, num_sections: int, sec_start: int
) -> int | None:
    """Translate an RVA to a file offset using the PE section table."""
    for i in range(num_sections):
        base = sec_start + i * 40
        if base + 40 > len(data):
            return None
        virtual_size = struct.unpack_from("<I", data, base + 8)[0]
        virtual_addr = struct.unpack_from("<I", data, base + 12)[0]
        raw_size = struct.unpack_from("<I", data, base + 16)[0]
        raw_ptr = struct.unpack_from("<I", data, base + 20)[0]
        size = max(virtual_size, raw_size)
        if virtual_addr <= rva < virtual_addr + size:
            offset = raw_ptr + (rva - virtual_addr)
            return offset if offset < len(data) else None
    return None


def _parse_metadata_root(data: bytes, off: int) -> str | None:
    if off + 16 > len(data):
        return None
    if struct.unpack_from("<I", data, off)[0] != 0x424A5342:  # BSJB
        return None
    version_len = struct.unpack_from("<I", data, off + 12)[0]
    streams_pos = off + 16 + version_len
    if streams_pos + 4 > len(data):
        return None
    _flags, num_streams = struct.unpack_from("<HH", data, streams_pos)
    pos = streams_pos + 4
    tilde_off = None
    for _ in range(num_streams):
        if pos + 8 > len(data):
            return None
        stream_off = struct.unpack_from("<I", data, pos)[0]
        stream_size = struct.unpack_from("<I", data, pos + 4)[0]
        name_pos = pos + 8
        end = data.index(b"\0", name_pos)
        name = data[name_pos:end].decode("ascii", errors="replace")
        if name == "#~":
            tilde_off = (off + stream_off, stream_size)
            break
        pos = (end + 1 + 3) & ~3  # name is null-terminated and padded to 4
    if tilde_off is None:
        return None
    return _parse_tilde_stream(data, tilde_off[0], tilde_off[1])


def _parse_tilde_stream(data: bytes, off: int, size: int) -> str | None:
    """Parse the #~ metadata table stream and return the Assembly version."""
    if size < 24 or off + 24 > len(data):
        return None
    heap_sizes = data[off + 6]
    valid = struct.unpack_from("<Q", data, off + 8)[0]
    row_counts_start = off + 24
    row_counts: dict[int, int] = {}
    pos = row_counts_start
    for table_id in range(64):
        if not (valid >> table_id) & 1:
            continue
        if pos + 4 > len(data):
            return None
        row_counts[table_id] = struct.unpack_from("<I", data, pos)[0]
        pos += 4

    if 0x20 not in row_counts or row_counts[0x20] == 0:
        return None

    # Find where the Assembly table rows start by summing the sizes of all
    # tables that come before it in table-ID order.
    table_data_start = pos
    assembly_offset = table_data_start
    for table_id in sorted(row_counts):
        if table_id == 0x20:
            break
        assembly_offset += _table_row_size(table_id, heap_sizes, row_counts) * row_counts[table_id]

    row_size = _table_row_size(0x20, heap_sizes, row_counts)
    if assembly_offset + row_size > len(data):
        return None
    major, minor, build, revision = struct.unpack_from(
        "<HHHH", data, assembly_offset + 4
    )
    return f"{major}.{minor}.{build}.{revision}"


# ---------------------------------------------------------------------------
# ECMA-335 table row sizes (II.22). Index sizes depend on the heap sizes byte
# and on the row counts of referenced tables.
# ---------------------------------------------------------------------------

def _table_row_size(table_id: int, heap_sizes: int, row_counts: dict[int, int]) -> int:
    """Return the row size in bytes for metadata table ``table_id``."""

    def rid(t: int) -> int:
        return 4 if row_counts.get(t, 0) > 0xFFFF else 2

    def idx(bit: int) -> int:
        return 4 if heap_sizes & bit else 2

    def coded(tag_bits: int, tables: list[int]) -> int:
        max_rows = max((row_counts.get(t, 0) for t in tables), default=0)
        max_token = (max_rows << tag_bits) | ((1 << tag_bits) - 1)
        return 4 if max_token >= 0x10000 else 2

    str_i = idx(0x01)
    guid_i = idx(0x02)
    blob_i = idx(0x04)

    if table_id == 0x00:  # Module
        return 2 + str_i + 3 * guid_i
    if table_id == 0x01:  # TypeRef
        return coded(2, [0x00, 0x01, 0x1A, 0x23]) + 2 * str_i
    if table_id == 0x02:  # TypeDef
        return 4 + 2 * str_i + coded(2, [0x02, 0x01, 0x1B]) + rid(0x04) + rid(0x06)
    if table_id == 0x03:  # FieldPtr
        return rid(0x04)
    if table_id == 0x04:  # Field
        return 2 + str_i + blob_i
    if table_id == 0x05:  # MethodPtr
        return rid(0x06)
    if table_id == 0x06:  # MethodDef
        return 8 + str_i + blob_i + rid(0x08)
    if table_id == 0x07:  # ParamPtr
        return rid(0x08)
    if table_id == 0x08:  # Param
        return 4 + str_i
    if table_id == 0x09:  # InterfaceImpl
        return rid(0x02) + coded(2, [0x02, 0x01, 0x1B])
    if table_id == 0x0A:  # MemberRef
        return coded(3, [0x02, 0x01, 0x1A, 0x06, 0x1B]) + str_i + blob_i
    if table_id == 0x0B:  # Constant
        return 2 + coded(2, [0x04, 0x08, 0x17]) + blob_i
    if table_id == 0x0C:  # CustomAttribute
        return (
            coded(5, [0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00, 0x0E, 0x17,
                      0x14, 0x11, 0x1A, 0x1B, 0x20, 0x23, 0x26, 0x27, 0x28, 0x2A,
                      0x2C, 0x2B])
            + coded(3, [0x06, 0x0A])
            + blob_i
        )
    if table_id == 0x0D:  # FieldMarshal
        return coded(1, [0x04, 0x08]) + blob_i
    if table_id == 0x0E:  # DeclSecurity
        return 2 + coded(2, [0x02, 0x06, 0x20]) + blob_i
    if table_id == 0x0F:  # ClassLayout
        return 6 + rid(0x02)
    if table_id == 0x10:  # FieldLayout
        return 4 + rid(0x04)
    if table_id == 0x11:  # StandAloneSig
        return blob_i
    if table_id == 0x12:  # EventMap
        return rid(0x02) + rid(0x14)
    if table_id == 0x13:  # EventPtr
        return rid(0x14)
    if table_id == 0x14:  # Event
        return 2 + str_i + coded(2, [0x02, 0x01, 0x1B])
    if table_id == 0x15:  # PropertyMap
        return rid(0x02) + rid(0x17)
    if table_id == 0x16:  # PropertyPtr
        return rid(0x17)
    if table_id == 0x17:  # Property
        return 2 + str_i + blob_i
    if table_id == 0x18:  # MethodSemantics
        return 2 + rid(0x06) + coded(1, [0x14, 0x17])
    if table_id == 0x19:  # MethodImpl
        return rid(0x02) + 2 * rid(0x06)
    if table_id == 0x1A:  # ModuleRef
        return str_i
    if table_id == 0x1B:  # TypeSpec
        return blob_i
    if table_id == 0x1C:  # ImplMap
        return 2 + coded(1, [0x04, 0x06]) + str_i + rid(0x1A)
    if table_id == 0x1D:  # FieldRVA
        return 4 + rid(0x04)
    if table_id == 0x1E:  # ENCLog
        return 8
    if table_id == 0x1F:  # ENCMap
        return 4
    if table_id == 0x20:  # Assembly
        return 16 + blob_i + 2 * str_i
    if table_id == 0x21:  # AssemblyProcessor
        return 4
    if table_id == 0x22:  # AssemblyOS
        return 12
    if table_id == 0x23:  # AssemblyRef
        return 12 + 2 * blob_i + 2 * str_i
    if table_id == 0x24:  # AssemblyRefProcessor
        return 4 + rid(0x23)
    if table_id == 0x25:  # AssemblyRefOS
        return 12 + rid(0x23)
    if table_id == 0x26:  # File
        return 4 + str_i + blob_i
    if table_id == 0x27:  # ExportedType
        return 8 + 2 * str_i + coded(2, [0x26, 0x23, 0x27])
    if table_id == 0x28:  # ManifestResource
        return 8 + str_i + coded(2, [0x26, 0x23, 0x27])
    if table_id == 0x29:  # NestedClass
        return 2 * rid(0x02)
    if table_id == 0x2A:  # GenericParam
        return 4 + coded(1, [0x02, 0x06]) + str_i
    if table_id == 0x2B:  # MethodSpec
        return coded(1, [0x06, 0x0A]) + blob_i
    if table_id == 0x2C:  # GenericParamConstraint
        return rid(0x2A) + coded(2, [0x02, 0x01, 0x1B])
    return 0


# ---------------------------------------------------------------------------
# .deps.json dependency extraction
# ---------------------------------------------------------------------------

def read_api_dependency(files_root: str | Path) -> str | None:
    """Return the CounterStrikeSharp.API version declared in a plugin package.

    Scans every ``*.deps.json`` under ``files_root`` and returns the version
    of the first ``CounterStrikeSharp.API`` reference found, or ``None``.
    """
    root = Path(files_root)
    if not root.is_dir():
        return None
    for deps_file in sorted(root.rglob("*.deps.json")):
        try:
            data = json.loads(deps_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        libraries = data.get("libraries", {})
        if not isinstance(libraries, dict):
            continue
        for key in libraries:
            if isinstance(key, str) and key.startswith(CSS_API_ASSEMBLY + "/"):
                return key.split("/", 1)[1]
    return None