"""Extracción de texto de documentos (solo lectura, solo biblioteca estándar).

La usan herramienta.py ('vistazo', unos cientos de caracteres) y busqueda.py
(el índice, el documento completo hasta un límite). Nunca modifica los archivos.
"""
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent

# Claves, certificados (incluida la e.firma del SAT: .key, .cer, .req) y bóvedas: nunca se leen
SENSIBLES = {".pem", ".key", ".p12", ".pfx", ".keychain", ".kdbx", ".ovpn", ".gpg", ".asc",
             ".cer", ".crt", ".req", ".sdg"}
TEXTO = {".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm", ".py", ".r",
         ".m", ".tex", ".bib", ".log", ".yaml", ".yml", ".ini", ".sh", ".js", ".css", ".rtf"}
OFFICE = {".docx": "word/document.xml", ".pptx": "ppt/slides/slide", ".xlsx": "xl/sharedStrings.xml"}


def lector_pdf():
    """Compila pdf_texto.swift en bin/ la primera vez (o si cambió). None si no hay swiftc."""
    fuente, binario = AQUI / "pdf_texto.swift", AQUI / "bin" / "pdf_texto"
    if binario.exists() and binario.stat().st_mtime >= fuente.stat().st_mtime:
        return binario
    if not shutil.which("swiftc"):
        return None
    binario.parent.mkdir(exist_ok=True)
    r = subprocess.run(["swiftc", "-O", "-o", str(binario), str(fuente)],
                       capture_output=True, text=True)
    return binario if r.returncode == 0 else None


def texto_pdf(p: Path, n: int, paginas=2, timeout=60) -> str:
    """Capa de texto con PDFKit, OCR con Vision si es un escaneo; si falla, índice de Spotlight.
    Si hubo OCR, el texto empieza con '[OCR] '."""
    lector = lector_pdf()
    if lector:
        try:
            r = subprocess.run([str(lector), str(p), str(n), str(paginas)],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()[:n]
        except subprocess.TimeoutExpired:
            pass
    r = subprocess.run(["mdls", "-raw", "-name", "kMDItemTextContent", str(p)],
                       capture_output=True, text=True).stdout
    return "" if r.strip() == "(null)" else r[:n]


def _sin_etiquetas(xml: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml)).strip()


def texto_office(p: Path, n: int, partes=None) -> str:
    """Texto de .docx, .pptx o .xlsx leyendo su XML interno (en orden de diapositiva)."""
    prefijo = OFFICE[p.suffix.lower()]
    with zipfile.ZipFile(p) as z:
        nombres = [x for x in z.namelist() if x.startswith(prefijo) and x.endswith(".xml")]
        nombres.sort(key=lambda x: int(re.sub(r"\D", "", x) or 0))
        texto = []
        for x in nombres[:partes]:
            # Saltos de párrafo para que los fragmentos no peguen palabras
            xml = z.read(x).decode("utf-8", "ignore").replace("</w:p>", "\n").replace("</a:p>", "\n")
            texto.append(_sin_etiquetas(xml))
            if sum(map(len, texto)) >= n:
                break
    return " ".join(texto)[:n]


CFDI_CAMPOS = [("Comprobante", ("Fecha", "Total", "SubTotal", "Moneda", "TipoDeComprobante", "Folio")),
               ("Emisor", ("Nombre", "Rfc")), ("Receptor", ("Nombre", "Rfc", "UsoCFDI")),
               ("Concepto", ("Descripcion", "Importe")), ("TimbreFiscalDigital", ("UUID",))]


def texto_xml(p: Path, n: int) -> str:
    """En un CFDI (factura electrónica) los datos están en atributos: se extraen con su nombre."""
    xml = p.read_text(encoding="utf-8", errors="ignore")
    if "Comprobante" not in xml[:4000]:
        return _sin_etiquetas(xml)[:n]
    partes = ["Factura electrónica CFDI."]
    for nodo, campos in CFDI_CAMPOS:
        for m in re.finditer(r"<(?:\w+:)?%s\b([^>]*)>" % nodo, xml):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            valores = [f"{c}: {attrs[c]}" for c in campos if c in attrs]
            if valores:
                partes.append(f"{nodo} - " + ", ".join(valores) + ".")
    return " ".join(partes)[:n]


def extraer(p: Path, n: int, paginas=2) -> str:
    """Texto de cualquier documento soportado ('' si no se puede o si es sensible)."""
    suf = p.suffix.lower()
    if suf in SENSIBLES:
        return ""
    if suf in TEXTO:
        return p.read_text(encoding="utf-8", errors="ignore")[:n]
    if suf in OFFICE:
        return texto_office(p, n)
    if suf == ".xml":
        return texto_xml(p, n)
    if suf == ".pdf":
        return texto_pdf(p, n, paginas, timeout=60 + 20 * paginas)
    return ""
