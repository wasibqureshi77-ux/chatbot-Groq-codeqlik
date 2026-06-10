import re
import json

STOPWORDS = {"the", "a", "an", "is", "are", "of", "to", "in", "for", "on", "and", "or", "what", "how", "why", "where", "you", "me", "this", "that", "with", "from", "your", "our", "we", "they", "them", "he", "she", "it", "has", "have", "had", "been", "was", "were", "be", "do", "does", "did", "can", "could", "would", "should", "will", "shall", "may", "might", "must"}

def extract_keywords_from_text(text: str, max_keywords: int = 8) -> list[str]:
    """
    Extracts unique keywords from text.
    """
    words = re.findall(r"\b\w{3,15}\b", text.lower())
    freq = {}
    for w in words:
        if w not in STOPWORDS and not w.isdigit():
            freq[w] = freq.get(w, 0) + 1
    sorted_kws = sorted(freq.keys(), key=lambda x: freq[x], reverse=True)
    return sorted_kws[:max_keywords]

def generate_summary(text: str, max_sentences: int = 1) -> str:
    """
    Generates a simple summary by extracting the first sentence(s).
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s for s in sentences if s.strip()]
    if not sentences:
        return ""
    return " ".join(sentences[:max_sentences])

def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 150) -> list[str]:
    """
    Standard character-based sliding window text splitter.
    """
    if not text:
        return []
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end]
        chunks.append(chunk)
        start += (chunk_size - chunk_overlap)
        if start >= text_len or chunk_size <= chunk_overlap:
            break
            
    return chunks

def chunk_document(doc_type: str, content: str, base_metadata: dict = None) -> list[dict]:
    """
    Specialized chunking based on document types:
    - csv, xlsx, database: Row-based / record-based chunking.
    - json: Array of objects or flat dictionary chunking.
    - md, markdown: Section-based chunking (by headers).
    - pdf, docx, txt: Paragraph/text chunking.
    """
    base_metadata = base_metadata or {}
    chunks = []
    doc_type = doc_type.lower().replace(".", "")

    # 1. Row-based/Record-based (CSV / XLSX / Database)
    if doc_type in ("csv", "xlsx", "xls") or doc_type.startswith("db_"):
        # Split by newline
        rows = [r.strip() for r in content.split("\n") if r.strip()]
        for idx, row in enumerate(rows):
            # Each row is its own chunk to preserve row boundaries
            kws = extract_keywords_from_text(row)
            summary = generate_summary(row, max_sentences=1) or f"Record row {idx+1} from {doc_type} data"
            
            row_meta = dict(base_metadata)
            row_meta["row_index"] = idx + 1
            if doc_type in ("xlsx", "xls") and "Sheet:" in row:
                match = re.search(r"Sheet: (\w+)", row)
                if match:
                    row_meta["sheet_name"] = match.group(1)
            
            chunks.append({
                "chunk_text": row,
                "chunk_summary": summary,
                "keywords": kws,
                "metadata": row_meta
            })

    # 2. JSON files
    elif doc_type == "json":
        try:
            data = json.loads(content)
            # If JSON is a list of objects (FAQs, products)
            if isinstance(data, list):
                for idx, obj in enumerate(data):
                    obj_str = json.dumps(obj, indent=2)
                    kws = extract_keywords_from_text(obj_str)
                    
                    # Try to find a good summary title
                    summary_title = ""
                    if isinstance(obj, dict):
                        for key in ("question", "title", "name", "id"):
                            if key in obj:
                                summary_title = str(obj[key])
                                break
                    if not summary_title:
                        summary_title = f"JSON Item {idx + 1}"
                        
                    obj_meta = dict(base_metadata)
                    obj_meta["json_index"] = idx
                    
                    chunks.append({
                        "chunk_text": obj_str,
                        "chunk_summary": f"JSON data: {summary_title}",
                        "keywords": kws,
                        "metadata": obj_meta
                    })
            # If JSON is a dictionary
            elif isinstance(data, dict):
                # Split dictionary keys into chunks
                for key, val in data.items():
                    section_text = f"{key}: {json.dumps(val, indent=2)}"
                    kws = extract_keywords_from_text(section_text)
                    
                    obj_meta = dict(base_metadata)
                    obj_meta["json_key"] = key
                    
                    chunks.append({
                        "chunk_text": section_text,
                        "chunk_summary": f"JSON section for key: {key}",
                        "keywords": kws,
                        "metadata": obj_meta
                    })
            else:
                # Fallback to standard text splitting
                raise ValueError("JSON is flat scalar value")
        except Exception:
            # Fallback
            text_chunks = split_text(content, chunk_size=800, chunk_overlap=150)
            for idx, tc in enumerate(text_chunks):
                chunks.append({
                    "chunk_text": tc,
                    "chunk_summary": generate_summary(tc, 1),
                    "keywords": extract_keywords_from_text(tc),
                    "metadata": base_metadata
                })

    # 3. Markdown / Section-based splitting
    elif doc_type in ("md", "markdown"):
        # Split by headers
        sections = re.split(r"(^#+\s+.*)", content, flags=re.MULTILINE)
        current_header = "Header"
        for part in sections:
            part = part.strip()
            if not part:
                continue
            if part.startswith("#"):
                current_header = part.replace("#", "").strip()
                continue
                
            full_section = f"[{current_header}]\n{part}"
            kws = extract_keywords_from_text(full_section)
            summary = generate_summary(part, 1) or f"Section: {current_header}"
            
            sect_meta = dict(base_metadata)
            sect_meta["section_header"] = current_header
            
            chunks.append({
                "chunk_text": full_section,
                "chunk_summary": summary,
                "keywords": kws,
                "metadata": sect_meta
            })

    # 4. Text/PDF/DOCX Paragraph/Text splitting
    else:
        # Check if PDF page marker exists (e.g. "[Page X]")
        # We can split PDF by pages if pages are demarcated in content
        pages = re.split(r"=== PAGE_BREAK: (\d+) ===", content)
        if len(pages) > 1:
            for i in range(1, len(pages), 2):
                page_num = int(pages[i])
                page_content = pages[i+1].strip()
                
                # Split page content into smaller paragraph chunks if page content is large
                paragraphs = split_text(page_content, chunk_size=800, chunk_overlap=150)
                for idx, para in enumerate(paragraphs):
                    kws = extract_keywords_from_text(para)
                    summary = generate_summary(para, 1)
                    
                    page_meta = dict(base_metadata)
                    page_meta["page_number"] = page_num
                    page_meta["paragraph_index"] = idx
                    
                    chunks.append({
                        "chunk_text": para,
                        "chunk_summary": summary,
                        "keywords": kws,
                        "metadata": page_meta
                    })
        else:
            # Paragraph splitting
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            
            current_chunk = ""
            for p in paragraphs:
                if len(current_chunk) + len(p) < 800:
                    current_chunk += ("\n\n" + p if current_chunk else p)
                else:
                    if current_chunk:
                        chunks.append({
                            "chunk_text": current_chunk,
                            "chunk_summary": generate_summary(current_chunk, 1),
                            "keywords": extract_keywords_from_text(current_chunk),
                            "metadata": base_metadata
                        })
                    current_chunk = p
            if current_chunk:
                chunks.append({
                    "chunk_text": current_chunk,
                    "chunk_summary": generate_summary(current_chunk, 1),
                    "keywords": extract_keywords_from_text(current_chunk),
                    "metadata": base_metadata
                })

    # Fallback to avoid empty chunks
    if not chunks and content:
        kws = extract_keywords_from_text(content)
        summary = generate_summary(content, 1)
        chunks.append({
            "chunk_text": content,
            "chunk_summary": summary,
            "keywords": kws,
            "metadata": base_metadata
        })

    return chunks
