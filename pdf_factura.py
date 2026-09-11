"""
Generador de PDF de factura, replicando el formato del modelo de
GRUPO NUTRIENTI S.A.S (factura electronica de venta tipo World Office).
"""
import io
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)

# ---------------------------------------------------------------------------
# Datos fijos de la empresa (encabezado de toda factura) - ver factura modelo
# ---------------------------------------------------------------------------
COMPANY = {
    "nombre": "GRUPO NUTRIENTI S.A.S",
    "nit": "901910987",
    "nit_dv": "7",
    "direccion": "Bogotá, D.C. CL 141 52 32",
    "telefono": "3134824742",
    "correo": "contacto@nutrienti.co",
    "autorizacion": (
        "Documento Oficial de Autorización de Numeración Facturación "
        "Electrónica No. 18764088265638 que habilita desde FE 1 hasta "
        "50000. Vence 03/02/2027."
    ),
    "responsable_iva": (
        "Somos Responsables de IVA, No somos Agentes de Retención de IVA. "
        "No somos Grandes Contribuyentes, Actividad Económica 4631 "
        "Tarifa de ICA 4.14 por mil."
    ),
    "vendedor": "GRUPO NUTRIENTI S.A.S",
}

NO_APARECE = "no aparece"
AZUL = colors.HexColor("#1F4E79")
AZUL_CLARO = colors.HexColor("#DCE6F1")
GRIS_TEXTO = colors.HexColor("#333333")

# ---------------------------------------------------------------------------
# Numero a letras (español) - implementacion propia, sin dependencias externas
# ---------------------------------------------------------------------------
_UNIDADES = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]
_DIECIS = ["diez", "once", "doce", "trece", "catorce", "quince", "dieciseis",
           "diecisiete", "dieciocho", "diecinueve"]
_DECENAS = ["", "", "veinte", "treinta", "cuarenta", "cincuenta", "sesenta",
            "setenta", "ochenta", "noventa"]
_CENTENAS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos",
             "quinientos", "seiscientos", "setecientos", "ochocientos", "novecientos"]


def _tres_digitos(n):
    if n == 0:
        return ""
    if n == 100:
        return "cien"
    palabras = []
    c, r = divmod(n, 100)
    if c:
        palabras.append(_CENTENAS[c])
    if r:
        if r < 10:
            palabras.append(_UNIDADES[r])
        elif r < 20:
            palabras.append(_DIECIS[r - 10])
        elif r < 30:
            u = r - 20
            palabras.append("veinti" + _UNIDADES[u] if u else "veinte")
        else:
            t, u = divmod(r, 10)
            palabras.append(_DECENAS[t] + (" y " + _UNIDADES[u] if u else ""))
    return " ".join(palabras)


def numero_a_letras(n):
    """Convierte un entero no negativo a palabras en español (sin acentos,
    igual al estilo usado en la factura modelo: 'SESENTA Y SEIS MIL...')."""
    n = int(round(n))
    if n == 0:
        return "cero"
    partes = []
    millones, resto = divmod(n, 1_000_000)
    miles, resto2 = divmod(resto, 1000)

    if millones:
        partes.append("un millon" if millones == 1 else _tres_digitos(millones) + " millones")
    if miles:
        partes.append("mil" if miles == 1 else _tres_digitos(miles) + " mil")
    if resto2:
        partes.append(_tres_digitos(resto2))
    return " ".join(partes)


def valor_en_letras_pesos(valor):
    return f"{numero_a_letras(valor).upper()} PESOS"


# ---------------------------------------------------------------------------
# Digito de verificacion de NIT (algoritmo DIAN, modulo 11)
# ---------------------------------------------------------------------------
_PESOS_DV = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]


def nit_digito_verificacion(nit):
    digitos = [int(d) for d in re.sub(r"\D", "", str(nit or ""))]
    if not digitos:
        return None
    digitos = digitos[::-1]
    total = sum(d * _PESOS_DV[i] for i, d in enumerate(digitos) if i < len(_PESOS_DV))
    r = total % 11
    return r if r < 2 else 11 - r


def formatear_nit(nit):
    if not nit or nit == NO_APARECE:
        return NO_APARECE
    dv = nit_digito_verificacion(nit)
    return f"{nit} - {dv}" if dv is not None else str(nit)


def fmt_money(v):
    try:
        return "$ " + f"{v:,.0f}".replace(",", ".") + ",00"
    except (TypeError, ValueError):
        return "$ 0,00"


# ---------------------------------------------------------------------------
# Construccion del PDF
# ---------------------------------------------------------------------------
def build_invoice_pdf(invoice):
    """invoice: dict con llaves:
        numero_factura (int)
        cliente_nombre, cliente_nit, cliente_direccion, cliente_ciudad,
        cliente_telefono, forma_pago (str, usar NO_APARECE si falta)
        fecha (str dd/mm/aaaa), vencimiento (str dd/mm/aaaa o NO_APARECE)
        concepto (str) - texto de cliente/punto tal como llego el pedido
        items: lista de dicts {codigo, descripcion, unidad, cantidad,
                                valor_unitario, encontrado(bool)}
    Devuelve los bytes del PDF.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
    )
    styles = getSampleStyleSheet()
    style_normal = ParagraphStyle("normal", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=GRIS_TEXTO)
    style_small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7, leading=9, textColor=GRIS_TEXTO)
    style_small_right = ParagraphStyle("small_r", parent=style_small, alignment=TA_RIGHT)
    style_company = ParagraphStyle("company", parent=styles["Normal"], fontSize=13, leading=15, textColor=AZUL, fontName="Helvetica-Bold")
    style_titulo = ParagraphStyle("titulo", parent=styles["Normal"], fontSize=15, leading=17, textColor=AZUL, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    style_fe = ParagraphStyle("fe", parent=styles["Normal"], fontSize=17, leading=20, textColor=AZUL, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    style_field_label = ParagraphStyle("field", parent=styles["Normal"], fontSize=8.5, leading=11, fontName="Helvetica-Bold", textColor=GRIS_TEXTO)

    story = []

    # --- Encabezado: empresa (izq) / titulo + FE + autorizacion (der) ------
    left_html = (
        f"<b>{COMPANY['nombre']}</b><br/>"
        f"NIT: {COMPANY['nit']} - {COMPANY['nit_dv']}<br/><br/>"
        f"{COMPANY['direccion']}<br/>"
        f"Teléfono {COMPANY['telefono']}<br/>"
        f"Correo Electrónico  {COMPANY['correo']}"
    )
    right_top = Paragraph("Factura Electrónica de Venta", style_titulo)
    right_fe = Paragraph(f"FE {invoice['numero_factura']}", style_fe)
    right_auth = Paragraph(COMPANY["autorizacion"] + "<br/>" + COMPANY["responsable_iva"], style_small_right)

    header_tbl = Table(
        [[Paragraph(left_html, style_normal), [right_top, Spacer(1, 2), right_fe, Spacer(1, 4), right_auth]]],
        colWidths=[95 * mm, 85 * mm],
    )
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, AZUL),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 4))

    # --- Datos del cliente ---------------------------------------------
    def cell(label, value, bold_value=False):
        val = value if value else NO_APARECE
        style_val = style_field_label if bold_value else style_normal
        return Paragraph(f"<b>{label}</b> {val}", style_normal)

    info_rows = [
        [cell("Cliente:", invoice.get("cliente_nombre")), cell("NIT:", formatear_nit(invoice.get("cliente_nit")))],
        [cell("Dirección:", invoice.get("cliente_direccion")), ""],
        [cell("Ciudad:", invoice.get("cliente_ciudad")), cell("Teléfono:", invoice.get("cliente_telefono"))],
        [cell("Fecha:", invoice.get("fecha")), cell("Vencimiento:", invoice.get("vencimiento"))],
        [cell("Forma de Pago:", invoice.get("forma_pago")), ""],
        [cell("Vendedor:", COMPANY["vendedor"]), ""],
        [cell("Por Concepto de:", invoice.get("concepto")), ""],
    ]
    info_tbl = Table(info_rows, colWidths=[125 * mm, 55 * mm])
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.8, AZUL),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B7C6DE")),
        ("SPAN", (0, 1), (1, 1)),
        ("SPAN", (0, 4), (1, 4)),
        ("SPAN", (0, 5), (1, 5)),
        ("SPAN", (0, 6), (1, 6)),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 4))

    # --- Tabla de items ---------------------------------------------------
    header = ["Item", "Código", "Descripción", "Unidad", "Cantidad",
              "Valor\nUnitario", "%\nDscto", "IVA %", "IVA Valor", "Total"]
    style_header_cell = ParagraphStyle("hcell", parent=styles["Normal"], fontSize=7.5, leading=9,
                                        textColor=colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold")
    style_cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10, textColor=GRIS_TEXTO)
    style_cell_r = ParagraphStyle("cell_r", parent=style_cell, alignment=TA_RIGHT)
    style_cell_c = ParagraphStyle("cell_c", parent=style_cell, alignment=TA_CENTER)

    rows = [[Paragraph(h, style_header_cell) for h in header]]
    subtotal = 0.0
    for idx, it in enumerate(invoice["items"], start=1):
        cantidad = it["cantidad"]
        if it.get("encontrado"):
            vu = it["valor_unitario"]
            total_linea = round(vu * cantidad)
            subtotal += total_linea
            vu_txt = fmt_money(vu)
            total_txt = fmt_money(total_linea)
        else:
            vu_txt = NO_APARECE
            total_txt = NO_APARECE
        rows.append([
            Paragraph(str(idx), style_cell_c),
            Paragraph(str(it.get("codigo") or NO_APARECE), style_cell),
            Paragraph(str(it.get("descripcion") or NO_APARECE), style_cell),
            Paragraph(str(it.get("unidad") or NO_APARECE), style_cell_c),
            Paragraph(f"{cantidad:g}", style_cell_r),
            Paragraph(vu_txt, style_cell_r),
            Paragraph("0,00", style_cell_r),
            Paragraph("0", style_cell_c),
            Paragraph("0,00", style_cell_r),
            Paragraph(total_txt, style_cell_r),
        ])

    items_tbl = Table(
        rows,
        colWidths=[10 * mm, 19 * mm, 42 * mm, 14 * mm, 16 * mm, 22 * mm, 12 * mm, 11 * mm, 16 * mm, 19 * mm],
        repeatRows=1,
    )
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B7C6DE")),
        ("BOX", (0, 0), (-1, -1), 0.8, AZUL),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FC")]),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 4))

    # --- Totales y valor en letras -----------------------------------------
    n_items = len(invoice["items"])
    descuento = 0
    iva = 0
    total_operacion = subtotal - descuento + iva
    retefuente = 0
    reteiva = 0
    reteica = 0
    total_documento = total_operacion - retefuente - reteiva - reteica

    letras_txt = valor_en_letras_pesos(subtotal) if subtotal else NO_APARECE
    letras_box = Table(
        [[Paragraph("<b>Valor en Letras</b>", style_field_label)],
         [Paragraph(letras_txt, style_normal)]],
        colWidths=[95 * mm], rowHeights=[15, 28],
    )
    letras_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, AZUL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, AZUL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
    ]))

    totales_rows = [
        ["TOTAL LINEAS O ITEMS", str(n_items)],
        ["SUBTOTAL", fmt_money(subtotal)],
        ["DESCUENTO", fmt_money(descuento)],
        ["IVA", fmt_money(iva)],
        ["TOTAL OPERACIÓN", fmt_money(total_operacion)],
        ["RETEFUENTE", fmt_money(retefuente)],
        ["RETEIVA", fmt_money(reteiva)],
        ["RETEICA", fmt_money(reteica)],
        ["TOTAL DOCUMENTO", fmt_money(total_documento)],
    ]
    style_tot_label = ParagraphStyle("totl", parent=styles["Normal"], fontSize=8, fontName="Helvetica-Bold", textColor=GRIS_TEXTO)
    style_tot_val = ParagraphStyle("totv", parent=styles["Normal"], fontSize=8, alignment=TA_RIGHT, textColor=GRIS_TEXTO)
    totales_tbl = Table(
        [[Paragraph(a, style_tot_label), Paragraph(b, style_tot_val)] for a, b in totales_rows],
        colWidths=[45 * mm, 40 * mm],
    )
    totales_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, AZUL),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B7C6DE")),
        ("BACKGROUND", (0, -1), (-1, -1), AZUL_CLARO),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))

    footer_tbl = Table([[letras_box, totales_tbl]], colWidths=[95 * mm, 85 * mm])
    footer_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(footer_tbl)
    story.append(Spacer(1, 22))

    firma_tbl = Table(
        [["Recibido Por _______________________________", "Firma Responsable _______________________________"]],
        colWidths=[95 * mm, 85 * mm],
    )
    firma_tbl.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5)]))
    story.append(firma_tbl)

    doc.build(story)
    return buf.getvalue(), {
        "subtotal": subtotal,
        "total_documento": total_documento,
    }
