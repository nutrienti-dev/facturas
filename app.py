"""
Nutrienti - Facturacion
Cruza los pedidos registrados por la app de pedidos con la lista de precios
por cliente y la base de clientes activos (World Office), guarda el
resultado en una Google Sheet y genera facturas en PDF por cliente, por
fecha o por ambos criterios.
"""
import io
import re

import pandas as pd
import streamlit as st
from googleapiclient.http import MediaIoBaseUpload

from lib import data, gauth
from lib.pdf_factura import build_invoice_pdf

st.set_page_config(
    page_title="Nutrienti | Facturacion",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .nutrienti-header {
        background: linear-gradient(135deg, #2E7D32 0%, #66BB6A 100%);
        padding: 1.6rem 1.4rem;
        border-radius: 14px;
        color: white;
        margin-bottom: 1.4rem;
    }
    .nutrienti-header h1 { margin: 0; font-size: 1.6rem; }
    .nutrienti-header p { margin: 0.2rem 0 0 0; opacity: 0.92; font-size: 0.95rem; }
    .warn-badge { color: #B71C1C; font-weight: 600; }
    .ok-badge { color: #1B5E20; font-weight: 600; }
    </style>
    <div class="nutrienti-header">
        <h1>🧾 Nutrienti — Facturacion</h1>
        <p>Cruza pedidos con precios por cliente y genera las facturas en PDF.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Conexion a Google
# ---------------------------------------------------------------------------
gc = gauth.get_gspread_client()
drive_service = gauth.get_drive_service()

if gc is None or drive_service is None:
    st.error(
        "No se encontraron credenciales de Google en `st.secrets['gcp_oauth']`. "
        "Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` y "
        "completa tus credenciales (ver README.md)."
    )
    st.stop()


def sheet_link(spreadsheet_id):
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def folder_link(folder_id):
    return f"https://drive.google.com/drive/folders/{folder_id}"


# ---------------------------------------------------------------------------
# Paso 1: cruzar pedidos con precios
# ---------------------------------------------------------------------------
st.subheader("1. Cruzar pedidos con precios")
st.caption(
    "Lee la hoja de pedidos y la lista de precios por cliente, hace el cruce "
    "(el nombre del cliente en el pedido suele incluir el punto/sede, ej. "
    '"La biferia Santafe"; se busca la cadena/empresa correspondiente en la '
    "lista de precios sin importar el punto) y escribe el resultado en una "
    "Google Sheet dentro de la carpeta **Integracion AI**."
)

col_a, col_b = st.columns([1, 3])
with col_a:
    cruzar_clicked = st.button("🔄 Cruzar pedidos con precios", type="primary", use_container_width=True)

if cruzar_clicked:
    with st.spinner("Cargando pedidos, precios y base de clientes..."):
        try:
            pedidos_rows = data.load_pedidos(gc)
            precios_rows = data.load_precios(gc)
            client_master_rows = data.load_client_master(drive_service)
            enriched = data.cross_reference(pedidos_rows, precios_rows, client_master_rows)
        except Exception as e:
            st.error(f"No se pudo cargar o cruzar la informacion: {e}")
            st.stop()

    with st.spinner("Escribiendo resultado en Google Sheets..."):
        try:
            sh = data.find_or_create_output_sheet(gc, drive_service)
            data.write_output_sheet(sh, enriched)
        except Exception as e:
            st.error(f"No se pudo escribir la hoja de resultado: {e}")
            st.stop()

    st.session_state["enriched"] = enriched
    st.session_state["output_sheet_id"] = sh.id
    st.success(f"Listo: {len(enriched)} lineas de pedido cruzadas.")

if "enriched" in st.session_state:
    enriched = st.session_state["enriched"]
    df = pd.DataFrame(data.enriched_to_rows(enriched), columns=data.OUTPUT_HEADERS)
    n_total = len(df)
    n_sin_precio = (df["Precio encontrado"] == "No").sum()
    n_sin_cliente = (df["Cliente encontrado en base"] == "No").sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("Lineas de pedido", n_total)
    m2.metric("Sin precio encontrado", int(n_sin_precio))
    m3.metric("Sin cliente en base de datos", int(n_sin_cliente))

    if "output_sheet_id" in st.session_state:
        st.markdown(f"📄 [Ver hoja de resultado en Google Sheets]({sheet_link(st.session_state['output_sheet_id'])})")

    def _highlight(row):
        color = "background-color: #FFEBEE" if row["Precio encontrado"] == "No" else ""
        return [color] * len(row)

    st.dataframe(df.style.apply(_highlight, axis=1), use_container_width=True, height=320)
else:
    st.info("Todavia no has cruzado los pedidos en esta sesion. Dale click al boton de arriba.")

st.divider()

# ---------------------------------------------------------------------------
# Paso 2: generar facturas PDF
# ---------------------------------------------------------------------------
st.subheader("2. Generar facturas en PDF")

if "enriched" not in st.session_state:
    st.info("Primero cruza los pedidos con precios (paso 1) para poder generar facturas.")
    st.stop()

enriched = st.session_state["enriched"]
all_groups = data.build_invoice_groups(enriched)  # [(cliente, fecha), rows]
clientes_disponibles = sorted({g[0][0] for g in all_groups}, key=lambda s: s.lower())
fechas_disponibles = sorted({g[0][1] for g in all_groups})

st.caption(
    "Cada factura corresponde a un cliente + una fecha de despacho (tal como "
    "quedaron agrupados los pedidos). Elige como quieres filtrar cuales generar."
)

modo = st.radio(
    "Generar facturas por:",
    options=["Cliente", "Fecha", "Cliente y fecha"],
    horizontal=True,
)

clientes_sel = None
fechas_sel = None
if modo in ("Cliente", "Cliente y fecha"):
    clientes_sel = st.multiselect("Cliente(s)", options=clientes_disponibles)
if modo in ("Fecha", "Cliente y fecha"):
    fechas_sel = st.multiselect("Fecha(s) de despacho", options=fechas_disponibles)

def group_matches(key):
    cliente, fecha = key
    if clientes_sel is not None and cliente not in clientes_sel:
        return False
    if fechas_sel is not None and fecha not in fechas_sel:
        return False
    return True

grupos_filtrados = [(k, rows) for k, rows in all_groups if group_matches(k)]
st.write(f"**{len(grupos_filtrados)}** factura(s) coinciden con el filtro de **{len(all_groups)}** disponibles.")

generar_clicked = st.button(
    "🧾 Generar facturas PDF y subirlas a 'facturas de prueba'",
    type="primary",
    disabled=(len(grupos_filtrados) == 0),
)

if generar_clicked:
    sh = gc.open_by_key(st.session_state["output_sheet_id"])
    resultados = []
    progress = st.progress(0.0)
    for i, (key, rows) in enumerate(grupos_filtrados, start=1):
        numero = data.get_next_invoice_number(sh)
        payload = data.build_invoice_payload(key, rows, numero)
        pdf_bytes, totals = build_invoice_pdf(payload)

        cliente_slug = re.sub(r"[^A-Za-z0-9]+", "_", key[0]).strip("_")
        fecha_dt = data.parse_fecha(key[1])
        fecha_slug = fecha_dt.strftime("%Y%m%d") if fecha_dt else re.sub(r"[^0-9]", "", key[1])
        filename = f"FE{numero}_{cliente_slug}_{fecha_slug}.pdf"

        try:
            media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf", resumable=False)
            file_meta = {"name": filename, "parents": [data.FACTURAS_FOLDER_ID]}
            created = drive_service.files().create(body=file_meta, media_body=media, fields="id, webViewLink").execute()
            drive_link = created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view"
        except Exception as e:
            drive_link = f"Error al subir: {e}"

        resultados.append({
            "numero": numero,
            "cliente": payload["cliente_nombre"],
            "concepto": payload["concepto"],
            "fecha": payload["fecha"],
            "total": totals["total_documento"],
            "drive_link": drive_link,
            "filename": filename,
            "pdf_bytes": pdf_bytes,
        })
        progress.progress(i / len(grupos_filtrados))

    st.session_state["ultimas_facturas"] = resultados
    st.success(f"Se generaron {len(resultados)} factura(s).")
    st.markdown(f"📁 [Ver carpeta 'facturas de prueba' en Drive]({folder_link(data.FACTURAS_FOLDER_ID)})")

if "ultimas_facturas" in st.session_state:
    st.write("### Facturas generadas")
    for r in st.session_state["ultimas_facturas"]:
        c1, c2, c3, c4, c5 = st.columns([1, 3, 2, 2, 2])
        c1.write(f"**FE {r['numero']}**")
        c2.write(f"{r['cliente']}  \n_{r['concepto']}_")
        c3.write(r["fecha"])
        c4.write(f"$ {r['total']:,.0f}".replace(",", "."))
        with c5:
            st.download_button(
                "⬇️ PDF", data=r["pdf_bytes"], file_name=r["filename"],
                mime="application/pdf", key=f"dl_{r['numero']}",
            )
