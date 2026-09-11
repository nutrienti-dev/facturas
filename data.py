"""
Carga de datos desde Google Sheets / Drive, cruce de pedidos con precios y
escritura del resultado en una hoja de Google dentro de "Integracion AI".
"""
import io
import re
from datetime import datetime, timedelta

import openpyxl

from . import matching

# ---------------------------------------------------------------------------
# IDs fijos de archivos / carpetas de Drive (cuenta contacto@nutrienti.co)
# ---------------------------------------------------------------------------
CLIENTS_MASTER_FILE_ID = "16GFApKVxoQ1mVURvCpgbDGNmwjCGbeka"       # BASE DE DATOS CLIENTES ACTIVOS.xlsx
PRICES_SHEET_ID = "1HMNBT9Qqogz3WgZIenm-jB9wTUP7Ta_NP1BhUhoB3-s"   # Nutrienti - Precios por Cliente (World Office)
PEDIDOS_SHEET_ID = "1WKkqvaM27VDxCviwNPWKEI5xKblDH-vgQEi9_5oiQNY"  # Pedidos Web - Registro de Solicitudes
INTEGRACION_AI_FOLDER_ID = "1I84GZo517GSPCmUQZVThxqdTODckhrmZ"
FACTURAS_FOLDER_ID = "1pcD7kT1X6MO2ltpxwro-D7gk19Du975a"

OUTPUT_SHEET_TITLE = "Nutrienti - Pedidos con Precios (Facturacion)"
PLAZO_DIAS_DEFAULT = 30  # se usa cuando el cliente no tiene "Plazo Dias" en la base

NO_APARECE = "no aparece"
LISTA_PRECIOS_EXCLUIDAS = {"predeterminada"}


# ---------------------------------------------------------------------------
# Carga de fuentes
# ---------------------------------------------------------------------------
def load_precios(gc):
    ws = gc.open_by_key(PRICES_SHEET_ID).sheet1
    records = ws.get_all_records()
    rows = []
    for r in records:
        empresa = str(r.get("empresa", "")).strip()
        if not empresa:
            continue
        try:
            precio = float(str(r.get("precio", 0)).replace(",", "."))
        except ValueError:
            precio = 0.0
        rows.append({
            "empresa": empresa,
            "codigo": str(r.get("codigo", "")).strip(),
            "descripcion": str(r.get("descripcion", "")).strip(),
            "unidad": str(r.get("unidad", "")).strip(),
            "precio": precio,
        })
    return rows


def get_empresas(precios_rows):
    seen = {}
    for r in precios_rows:
        if r["empresa"].strip().lower() in LISTA_PRECIOS_EXCLUIDAS:
            continue
        seen.setdefault(r["empresa"], True)
    return sorted(seen.keys(), key=lambda s: s.lower())


def load_pedidos(gc):
    ws = gc.open_by_key(PEDIDOS_SHEET_ID).sheet1
    records = ws.get_all_records()
    rows = []
    for r in records:
        cliente_texto = str(r.get("Cliente (texto ingresado)", "")).strip()
        cliente_sugerido = str(r.get("Cliente (sugerencia automatica)", "")).strip()
        producto = str(r.get("Producto", "")).strip()
        if not cliente_texto and not producto:
            continue
        try:
            cantidad = float(str(r.get("Cantidad", 0)).replace(",", "."))
        except ValueError:
            cantidad = 0.0
        rows.append({
            "fecha_solicitud": str(r.get("Fecha Solicitud", "")).strip(),
            "fecha_despacho": str(r.get("Fecha Despacho Deseada", "")).strip(),
            "cliente_texto": cliente_texto,
            "cliente_sugerido": cliente_sugerido,
            "producto": producto,
            "unidad": str(r.get("Unidad", "")).strip(),
            "cantidad": cantidad,
        })
    return rows


_CLIENT_COLS = {
    "razon_social": "Primer Nombre ó Razon Social",
    "nit": "Identificación",
    "lista_precios": "Lista Precios",
    "forma_pago": "Forma Pago",
    "plazo_dias": "Plazo Días",
    "direccion": "Dirección",
    "telefono": "Teléfonos",
    "ciudad": "Ciudad Dirección",
    "email": "Email",
}


def load_client_master(drive_service):
    """Descarga BASE DE DATOS CLIENTES ACTIVOS.xlsx (archivo Office subido a
    Drive - la API de Sheets no puede leerlo directamente) y lo parsea."""
    request = drive_service.files().get_media(fileId=CLIENTS_MASTER_FILE_ID)
    raw = request.execute()
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    header = [str(h or "").strip() for h in all_rows[0]]
    idx = {h: i for i, h in enumerate(header)}

    def col(row, key):
        header_name = _CLIENT_COLS[key]
        i = idx.get(header_name)
        if i is None or i >= len(row):
            return ""
        v = row[i]
        return str(v).strip() if v is not None else ""

    rows = []
    for row in all_rows[1:]:
        razon = col(row, "razon_social")
        if not razon:
            continue
        rows.append({k: col(row, k) for k in _CLIENT_COLS})
    return rows


# ---------------------------------------------------------------------------
# Cruce de pedidos + precios + base de clientes
# ---------------------------------------------------------------------------
def cross_reference(pedidos_rows, precios_rows, client_master_rows):
    empresas = get_empresas(precios_rows)
    precios_by_empresa = {}
    for r in precios_rows:
        precios_by_empresa.setdefault(r["empresa"], []).append(r)

    enriched = []
    for p in pedidos_rows:
        cliente_para_match = p["cliente_sugerido"] or p["cliente_texto"]
        empresa_matched, score_empresa = matching.match_empresa(cliente_para_match, empresas)

        precio_row = None
        if empresa_matched:
            precio_row = matching.match_product(p["producto"], precios_by_empresa.get(empresa_matched, []))

        cliente_master = matching.match_client_master(empresa_matched, cliente_para_match, client_master_rows)

        row = dict(p)
        row["cliente_para_match"] = cliente_para_match
        row["empresa_matched"] = empresa_matched or NO_APARECE
        row["similitud_empresa"] = score_empresa
        row["precio_encontrado"] = precio_row is not None
        row["codigo"] = precio_row["codigo"] if precio_row else NO_APARECE
        row["descripcion_precio"] = precio_row["descripcion"] if precio_row else NO_APARECE
        row["unidad_precio"] = precio_row["unidad"] if precio_row else (p["unidad"] or NO_APARECE)
        row["precio_unitario"] = precio_row["precio"] if precio_row else None
        row["valor_total"] = round(precio_row["precio"] * p["cantidad"]) if precio_row else None

        row["cliente_master_encontrado"] = cliente_master is not None
        row["cliente_oficial"] = cliente_master["razon_social"] if cliente_master else NO_APARECE
        row["nit"] = cliente_master["nit"] if cliente_master and cliente_master["nit"] else NO_APARECE
        row["direccion"] = cliente_master["direccion"] if cliente_master and cliente_master["direccion"] else NO_APARECE
        row["ciudad"] = cliente_master["ciudad"] if cliente_master and cliente_master["ciudad"] else NO_APARECE
        row["telefono"] = cliente_master["telefono"] if cliente_master and cliente_master["telefono"] else NO_APARECE
        row["forma_pago"] = cliente_master["forma_pago"] if cliente_master and cliente_master["forma_pago"] else NO_APARECE
        row["plazo_dias"] = cliente_master["plazo_dias"] if cliente_master and cliente_master["plazo_dias"] else ""

        enriched.append(row)
    return enriched


OUTPUT_HEADERS = [
    "Fecha Solicitud", "Fecha Despacho Deseada", "Cliente (texto ingresado)",
    "Cliente (sugerencia automatica)", "Empresa (lista de precios)",
    "Similitud empresa (%)", "Producto", "Unidad", "Cantidad",
    "Codigo", "Precio unitario", "Valor total", "Precio encontrado",
    "Cliente oficial (razon social)", "NIT", "Direccion", "Ciudad",
    "Telefono", "Forma de pago", "Plazo dias", "Cliente encontrado en base",
]


def enriched_to_rows(enriched):
    rows = []
    for r in enriched:
        rows.append([
            r["fecha_solicitud"], r["fecha_despacho"], r["cliente_texto"],
            r["cliente_sugerido"], r["empresa_matched"], r["similitud_empresa"],
            r["producto"], r["unidad"], r["cantidad"],
            r["codigo"], r["precio_unitario"] if r["precio_unitario"] is not None else NO_APARECE,
            r["valor_total"] if r["valor_total"] is not None else NO_APARECE,
            "Si" if r["precio_encontrado"] else "No",
            r["cliente_oficial"], r["nit"], r["direccion"], r["ciudad"],
            r["telefono"], r["forma_pago"], r["plazo_dias"],
            "Si" if r["cliente_master_encontrado"] else "No",
        ])
    return rows


# ---------------------------------------------------------------------------
# Hoja de resultado en Drive ("Integracion AI")
# ---------------------------------------------------------------------------
def find_or_create_output_sheet(gc, drive_service):
    q = (
        f"name = '{OUTPUT_SHEET_TITLE}' and "
        f"'{INTEGRACION_AI_FOLDER_ID}' in parents and trashed = false and "
        "mimeType = 'application/vnd.google-apps.spreadsheet'"
    )
    res = drive_service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return gc.open_by_key(files[0]["id"])

    meta = {
        "name": OUTPUT_SHEET_TITLE,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [INTEGRACION_AI_FOLDER_ID],
    }
    created = drive_service.files().create(body=meta, fields="id").execute()
    return gc.open_by_key(created["id"])


def write_output_sheet(sh, enriched_rows):
    ws = sh.sheet1
    ws.update_title("Pedidos con precios")
    ws.clear()
    values = [OUTPUT_HEADERS] + enriched_to_rows(enriched_rows)
    ws.update(values, value_input_option="USER_ENTERED")
    try:
        ws.freeze(rows=1)
    except Exception:
        pass


def get_next_invoice_number(sh):
    try:
        ws = sh.worksheet("contador_facturas")
    except Exception:
        ws = sh.add_worksheet(title="contador_facturas", rows=5, cols=2)
        ws.update([["siguiente_numero"], ["1"]], value_input_option="USER_ENTERED")

    val = ws.acell("A2").value
    try:
        numero = int(float(val))
    except (TypeError, ValueError):
        numero = 1
    ws.update_acell("A2", str(numero + 1))
    return numero


# ---------------------------------------------------------------------------
# Helpers de fecha / agrupacion para las facturas
# ---------------------------------------------------------------------------
def parse_fecha(s):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def fmt_fecha_dmy(dt):
    return dt.strftime("%d/%m/%Y") if dt else NO_APARECE


def calcular_vencimiento(fecha_dt, plazo_dias):
    if fecha_dt is None:
        return NO_APARECE
    try:
        dias = int(float(plazo_dias))
    except (TypeError, ValueError):
        dias = PLAZO_DIAS_DEFAULT
    return fmt_fecha_dmy(fecha_dt + timedelta(days=dias))


def build_invoice_groups(enriched_rows):
    """Agrupa por (cliente tal como llego el pedido, fecha de despacho) -
    una factura por cada grupo, en el orden en que aparecen los pedidos."""
    groups = {}
    order = []
    for r in enriched_rows:
        key = (r["cliente_para_match"], r["fecha_despacho"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)
    return [(k, groups[k]) for k in order]


def build_invoice_payload(group_key, rows, numero_factura):
    """Arma el dict que espera pdf_factura.build_invoice_pdf a partir de un
    grupo (cliente, fecha de despacho) de filas ya cruzadas con precios."""
    cliente_display, fecha_despacho_str = group_key
    fecha_dt = parse_fecha(fecha_despacho_str)
    first = rows[0]

    items = []
    for r in rows:
        items.append({
            "codigo": r["codigo"] if r["precio_encontrado"] else NO_APARECE,
            "descripcion": r["producto"],
            "unidad": r["unidad"] or r["unidad_precio"],
            "cantidad": r["cantidad"],
            "valor_unitario": r["precio_unitario"] if r["precio_encontrado"] else 0,
            "encontrado": r["precio_encontrado"],
        })

    return {
        "numero_factura": numero_factura,
        "cliente_nombre": first["cliente_oficial"],
        "cliente_nit": first["nit"] if first["nit"] != NO_APARECE else None,
        "cliente_direccion": first["direccion"],
        "cliente_ciudad": first["ciudad"],
        "cliente_telefono": first["telefono"],
        "forma_pago": first["forma_pago"],
        "fecha": fmt_fecha_dmy(fecha_dt) if fecha_dt else (fecha_despacho_str or NO_APARECE),
        "vencimiento": calcular_vencimiento(fecha_dt, first["plazo_dias"]),
        "concepto": cliente_display,
        "items": items,
    }
