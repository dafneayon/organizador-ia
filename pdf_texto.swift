// Extrae texto de un PDF para 'vistazo' sin dependencias externas (solo macOS).
// Usa la capa de texto de PDFKit; si una página no tiene texto (escaneo),
// hace OCR con Vision. Solo lee: nunca modifica el PDF.
//
// Uso: pdf_texto <archivo.pdf> [max_caracteres] [max_paginas]
// Lo compila herramienta.py la primera vez en bin/pdf_texto.
import Foundation
import PDFKit
import Vision

let args = CommandLine.arguments
guard args.count >= 2, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("no se pudo abrir el PDF\n".data(using: .utf8)!)
    exit(1)
}
let maxCaracteres = args.count >= 3 ? Int(args[2]) ?? 1200 : 1200
let maxPaginas = args.count >= 4 ? Int(args[3]) ?? 2 : 2

func ocr(_ pagina: PDFPage) -> String {
    let caja = pagina.bounds(for: .mediaBox)
    let escala: CGFloat = 2
    let ancho = Int(caja.width * escala), alto = Int(caja.height * escala)
    guard ancho > 0, alto > 0,
          let ctx = CGContext(data: nil, width: ancho, height: alto, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return "" }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: ancho, height: alto))
    ctx.scaleBy(x: escala, y: escala)
    pagina.draw(with: .mediaBox, to: ctx)
    guard let imagen = ctx.makeImage() else { return "" }
    let peticion = VNRecognizeTextRequest()
    peticion.recognitionLevel = .accurate
    peticion.recognitionLanguages = ["es-ES", "en-US"]
    try? VNImageRequestHandler(cgImage: imagen).perform([peticion])
    return (peticion.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: " ")
}

var texto = ""
var usoOCR = false
for i in 0..<min(doc.pageCount, maxPaginas) {
    guard let pagina = doc.page(at: i) else { continue }
    var t = (pagina.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    if t.isEmpty {
        t = ocr(pagina)
        usoOCR = usoOCR || !t.isEmpty
    }
    texto += t + " "
    if texto.count >= maxCaracteres { break }
}
let limpio = texto.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
print((usoOCR ? "[OCR] " : "") + String(limpio.prefix(maxCaracteres)))
