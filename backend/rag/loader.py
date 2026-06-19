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
            
            for table_idx, table in enumerate(doc.tables):
                content.append(f"--- Table {table_idx + 1} ---")
                headers = []
                for row_idx, row in enumerate(table.rows):
                    cells = [cell.text.strip() for cell in row.cells]
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
    """
    RAG Highly Dense Context Optimization for Dynamic JSON layout.
    Injects context into every structural line for precise vector retrieval.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        
        output = []
        
        def parse_element(element, context_summary="", prefix=""):
            if isinstance(element, dict):
                # Context identify karne ki koshish (e.g., name, title, item_name)
                local_context = context_summary
                for identity_key in ['name', 'title', 'id', 'record_id', 'type']:
                    if identity_key in element and not isinstance(element[identity_key], (dict, list)):
                        local_context = f"{identity_key} '{element[identity_key]}'"
                        break
                
                for k, v in element.items():
                    current_key = f"{prefix}.{k}" if prefix else k
                    if isinstance(v, (dict, list)):
                        parse_element(v, local_context, current_key)
                    else:
                        if v is not None and str(v).strip():
                            ctx_str = f"Regarding {local_context}: " if local_context else ""
                            output.append(f"{ctx_str}The field '{current_key}' or '{k}' has the exact value: '{v}'")
            
            elif isinstance(element, list):
                for idx, item in enumerate(element):
                    current_prefix = f"{prefix}[{idx}]" if prefix else f"Record_{idx}"
                    parse_element(item, context_summary, current_prefix)
            else:
                if element is not None and str(element).strip():
                    output.append(f"Value for {prefix or 'element'}: '{element}'")

        parse_element(data)
        
        if not output:
            return "[Empty JSON Content]"
        return "\n".join(output)
        
    except Exception as e:
        return f"[JSON Load Error: {str(e)}]"


def load_csv(file_path: str) -> str:
    """
    RAG Highly Dense Context Optimization for dynamic CSV rows.
    Ensures ID and entity name mappings are repeated on every attribute line.
    """
    try:
        output = []
        filename = os.path.basename(file_path)
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            sample = f.read(2048)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample)
                reader = csv.reader(f, dialect)
            except Exception:
                reader = csv.reader(f)
                
            rows = list(reader)
            if not rows:
                return "[Empty CSV Content]"
            
            headers = [h.strip() if h.strip() else f"Column_{i+1}" for i, h in enumerate(rows[0])]
            
            for idx, row in enumerate(rows[1:]):
                if not any(cell.strip() for cell in row):
                    continue
                
                # Sahi metadata link setup karne ke liye Row identity dhoondna
                row_identity = f"Record Row {idx + 1}"
                for i, cell in enumerate(row):
                    if i < len(headers) and headers[i].lower() in ['name', 'title', 'id', 'record id', 'record_id']:
                        if cell.strip():
                            row_identity = f"Entity ({headers[i]}: {cell.strip()})"
                            break

                row_items = []
                for i, cell in enumerate(row):
                    val = cell.strip()
                    if val:
                        header_name = headers[i] if i < len(headers) else f"Column_{i+1}"
                        row_items.append(f"For {row_identity} in {filename} -> the '{header_name}' is '{val}'")
                
                if row_items:
                    output.extend(row_items)
                    
        return "\n".join(output)
    except Exception as e:
        return f"[CSV Load Error: {str(e)}]"


def load_xlsx(file_path: str) -> str:
    """
    RAG Highly Dense Context Optimization for Excel sheets.
    """
    if openpyxl:
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            output = []
            filename = os.path.basename(file_path)
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue
                
                headers = [str(cell).strip() if cell is not None and str(cell).strip() else f"Col_{i+1}" for i, cell in enumerate(rows[0])]
                
                for idx, row in enumerate(rows[1:]):
                    if any(cell is not None for cell in row):
                        row_identity = f"Row {idx+2}"
                        for i, cell in enumerate(row):
                            if i < len(headers) and headers[i].lower() in ['name', 'title', 'id', 'record id', 'record_id']:
                                if cell is not None and str(cell).strip():
                                    row_identity = f"Entity ({headers[i]}: {str(cell).strip()})"
                                    break
                                    
                        row_items = []
                        for i, cell in enumerate(row):
                            if cell is not None and str(cell).strip():
                                header_name = headers[i] if i < len(headers) else f"Col_{i+1}"
                                row_items.append(f"In Sheet '{sheet}' of '{filename}', for {row_identity} -> '{header_name}' is '{str(cell).strip()}'")
                        
                        if row_items:
                            output.extend(row_items)
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