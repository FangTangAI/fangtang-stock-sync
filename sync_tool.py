import base64
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, StringVar, Toplevel, Listbox, filedialog, font, messagebox, ttk

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import customtkinter as ctk


APP_TITLE = "方塘自选股同步工具"
APP_AUTHOR = "作者：方塘    公众号：问道半亩方塘    邮箱：fangtangchn@163.com"
COLOR_PRIMARY = "#1677ff"
COLOR_PRIMARY_HOVER = "#0f5fd1"
COLOR_SELECT = "#dbeafe"
COLOR_SELECT_TEXT = "#0f172a"
FONT_FAMILY = "Microsoft YaHei UI"
FONT_TITLE = (FONT_FAMILY, 20, "bold")
FONT_SECTION = (FONT_FAMILY, 13, "bold")
FONT_NORMAL = (FONT_FAMILY, 12)
FONT_SMALL = (FONT_FAMILY, 10)
FONT_TABLE = (FONT_FAMILY, 17)
FONT_TABLE_HEAD = (FONT_FAMILY, 17, "bold")
FONT_ACCOUNT_LIST = (FONT_FAMILY, 15)
FONT_MONO = ("Consolas", 12)
DEFAULT_WH_DIR = Path(r"C:\Users\pengy\Desktop\wh7个性化设置\PageBak\Page\SelfMess")
DEFAULT_WH_INSTALL_DIR = Path(r"C:\Software\wh6模拟版")
DEFAULT_THS_INSTALL_DIR = Path(r"C:\software\同花顺")
DEFAULT_TDX_INSTALL_DIR = Path(r"C:\Software\new_tdx_mock")
STATE_FILE = Path.home() / ".fangtang_stock_sync_tool.json"
SOFTWARES = ("同花顺", "文华财经", "通达信")
_WH_CODE_CACHE: dict[str, tuple[dict[tuple[int, int], "WenhuaCodeEntry"], dict[str, "WenhuaCodeEntry"]]] = {}
_STOCK_NAME_CACHE: dict[tuple[str, ...], dict[str, str]] = {}


@dataclass
class Block:
    block_id: str
    name: str
    path: Path
    codes: list[str]
    markets: dict[str, str]


@dataclass
class WenhuaCodeEntry:
    table: int
    internal_id: int
    code: str
    name: str


def today() -> str:
    return time.strftime("%Y%m%d")


def unique_codes(codes: list[str]) -> list[str]:
    seen = set()
    out = []
    for code in codes:
        code = normalize_code(code)
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def normalize_code(code: str) -> str:
    code = str(code).strip().upper()
    if len(code) == 6 and code.isdigit():
        return code
    if code.isdigit() and len(code) < 6:
        return code.zfill(6)
    return code


def guess_market(code: str) -> str:
    code = normalize_code(code)
    if code.startswith(("60", "68", "51", "58")):
        return "17"
    if code.startswith(("00", "30", "15", "16", "18", "12")):
        return "33"
    if code.startswith(("8", "4")) and len(code) == 6:
        return "48"
    return "33"


def market_label(market: str) -> str:
    if market in {"17", "22", "1"}:
        return "SH"
    if market in {"33", "0"}:
        return "SZ"
    if market in {"48", "2"}:
        return "BJ"
    return market or ""


def tdx_market_prefix(code: str, market: str | None = None) -> str:
    label = market_label(market or guess_market(code))
    if label == "SH":
        return "1"
    if label == "BJ":
        return "2"
    return "0"


def tdx_market_to_common(prefix: str) -> str:
    if prefix == "1":
        return "17"
    if prefix == "2":
        return "48"
    return "33"


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(data: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def saved_user_path(value: str) -> str:
    if not value:
        return ""
    name = Path(value).name.lower()
    if name in {"custom_block", "selfmess", "blocknew"}:
        return ""
    if value in {str(DEFAULT_THS_INSTALL_DIR), str(DEFAULT_WH_INSTALL_DIR), str(DEFAULT_TDX_INSTALL_DIR)}:
        return ""
    return value


def safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def block_file_name(block_id: str) -> str:
    try:
        return str(int(block_id, 16))
    except ValueError:
        return block_id


def block_ini_id(path_name: str) -> str:
    try:
        return format(int(path_name), "X")
    except ValueError:
        return path_name


def parse_ths_context(context: str) -> tuple[list[str], dict[str, str]]:
    items = [x for x in context.split(",") if x]
    codes = []
    markets = {}
    for item in items:
        if ":" not in item:
            continue
        market, code = item.split(":", 1)
        code = normalize_code(code)
        codes.append(code)
        markets[code] = market
    return unique_codes(codes), markets


def build_ths_ini_context(codes: list[str], markets: dict[str, str]) -> str:
    return ",".join(f"{markets.get(c, guess_market(c))}:{c}" for c in unique_codes(codes)) + ",,"


def load_stock_names(paths: list[Path]) -> dict[str, str]:
    key = tuple(sorted(str(path.resolve()) if path.exists() else str(path) for path in paths if path))
    if key in _STOCK_NAME_CACHE:
        return _STOCK_NAME_CACHE[key]
    names: dict[str, str] = {}
    for path in paths:
        try:
            _, wh_by_code = load_wenhua_code_table(path)
        except Exception:
            wh_by_code = {}
        for code, entry in wh_by_code.items():
            if entry.name:
                names.setdefault(code, entry.name)
    roots = []
    for path in paths:
        if not path:
            continue
        candidates = [path]
        if path.name == "custom_block":
            candidates.append(path.parent.parent)
        candidates.extend(list(path.parents)[:3])
        roots.extend(candidates)
    for root in roots:
        stock_dir = root / "stockname"
        if not stock_dir.exists():
            continue
        for file_path in stock_dir.glob("stockname_*_*.txt"):
            try:
                text = file_path.read_text("gbk", errors="ignore")
            except Exception:
                continue
            for line in text.splitlines():
                if "=" not in line:
                    continue
                code, value = line.split("=", 1)
                code = normalize_code(code)
                if not code:
                    continue
                name = value.split("|", 1)[0].strip()
                if name and code not in names:
                    names[code] = name
    for path in paths:
        root = TdxStore.install_root_from_path(path)
        if not root:
            continue
        for code, name in load_tdx_names(root).items():
            names.setdefault(code, name)
    _STOCK_NAME_CACHE[key] = names
    return names


def clear_runtime_caches() -> None:
    _STOCK_NAME_CACHE.clear()


def read_ini_sections(path: Path, encoding: str = "gbk") -> tuple[list[str], dict[str, dict[str, str]]]:
    lines = path.read_text(encoding=encoding, errors="ignore").splitlines()
    current = ""
    sections: dict[str, dict[str, str]] = {}
    order = []
    for line in lines:
        raw = line.strip()
        if raw.startswith("[") and raw.endswith("]"):
            current = raw[1:-1]
            if current not in sections:
                sections[current] = {}
                order.append(current)
        elif current and "=" in line:
            key, value = line.split("=", 1)
            sections[current][key.strip()] = value.strip()
    return order, sections


def update_ini_value(path: Path, section: str, key: str, value: str, encoding: str = "gbk") -> None:
    lines = path.read_text(encoding=encoding, errors="ignore").splitlines()
    out = []
    current = ""
    in_section = False
    section_found = False
    key_written = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not key_written:
                out.append(f"{key}={value}")
                key_written = True
            current = stripped[1:-1]
            in_section = current == section
            section_found = section_found or in_section
            out.append(line)
            continue
        if in_section and line.split("=", 1)[0].strip() == key and "=" in line:
            out.append(f"{key}={value}")
            key_written = True
        else:
            out.append(line)
    if not section_found:
        out.extend([f"[{section}]", f"{key}={value}"])
    elif in_section and not key_written:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding=encoding)


def encode_name(name: str) -> str:
    return base64.b64encode(name.encode("gbk", "ignore")).decode("ascii")


def decode_name(value: str) -> str:
    if not value:
        return ""
    try:
        raw = base64.b64decode(value + "===")
        for enc in ("gbk", "utf-8"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
    except Exception:
        return ""
    return ""


def read_json_text(path: Path):
    for enc in ("utf-8", "gbk", "ansi"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            continue
    raise ValueError(f"无法读取 JSON：{path}")


def read_json_list(path: Path) -> list:
    value = read_json_text(path)
    return value if isinstance(value, list) else []


def build_ths_self_stock_rows(path: Path, codes: list[str], markets: dict[str, str]) -> list[dict]:
    old_rows = []
    if path.exists():
        try:
            old_rows = read_json_text(path)
        except Exception:
            old_rows = []
    old_by_code = {}
    if isinstance(old_rows, list):
        for row in old_rows:
            if isinstance(row, dict):
                code = normalize_code(row.get("C", ""))
                if code:
                    old_by_code[code] = row
    rows = []
    for code in unique_codes(codes):
        old = dict(old_by_code.get(code, {}))
        old["C"] = code
        old["M"] = str(markets.get(code) or old.get("M") or guess_market(code))
        old.setdefault("P", "0")
        old["T"] = today()
        rows.append(old)
    return rows


class TonghuashunStore:
    def __init__(self, root: Path):
        self.root = root
        self.account_dir = root.parent if root.is_dir() and root.name == "custom_block" else root.parent
        self.stock_block_ini = self.account_dir / "StockBlock.ini"

    @staticmethod
    def is_account_dir(path: Path) -> bool:
        if (path / "custom_block").exists():
            return True
        self_stock = path / "SelfStockInfo.json"
        if not self_stock.exists():
            return False
        try:
            return isinstance(read_json_text(self_stock), list)
        except Exception:
            return False

    @staticmethod
    def find_accounts(exe_path: str) -> list[Path]:
        p = Path(exe_path)
        if p.is_file() and p.name.lower() == "selfstockinfo.json":
            return [p.parent]
        bases = [p.parent if p.is_file() else p]
        if p.is_file() and p.parent.parent != p.parent:
            bases.append(p.parent.parent)
        accounts: list[Path] = []
        seen = set()
        for base in bases:
            candidates = [base]
            try:
                candidates.extend([x for x in base.iterdir() if x.is_dir()])
            except Exception:
                pass
            try:
                candidates.extend([x.parent for x in base.rglob("SelfStockInfo.json")])
            except Exception:
                pass
            for candidate in candidates:
                if TonghuashunStore.is_account_dir(candidate):
                    key = str(candidate.resolve())
                    if key not in seen:
                        seen.add(key)
                        accounts.append(candidate)
        return accounts

    @staticmethod
    def locate(exe_path: str) -> Path | None:
        p = Path(exe_path)
        if p.is_file() and p.name.lower() == "selfstockinfo.json":
            return p
        if p.is_dir() and p.name == "custom_block":
            return p
        if p.is_dir() and ((p / "custom_block").exists() or (p / "SelfStockInfo.json").exists()):
            cb = p / "custom_block"
            return cb if cb.exists() else p / "SelfStockInfo.json"
        accounts = TonghuashunStore.find_accounts(exe_path)
        if accounts:
            cb = accounts[0] / "custom_block"
            return cb if cb.exists() else accounts[0] / "SelfStockInfo.json"
        bases = [p.parent if p.is_file() else p]
        if p.is_file() and p.parent.parent != p.parent:
            bases.append(p.parent.parent)
        for base in bases:
            cb = base / "custom_block"
            if cb.exists():
                return cb
            try:
                for found in base.rglob("custom_block"):
                    if found.is_dir():
                        return found
            except Exception:
                pass
        return None

    def list_blocks(self) -> list[Block]:
        if self.root.is_file() and self.root.name.lower() == "selfstockinfo.json":
            rows = read_json_list(self.root)
            codes = [normalize_code(x.get("C", "")) for x in rows if isinstance(x, dict)]
            markets = {normalize_code(x.get("C", "")): str(x.get("M", "")) for x in rows if isinstance(x, dict)}
            return [Block("SelfStockInfo", "同花顺自选股", self.root, unique_codes(codes), markets)]

        blocks = []
        self_stock = self.account_dir / "SelfStockInfo.json"
        if self_stock.exists():
            try:
                rows = read_json_list(self_stock)
                codes = [normalize_code(x.get("C", "")) for x in rows if isinstance(x, dict)]
                markets = {normalize_code(x.get("C", "")): str(x.get("M", "")) for x in rows if isinstance(x, dict)}
                blocks.append(Block("SelfStockInfo", "同花顺自选股", self_stock, unique_codes(codes), markets))
            except Exception:
                pass

        if self.stock_block_ini.exists():
            _, sections = read_ini_sections(self.stock_block_ini)
            active_ids = list(sections.get("@7", {}).keys())
            names = sections.get("BLOCK_NAME_MAP_TABLE", {})
            contexts = sections.get("BLOCK_STOCK_CONTEXT", {})
            for block_id in active_ids:
                file_path = self.root / block_file_name(block_id)
                context = contexts.get(block_id, "")
                codes, markets = parse_ths_context(context)
                if not context and file_path.exists():
                    try:
                        obj = read_json_text(file_path)
                        codes_part, markets_part = (obj.get("context", "").split(",", 1) + [""])[:2]
                        codes = [normalize_code(x) for x in codes_part.split("|") if x]
                        mkts = [x for x in markets_part.split("|") if x]
                        markets = {code: (mkts[i] if i < len(mkts) else guess_market(code)) for i, code in enumerate(codes)}
                    except Exception:
                        pass
                name = names.get(block_id, "")
                if not name and file_path.exists():
                    try:
                        name = decode_name(read_json_text(file_path).get("ln", ""))
                    except Exception:
                        pass
                blocks.append(Block(block_id, name or block_id, file_path, unique_codes(codes), markets))
            return blocks

        for path in sorted(self.root.iterdir(), key=lambda x: (not x.name.isdigit(), x.name)):
            if not path.is_file() or not path.name.isdigit():
                continue
            try:
                obj = read_json_text(path)
            except Exception:
                continue
            name = decode_name(obj.get("ln", "")) or path.name
            context = obj.get("context", "")
            codes_part, markets_part = (context.split(",", 1) + [""])[:2]
            codes = [normalize_code(x) for x in codes_part.split("|") if x]
            mkts = [x for x in markets_part.split("|") if x]
            markets = {code: (mkts[i] if i < len(mkts) else guess_market(code)) for i, code in enumerate(codes)}
            blocks.append(Block(block_ini_id(path.name), name, path, unique_codes(codes), markets))
        return blocks

    def write_block(self, block: Block, codes: list[str], markets: dict[str, str] | None = None, mode: str = "replace") -> None:
        markets = markets or {}
        if mode == "append":
            codes = unique_codes(block.codes + codes)
        else:
            codes = unique_codes(codes)
        if block.path.name.lower() == "selfstockinfo.json":
            backup_file(block.path)
            rows = build_ths_self_stock_rows(block.path, codes, markets)
            block.path.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            return
        if not block.path.exists():
            block.path = self.root / block_file_name(block.block_id)
        obj = read_json_text(block.path) if block.path.exists() else {"ln": encode_name(block.name), "xn": "", "context": ""}
        market_list = [markets.get(c) or block.markets.get(c) or guess_market(c) for c in codes]
        obj["ln"] = obj.get("ln") or encode_name(block.name)
        obj["context"] = "|".join(codes) + "|," + "|".join(market_list) + "|"
        if block.path.exists():
            backup_file(block.path)
        block.path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if self.stock_block_ini.exists():
            backup_file(self.stock_block_ini)
            update_ini_value(self.stock_block_ini, "BLOCK_STOCK_CONTEXT", block.block_id, build_ths_ini_context(codes, {c: market_list[i] for i, c in enumerate(codes)}))


def read_varint(data: bytes, i: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while i < len(data):
        b = data[i]
        i += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, i
        shift += 7
    raise ValueError("截断的 varint")


def write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_field(field_no: int, wire_type: int) -> bytes:
    return write_varint((field_no << 3) | wire_type)


def pb_string(field_no: int, value: bytes) -> bytes:
    return pb_field(field_no, 2) + write_varint(len(value)) + value


def pb_int(field_no: int, value: int) -> bytes:
    return pb_field(field_no, 0) + write_varint(value)


def protobuf_fields(data: bytes):
    i = 0
    while i < len(data):
        try:
            tag, i = read_varint(data, i)
        except Exception:
            break
        field_no = tag >> 3
        wire = tag & 7
        if wire == 0:
            try:
                value, i = read_varint(data, i)
            except Exception:
                break
            yield field_no, wire, value
        elif wire == 2:
            try:
                length, i = read_varint(data, i)
            except Exception:
                break
            if i + length > len(data):
                break
            value = data[i:i + length]
            i += length
            yield field_no, wire, value
        elif wire == 5:
            if i + 4 > len(data):
                break
            yield field_no, wire, data[i:i + 4]
            i += 4
        elif wire == 1:
            if i + 8 > len(data):
                break
            yield field_no, wire, data[i:i + 8]
            i += 8
        else:
            break


def decode_gbk(data: bytes) -> str:
    try:
        return data.decode("gbk")
    except UnicodeDecodeError:
        try:
            return data.decode("gb18030")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="ignore")


def parse_wenhua_code_record(data: bytes, table: int) -> WenhuaCodeEntry | None:
    fields = {}
    nested = {}
    for field_no, wire, value in protobuf_fields(data):
        if wire == 0:
            fields[field_no] = value
        elif wire == 2 and isinstance(value, bytes):
            if field_no == 7:
                for n_field, n_wire, n_value in protobuf_fields(value):
                    if n_wire == 0:
                        nested[n_field] = n_value
                    elif n_wire == 2 and isinstance(n_value, bytes):
                        nested[n_field] = decode_gbk(n_value)
            else:
                fields[field_no] = decode_gbk(value)
    internal_id = fields.get(2)
    if internal_id is None:
        return None
    if nested:
        code = str(nested.get(3, "")).strip()
        name = str(nested.get(4, "")).strip()
    else:
        code = str(fields.get(4, "")).strip()
        name = str(fields.get(3, "")).strip()
    if not code:
        return None
    return WenhuaCodeEntry(table, internal_id, normalize_code(code), name)


def find_wenhua_install(start: Path | None = None) -> Path | None:
    candidates = []
    if start:
        p = start if start.is_dir() else start.parent
        candidates.extend([p, *list(p.parents)])
    for candidate in candidates:
        if (candidate / "WHData" / "CodeTable").exists():
            return candidate
    software = Path("C:/Software")
    if software.exists():
        for child in software.iterdir():
            if (child / "mytrader_wh.exe").exists() and (child / "WHData" / "CodeTable").exists():
                return child
    return None


def load_wenhua_code_table(start: Path | None = None) -> tuple[dict[tuple[int, int], WenhuaCodeEntry], dict[str, WenhuaCodeEntry]]:
    install = find_wenhua_install(start)
    by_key: dict[tuple[int, int], WenhuaCodeEntry] = {}
    by_code: dict[str, WenhuaCodeEntry] = {}
    if not install:
        return by_key, by_code
    cache_key = str(install.resolve())
    if cache_key in _WH_CODE_CACHE:
        return _WH_CODE_CACHE[cache_key]
    root = install / "WHData" / "CodeTable"
    for path in root.glob("*.dat"):
        try:
            table = int(path.stem)
        except ValueError:
            continue
        data = path.read_bytes()
        for field_no, wire, value in protobuf_fields(data):
            if wire != 2 or not isinstance(value, bytes):
                continue
            entry = parse_wenhua_code_record(value, table)
            if not entry:
                continue
            by_key[(entry.table, entry.internal_id)] = entry
            by_code.setdefault(entry.code, entry)
    _WH_CODE_CACHE[cache_key] = (by_key, by_code)
    return by_key, by_code


def wh_code_to_plain(market: int | None, value: int | None) -> str:
    if value is None:
        return ""
    if market == 1:
        return f"{value:06d}"
    if 30000 <= value < 40000:
        return f"{value + 655000:06d}"
    if 10000 <= value < 100000:
        return f"{value + 590000:06d}"
    return f"{value:06d}"


def plain_to_wh(code: str) -> tuple[int | None, int]:
    code = normalize_code(code)
    if code.startswith("688") and code.isdigit():
        return None, int(code) - 655000
    if code.startswith("6") and code.isdigit():
        return None, int(code) - 590000
    if code.isdigit():
        return 1, int(code)
    return None, int("".join(ch for ch in code if ch.isdigit()) or "0")


class WenhuaStore:
    def __init__(self, root: Path):
        self.root = root
        self.code_by_key, self.code_by_code = load_wenhua_code_table(root)

    @staticmethod
    def locate(exe_path: str) -> Path | None:
        p = Path(exe_path)
        bases = [p.parent if p.is_file() else p]
        if p.is_file() and p.parent.parent != p.parent:
            bases.append(p.parent.parent)
        for base in bases:
            direct = base / "PageBak" / "Page" / "SelfMess"
            if direct.exists():
                return direct
            direct = base / "pageBack" / "Page" / "SelfMess"
            if direct.exists():
                return direct
            direct = base / "page" / "SelfMess"
            if direct.exists():
                return direct
            try:
                for found in base.rglob("SelfMess"):
                    if found.is_dir() and found.parent.name.lower() == "page":
                        return found
            except Exception:
                pass
        return None

    def list_blocks(self) -> list[Block]:
        blocks = []
        self_stock = self.root.parent / "z061.dat"
        if self_stock.exists():
            try:
                codes = self.read_codes(self_stock)
                blocks.append(Block("__self__", "文华自选股", self_stock, codes, {c: guess_market(c) for c in codes}))
            except Exception:
                pass
        for path in sorted(self.root.glob("*.dat"), key=lambda x: x.name):
            try:
                codes = self.read_codes(path)
            except Exception:
                continue
            blocks.append(Block(path.stem, path.stem, path, codes, {c: guess_market(c) for c in codes}))
        return blocks

    def read_codes(self, path: Path) -> list[str]:
        data = path.read_bytes()
        i = 0
        codes = []
        while i < len(data):
            tag, i = read_varint(data, i)
            field_no = tag >> 3
            wire = tag & 7
            if wire == 2:
                length, i = read_varint(data, i)
                value = data[i:i + length]
                i += length
                if field_no == 3:
                    market = None
                    num = None
                    j = 0
                    while j < len(value):
                        t, j = read_varint(value, j)
                        f = t >> 3
                        w = t & 7
                        if w == 0:
                            v, j = read_varint(value, j)
                            if f == 1:
                                market = v
                            elif f == 2:
                                num = v
                        else:
                            break
                    table = market if market is not None else 0
                    entry = self.code_by_key.get((table, num)) if num is not None else None
                    code = entry.code if entry else wh_code_to_plain(market, num)
                    if code:
                        codes.append(code)
            elif wire == 0:
                _, i = read_varint(data, i)
            else:
                break
        return unique_codes(codes)

    def write_block(self, block: Block, codes: list[str], markets: dict[str, str] | None = None, mode: str = "replace") -> None:
        if mode == "append":
            codes = unique_codes(block.codes + codes)
        else:
            codes = unique_codes(codes)
        backup_file(block.path)
        if block.block_id == "__self__":
            title = b"z061"
        else:
            title = f"SelfMess\\{block.name}".encode("gbk", "ignore")
        out = bytearray(pb_string(2, title))
        for code in codes:
            entry = self.code_by_code.get(normalize_code(code))
            if entry:
                market = entry.table if entry.table != 0 else None
                num = entry.internal_id
            else:
                market, num = plain_to_wh(code)
            rec = bytearray()
            if market is not None:
                rec += pb_int(1, market)
            rec += pb_int(2, num)
            out += pb_string(3, bytes(rec))
        block.path.write_bytes(bytes(out))


def parse_tdx_block_cfg(root: Path) -> dict[str, str]:
    cfg = root / "blocknew.cfg"
    if not cfg.exists():
        return {}
    data = cfg.read_bytes()
    names: dict[str, str] = {}
    chunk = 120
    for i in range(0, len(data), chunk):
        part = data[i:i + chunk]
        if not part.strip(b"\x00"):
            continue
        halves = part.split(b"\x00" * 2, 1)
        text = decode_gbk(part).replace("\x00", " ").split()
        if len(text) >= 2:
            names[text[-1].upper()] = text[0]
            continue
        if halves:
            decoded = decode_gbk(halves[0]).replace("\x00", "").strip()
            if decoded:
                names[decoded.upper()] = decoded
    return names


def load_tdx_names(root: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    stockname = root / "T0002" / "hq_cache" / "code2name.ini"
    if not stockname.exists():
        return names
    try:
        for line in stockname.read_text("gbk", errors="ignore").splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 2 and len(parts[0]) == 6 and parts[0].isdigit():
                names[normalize_code(parts[0])] = parts[1]
    except Exception:
        pass
    return names


class TdxStore:
    def __init__(self, root: Path):
        self.root = root
        self.install_root = self.install_root_from_path(root) or root
        self.block_names = parse_tdx_block_cfg(root)

    @staticmethod
    def install_root_from_path(path: Path | None) -> Path | None:
        if not path:
            return None
        p = path
        candidates = [p.parent if p.is_file() else p, *list((p.parent if p.is_file() else p).parents)]
        for candidate in candidates:
            if (candidate / "TdxW.exe").exists() and (candidate / "T0002" / "blocknew").exists():
                return candidate
            if candidate.name.lower() == "t0002" and (candidate / "blocknew").exists():
                return candidate.parent
        return None

    @staticmethod
    def locate(exe_path: str) -> Path | None:
        p = Path(exe_path)
        bases = [p.parent if p.is_file() else p]
        if p.is_file() and p.parent.parent != p.parent:
            bases.append(p.parent.parent)
        for base in bases:
            direct = base / "T0002" / "blocknew"
            if direct.exists():
                return direct
            if base.name.lower() == "blocknew":
                return base
            try:
                for found in base.rglob("blocknew"):
                    if found.is_dir() and found.parent.name.upper() == "T0002":
                        return found
            except Exception:
                pass
        return None

    def list_blocks(self) -> list[Block]:
        blocks: list[Block] = []
        system_blocks = {"FGBK", "GNBK", "HYBK", "HXGG"}
        for path in sorted(self.root.glob("*.blk"), key=lambda x: (x.stem.lower() != "zxg", x.stem.lower())):
            if path.parent.name.lower() == "lastsync":
                continue
            codes, markets = self.read_codes(path)
            stem = path.stem.upper()
            if stem in system_blocks:
                continue
            if stem == "ZXG":
                name = "通达信自选股"
            else:
                name = self.block_names.get(stem, path.stem)
            blocks.append(Block(stem, name, path, codes, markets))
        return blocks

    def read_codes(self, path: Path) -> tuple[list[str], dict[str, str]]:
        codes: list[str] = []
        markets: dict[str, str] = {}
        try:
            text = path.read_text("gbk", errors="ignore")
        except Exception:
            text = ""
        for raw in text.splitlines():
            item = raw.strip().upper()
            if not item:
                continue
            if len(item) >= 7 and item[0].isdigit() and item[1:7].isdigit():
                code = normalize_code(item[1:7])
                markets[code] = tdx_market_to_common(item[0])
                codes.append(code)
            elif len(item) == 6 and item.isdigit():
                code = normalize_code(item)
                markets[code] = guess_market(code)
                codes.append(code)
        return unique_codes(codes), markets

    def write_block(self, block: Block, codes: list[str], markets: dict[str, str] | None = None, mode: str = "replace") -> None:
        markets = markets or {}
        if mode == "append":
            codes = unique_codes(block.codes + codes)
        else:
            codes = unique_codes(codes)
        backup_file(block.path)
        lines = [tdx_market_prefix(code, markets.get(code) or block.markets.get(code)) + normalize_code(code) for code in codes]
        block.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="gbk")


def backup_file(path: Path) -> None:
    if not path.exists():
        return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    folder = path.parent / "_sync_backup" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, folder / path.name)


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1320x780")
        self.state = load_state()
        self.left_kind = StringVar(value=self.state.get("left_kind", "同花顺"))
        self.right_kind = StringVar(value=self.state.get("right_kind", "文华财经"))
        self.left_path = StringVar(value=saved_user_path(self.state.get("left_path", "")))
        self.right_path = StringVar(value=saved_user_path(self.state.get("right_path", "")))
        self.mode = StringVar(value="append")
        self.left_store = None
        self.right_store = None
        self.left_blocks: list[Block] = []
        self.right_blocks: list[Block] = []
        self.left_selected = None
        self.right_selected = None
        self.stock_names: dict[str, str] = {}
        self.build()
        self.status.set("请选择左右两侧程序后载入")

    def build(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.root.tk.call("tk", "scaling", 1.35)
        self.root.configure(fg_color="#f6f8fa")
        self.table_font = font.Font(family=FONT_TABLE[0], size=FONT_TABLE[1])
        self.table_head_font = font.Font(family=FONT_TABLE_HEAD[0], size=FONT_TABLE_HEAD[1], weight="bold")
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Stock.Treeview", rowheight=46, font=self.table_font, fieldbackground="#ffffff", background="#ffffff", foreground="#24292f", bordercolor="#d0d7de")
        style.map("Stock.Treeview", background=[("selected", COLOR_SELECT)], foreground=[("selected", COLOR_SELECT_TEXT)])
        style.configure("Stock.Treeview.Heading", font=self.table_head_font, background="#f3f4f6", foreground="#24292f")
        shell = ctk.CTkFrame(self.root, fg_color="#f6f8fa", corner_radius=0)
        shell.pack(fill=BOTH, expand=True, padx=14, pady=14)
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill=X, pady=(0, 10))
        ctk.CTkLabel(header, text=APP_TITLE, font=FONT_TITLE, text_color="#111827").pack(side=LEFT)
        top = ctk.CTkFrame(shell, fg_color="#ffffff", corner_radius=10, border_width=1, border_color="#d0d7de")
        top.pack(fill=X, pady=(0, 10), ipady=8)
        self.path_row(top, "左侧来源", self.left_kind, self.left_path, self.choose_left, self.load_left, "left")
        self.path_row(top, "右侧来源", self.right_kind, self.right_path, self.choose_right, self.load_right, "right")
        middle = ctk.CTkFrame(shell, fg_color="transparent")
        middle.pack(fill=BOTH, expand=True)
        self.left_box = self.block_panel(middle, "左侧板块", LEFT)
        center = ctk.CTkFrame(middle, fg_color="#ffffff", corner_radius=10, border_width=1, border_color="#d0d7de")
        center.pack(side=LEFT, fill="y")
        ctk.CTkLabel(center, text="同步方式", font=FONT_SECTION, text_color="#111827").pack(anchor="w", padx=16, pady=(16, 6))
        ctk.CTkRadioButton(center, text="补充式同步", font=FONT_NORMAL, variable=self.mode, value="append").pack(anchor="w", padx=16, pady=6)
        ctk.CTkRadioButton(center, text="覆盖式同步", font=FONT_NORMAL, variable=self.mode, value="replace").pack(anchor="w", padx=16, pady=6)
        ctk.CTkButton(center, text="向右同步", font=FONT_NORMAL, height=36, fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER, command=lambda: self.sync("left")).pack(fill=X, padx=14, pady=(22, 8))
        ctk.CTkButton(center, text="向左同步", font=FONT_NORMAL, height=36, fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER, command=lambda: self.sync("right")).pack(fill=X, padx=14, pady=6)
        ctk.CTkButton(center, text="重新载入数据", font=FONT_NORMAL, height=34, fg_color="#ffffff", text_color="#24292f", border_width=1, border_color="#d0d7de", hover_color="#f3f4f6", command=self.load_all).pack(fill=X, padx=14, pady=(26, 12))
        self.right_box = self.block_panel(middle, "右侧板块", LEFT)
        bottom = ctk.CTkFrame(shell, fg_color="#ffffff", corner_radius=10, border_width=1, border_color="#d0d7de")
        bottom.pack(fill=X)
        self.status = StringVar(value="就绪")
        ctk.CTkLabel(bottom, textvariable=self.status, font=FONT_NORMAL, text_color="#57606a", anchor="w").pack(side=LEFT, padx=12, pady=8)
        ctk.CTkLabel(bottom, text=APP_AUTHOR, text_color="#6b7280", font=FONT_SMALL).pack(side=RIGHT, padx=12, pady=8)

    def path_row(self, parent, label, kind_var, path_var, choose_cmd, load_cmd, side):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill=X, pady=6, padx=10)
        ctk.CTkLabel(frame, text=label, font=FONT_NORMAL, width=78, text_color="#374151", anchor="w").pack(side=LEFT)
        combo = ctk.CTkComboBox(frame, variable=kind_var, values=list(SOFTWARES), state="readonly", font=FONT_NORMAL, dropdown_font=FONT_NORMAL, width=112, height=32, command=lambda _value, s=side: self.source_changed(s))
        combo.pack(side=LEFT, padx=(0, 6))
        ctk.CTkEntry(frame, textvariable=path_var, font=FONT_MONO, height=32).pack(side=LEFT, fill=X, expand=True, padx=6)
        ctk.CTkButton(frame, text="选择", font=FONT_NORMAL, width=66, height=32, fg_color="#ffffff", text_color="#24292f", border_width=1, border_color="#d0d7de", hover_color="#f3f4f6", command=choose_cmd).pack(side=LEFT, padx=3)
        ctk.CTkButton(frame, text="载入", font=FONT_NORMAL, width=66, height=32, fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER, command=load_cmd).pack(side=LEFT, padx=3)

    def source_changed(self, side: str):
        self.reset_side(side, clear_path=True)
        clear_runtime_caches()
        self.persist_state()
        self.status.set("已切换来源，请重新选择路径并载入")

    def reset_side(self, side: str, clear_path: bool = False):
        if side == "left":
            if clear_path:
                self.left_path.set("")
            self.left_store = None
            self.left_blocks = []
            self.left_selected = None
            self.clear_box(self.left_box)
        else:
            if clear_path:
                self.right_path.set("")
            self.right_store = None
            self.right_blocks = []
            self.right_selected = None
            self.clear_box(self.right_box)

    def clear_box(self, box):
        box["blocks"].delete(*box["blocks"].get_children())
        box["stocks"].delete(*box["stocks"].get_children())

    def block_panel(self, parent, title, side):
        frame = ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=10, border_width=1, border_color="#d0d7de")
        frame.pack(side=side, fill=BOTH, expand=True, padx=6)
        ctk.CTkLabel(frame, text=title, font=FONT_SECTION, text_color="#111827").pack(anchor="w", padx=12, pady=(10, 6))
        block_wrap = ctk.CTkFrame(frame, fg_color="#ffffff")
        block_wrap.pack(fill=X, padx=10)
        blocks = ttk.Treeview(block_wrap, columns=("name", "count"), show="headings", height=5, style="Stock.Treeview")
        block_y = ttk.Scrollbar(block_wrap, orient="vertical", command=blocks.yview)
        blocks.configure(yscrollcommand=block_y.set)
        blocks.heading("name", text="自定义板块")
        blocks.heading("count", text="数量")
        blocks.column("name", width=330)
        blocks.column("count", width=70, anchor="center")
        blocks.pack(side=LEFT, fill=X, expand=True)
        block_y.pack(side=RIGHT, fill="y")
        stock_wrap = ctk.CTkFrame(frame, fg_color="#ffffff")
        stock_wrap.pack(fill=BOTH, expand=True, padx=10, pady=(8, 10))
        stocks = ttk.Treeview(stock_wrap, columns=("sel", "idx", "market", "code", "name"), show="headings", style="Stock.Treeview")
        stock_y = ttk.Scrollbar(stock_wrap, orient="vertical", command=stocks.yview)
        stock_x = ttk.Scrollbar(stock_wrap, orient="horizontal", command=stocks.xview)
        stocks.configure(yscrollcommand=stock_y.set, xscrollcommand=stock_x.set)
        for col, text, width in [("sel", "选择", 50), ("idx", "序号", 55), ("market", "市场", 60), ("code", "股票代码", 100), ("name", "股票名称", 150)]:
            stocks.heading(col, text=text)
            stocks.column(col, width=width, anchor="center")
        stocks.pack(side=LEFT, fill=BOTH, expand=True)
        stock_y.pack(side=RIGHT, fill="y")
        stock_x.pack(side="bottom", fill=X)
        blocks.bind("<<TreeviewSelect>>", lambda e, b=blocks, s=stocks: self.show_block(b, s))
        return {"blocks": blocks, "stocks": stocks}

    def choose_left(self):
        path = filedialog.askopenfilename(title="选择左侧程序", filetypes=[("程序或数据文件", "*.exe *.json *.blk *.dat"), ("所有文件", "*.*")])
        if path:
            self.left_path.set(path)
            self.reset_side("left")
            self.status.set("左侧路径已选择，请点击载入")

    def choose_right(self):
        path = filedialog.askopenfilename(title="选择右侧程序", filetypes=[("程序或数据文件", "*.exe *.json *.blk *.dat"), ("所有文件", "*.*")])
        if path:
            self.right_path.set(path)
            self.reset_side("right")
            self.status.set("右侧路径已选择，请点击载入")

    def load_all(self):
        refreshed = False
        if self.left_store:
            self.reload_side("left", self.left_selected.name if self.left_selected else None)
            refreshed = True
        elif self.left_path.get().strip():
            self.load_left()
            refreshed = True
        if self.right_store:
            self.reload_side("right", self.right_selected.name if self.right_selected else None)
            refreshed = True
        elif self.right_path.get().strip():
            self.load_right()
            refreshed = True
        if refreshed:
            self.status.set("已重新载入当前数据")
        else:
            self.status.set("请选择左右两侧程序后载入")

    def load_left(self):
        store = self.create_store(self.left_kind.get(), self.left_path.get(), "left")
        if not store:
            self.reset_side("left")
            return
        self.left_store = store
        self.left_blocks = self.left_store.list_blocks()
        self.left_selected = None
        self.left_box["stocks"].delete(*self.left_box["stocks"].get_children())
        self.refresh_stock_names()
        self.fill_blocks(self.left_box["blocks"], self.left_blocks)
        self.show_selected_block(self.left_box)
        self.persist_state()

    def load_right(self):
        store = self.create_store(self.right_kind.get(), self.right_path.get(), "right")
        if not store:
            self.reset_side("right")
            return
        self.right_store = store
        self.right_blocks = self.right_store.list_blocks()
        self.right_selected = None
        self.right_box["stocks"].delete(*self.right_box["stocks"].get_children())
        self.refresh_stock_names()
        self.fill_blocks(self.right_box["blocks"], self.right_blocks)
        self.show_selected_block(self.right_box)
        self.persist_state()

    def create_store(self, kind: str, raw_path: str, side: str):
        if not raw_path.strip():
            messagebox.showwarning("请选择路径", f"请先选择{kind}的执行程序或数据文件。")
            return None
        path, error = self.resolve_path(kind, raw_path)
        if error:
            messagebox.showwarning("路径不匹配", error)
            return None
        if not path:
            self.status.set("已取消选择账号" if kind == "同花顺" else f"没有找到 {kind} 的自选股数据")
            return None
        if kind == "同花顺":
            return TonghuashunStore(path)
        if kind == "文华财经":
            return WenhuaStore(path)
        if kind == "通达信":
            return TdxStore(path)
        return None

    def resolve_path(self, kind: str, raw_path: str) -> tuple[Path | None, str | None]:
        raw = Path(raw_path)
        if not safe_exists(raw):
            return None, f"这个路径不存在：\n{raw_path}"
        if kind == "同花顺":
            accounts = TonghuashunStore.find_accounts(raw_path)
            selected = None
            if len(accounts) > 1:
                selected = self.choose_account(accounts)
                if not selected:
                    return None, None
            elif accounts:
                selected = accounts[0]
            if selected:
                cb = selected / "custom_block"
                return (cb if cb.exists() else selected / "SelfStockInfo.json"), None
            found = TonghuashunStore.locate(raw_path)
            if found and safe_exists(found):
                return found, None
            return None, "当前选择的是“同花顺”，但这个路径下没有找到同花顺自选股数据。\n请选同花顺安装目录里的执行程序，或直接选择 SelfStockInfo.json。"
        if kind == "文华财经":
            if raw.exists() and raw.is_dir() and raw.name.lower() == "selfmess":
                return raw, None
            found = WenhuaStore.locate(raw_path)
            if found and safe_exists(found):
                return found, None
            return None, "当前选择的是“文华财经”，但这个路径下没有找到文华自选股数据。\n请选文华财经安装目录里的执行程序，或选择 SelfMess 目录。"
        if kind == "通达信":
            if raw.exists() and raw.is_dir() and raw.name.lower() == "blocknew":
                return raw, None
            found = TdxStore.locate(raw_path)
            if found and safe_exists(found):
                return found, None
            return None, "当前选择的是“通达信”，但这个路径下没有找到通达信自选股数据。\n请选通达信安装目录里的 TdxW.exe，或选择 T0002\\blocknew 目录。"
        return None, "请选择正确的软件来源。"

    def choose_account(self, accounts: list[Path]) -> Path | None:
        dialog = Toplevel(self.root)
        dialog.title("选择同花顺账号")
        dialog.configure(bg="#f6f8fa")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(2, weight=1, minsize=150)
        ctk.CTkLabel(dialog, text="检测到多个同花顺账号", font=FONT_SECTION, text_color="#111827").grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 4))
        ctk.CTkLabel(dialog, text="单击选择账号数据路径，双击或点确定确认", font=FONT_NORMAL, text_color="#57606a").grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        box = Listbox(dialog, height=min(8, len(accounts)), bg="#ffffff", fg="#24292f", selectbackground=COLOR_SELECT, selectforeground=COLOR_SELECT_TEXT, font=FONT_ACCOUNT_LIST, activestyle="none", relief="solid", bd=1, highlightthickness=0)
        box.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 12))
        for account in accounts:
            box.insert(END, f"{account.name or '账号'}    {account}")
        chosen = {"path": None}
        def ok():
            sel = box.curselection()
            if sel:
                chosen["path"] = accounts[sel[0]]
            dialog.destroy()
        def cancel():
            chosen["path"] = None
            dialog.destroy()
        box.bind("<Double-Button-1>", lambda _event: ok())
        box.bind("<Return>", lambda _event: ok())
        button_row = ctk.CTkFrame(dialog, fg_color="transparent")
        button_row.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 16))
        button_row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(button_row, text="取消", font=FONT_NORMAL, height=42, fg_color="#ffffff", text_color="#24292f", border_width=1, border_color="#d0d7de", hover_color="#f3f4f6", command=cancel).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(button_row, text="确定", font=FONT_NORMAL, height=42, fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER, command=ok).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        if accounts:
            box.selection_set(0)
            box.focus_set()
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self.center_dialog(dialog, width=720, height=360)
        dialog.wait_window()
        return chosen["path"]

    def center_dialog(self, dialog, width: int, height: int):
        self.root.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = max(self.root.winfo_width(), 1)
        root_h = max(self.root.winfo_height(), 1)
        x = root_x + (root_w - width) // 2
        y = root_y + (root_h - height) // 2
        dialog.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def persist_state(self):
        save_state({
            "left_kind": self.left_kind.get(),
            "left_path": self.left_path.get(),
            "right_kind": self.right_kind.get(),
            "right_path": self.right_path.get(),
        })

    def refresh_stock_names(self):
        paths = []
        for var in (self.left_path, self.right_path):
            try:
                paths.append(Path(var.get()))
            except Exception:
                pass
        self.stock_names = load_stock_names(paths)

    def fill_blocks(self, tree, blocks, select_name: str | None = None):
        tree.delete(*tree.get_children())
        for i, block in enumerate(blocks):
            tree.insert("", END, iid=str(i), values=(block.name, len(block.codes)))
        if blocks:
            idx = 0
            if select_name:
                for i, block in enumerate(blocks):
                    if block.name == select_name:
                        idx = i
                        break
            tree.selection_set(str(idx))
            tree.focus(str(idx))

    def show_selected_block(self, box):
        self.show_block(box["blocks"], box["stocks"])

    def show_block(self, block_tree, stock_tree):
        side_blocks = self.left_blocks if block_tree is self.left_box["blocks"] else self.right_blocks
        sel = block_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(side_blocks):
            return
        block = side_blocks[idx]
        if block_tree is self.left_box["blocks"]:
            self.left_selected = block
        else:
            self.right_selected = block
        stock_tree.delete(*stock_tree.get_children())
        for i, code in enumerate(block.codes, 1):
            stock_tree.insert("", END, values=("√", i, market_label(block.markets.get(code, guess_market(code))), code, self.stock_names.get(code, "")))

    def sync(self, direction):
        if not self.left_selected or not self.right_selected:
            messagebox.showwarning("请选择板块", "请先在左右两边各选择一个自定义板块。")
            return
        mode = self.mode.get()
        if direction == "left":
            self.right_store.write_block(self.right_selected, self.left_selected.codes, self.left_selected.markets, mode)
            clear_runtime_caches()
            target_name = self.right_selected.name
            self.reload_side("right", target_name)
            msg = f"已同步到右侧：{target_name}"
        else:
            self.left_store.write_block(self.left_selected, self.right_selected.codes, self.right_selected.markets, mode)
            clear_runtime_caches()
            target_name = self.left_selected.name
            self.reload_side("left", target_name)
            msg = f"已同步到左侧：{target_name}"
        self.status.set(msg)
        messagebox.showinfo("完成", msg + "\n原文件已自动备份到 _sync_backup。")

    def reload_side(self, side: str, select_name: str | None = None):
        if side == "left" and self.left_store:
            self.left_blocks = self.left_store.list_blocks()
            self.left_selected = None
            self.left_box["stocks"].delete(*self.left_box["stocks"].get_children())
            self.refresh_stock_names()
            self.fill_blocks(self.left_box["blocks"], self.left_blocks, select_name)
            self.show_selected_block(self.left_box)
        elif side == "right" and self.right_store:
            self.right_blocks = self.right_store.list_blocks()
            self.right_selected = None
            self.right_box["stocks"].delete(*self.right_box["stocks"].get_children())
            self.refresh_stock_names()
            self.fill_blocks(self.right_box["blocks"], self.right_blocks, select_name)
            self.show_selected_block(self.right_box)


if __name__ == "__main__":
    root = ctk.CTk()
    App(root)
    root.mainloop()
