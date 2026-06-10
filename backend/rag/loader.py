import json
import csv
import io
import os

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import docx
except ImportError:
    docx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None


class Document:
    def __init__(self, content: str, metadata: dict = None):
        self.content = content
        self.metadata = metadata or {}


def load_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def load_pdf(file_path: str) -> str:
    if pypdf:
        text = []
        try:
            reader = pypdf.PdfReader(file_path)
            for page_idx, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text.append(f"=== PAGE_BREAK: {page_idx + 1} ===\n{page_text}")
            return "\n".join(text)
        except Exception as e:
            return f"[PDF Load Error: {str(e)}]"
    else:
        # Fallback reading ASCII character blocks
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            ascii_text = "".join(chr(b) if (32 <= b <= 126 or b in (10, 13)) else " " for b in content)
            return f"[pypdf not installed. Read raw bytes fallback]\n{ascii_text[:4000]}"
        except Exception:
            return "[PDF Read Error: pypdf not available]"


def load_docx(file_path: str) -> str:
    if docx:
        try:
            doc = docx.Document(file_path)
            content = []
            for para in doc.paragraphs:
                if para.text.strip():
                    content.append(para.text.strip())
            # Parse tables
            for table_idx, table in enumerate(doc.tables):
                content.append(f"--- Table {table_idx + 1} ---")
                headers = []
                for row_idx, row in enumerate(table.rows):
                    cells = [cell.text.strip() for cell in row.cells]
                    # Clean up adjacent duplicates due to horizontal merges
                    clean_cells = []
                    for c in cells:
                        if not clean_cells or c != clean_cells[-1]:
                            clean_cells.append(c)
                            
                    if row_idx == 0:
                        headers = clean_cells
                        content.append("Headers: " + " | ".join(headers))
                    else:
                        content.append("Row: " + " | ".join(
                            f"{headers[i] if i < len(headers) else f'Col{i}'}: {val}" 
                            for i, val in enumerate(clean_cells)
                        ))
            return "\n\n".join(content)
        except Exception as e:
            return f"[DOCX Load Error: {str(e)}]"
    else:
        return f"[python-docx not installed. Unable to load Word file {os.path.basename(file_path)}]"


def load_json(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"[JSON Load Error: {str(e)}]"


def load_csv(file_path: str) -> str:
    try:
        output = []
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                row_str = ", ".join(f"{k}: {v}" for k, v in row.items() if v)
                output.append(row_str)
        return "\n".join(output)
    except Exception as e:
        return f"[CSV Load Error: {str(e)}]"


def load_xlsx(file_path: str) -> str:
    if openpyxl:
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            output = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue
                headers = [str(cell) if cell is not None else f"Column{i}" for i, cell in enumerate(rows[0])]
                for idx, row in enumerate(rows[1:]):
                    if any(cell is not None for cell in row):
                        row_str = f"Sheet: {sheet}, " + ", ".join(
                            f"{headers[i]}: {str(cell)}" 
                            for i, cell in enumerate(row) 
                            if cell is not None
                        )
                        output.append(row_str)
            return "\n".join(output)
        except Exception as e:
            return f"[Excel Load Error: {str(e)}]"
    else:
        return f"[openpyxl not installed. Unable to load Excel file {os.path.basename(file_path)}]"


def load_any_file(file_path: str) -> Document:
    ext = os.path.splitext(file_path)[1].lower()
    metadata = {
        "source_name": os.path.basename(file_path),
        "source_type": ext.replace(".", "")
    }
    
    if ext == ".txt":
        content = load_txt(file_path)
    elif ext == ".pdf":
        content = load_pdf(file_path)
    elif ext in (".docx", ".doc"):
        content = load_docx(file_path)
    elif ext == ".json":
        content = load_json(file_path)
    elif ext == ".csv":
        content = load_csv(file_path)
    elif ext in (".xlsx", ".xls"):
        content = load_xlsx(file_path)
    elif ext in (".md", ".markdown"):
        content = load_txt(file_path)
    else:
        try:
            content = load_txt(file_path)
        except Exception:
            content = f"[Unsupported file format: {ext}]"

    return Document(content, metadata)
