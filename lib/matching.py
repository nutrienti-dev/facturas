"""
Logica de cruce (fuzzy matching) entre:
- el texto de cliente tal como llega en los pedidos (con nombre de punto/sede)
- las "empresas" de la hoja de precios por cliente (nombre de cadena, sin sede)
- la razon social oficial en la base de clientes activos (NIT, direccion, etc.)
- el nombre de producto del pedido vs la descripcion en la lista de precios

No usa librerias externas de fuzzy matching (rapidfuzz no esta disponible en
todos los entornos) - solo difflib de la libreria estandar de Python.
"""
import re
import unicodedata
from difflib import SequenceMatcher

# Sufijos legales comunes en razones sociales colombianas, para poder comparar
# "LA BIFERIA S A" contra "La biferia" ignorando el tipo societario.
LEGAL_SUFFIXES = {
    "s.a.s", "sas", "s.a", "sa", "s a", "ltda", "cia", "compania", "compania.",
    "e.u", "eu", "y cia", "and cia",
}

# Umbrales de aceptacion (0-1). Se dejan como constantes de modulo para poder
# ajustarlos facilmente si el negocio los quiere mas estrictos/laxos.
UMBRAL_EMPRESA = 0.72
UMBRAL_CLIENTE_MASTER = 0.60
UMBRAL_PRODUCTO = 0.78
UMBRAL_NOMBRE_COMERCIAL = 0.72


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(s):
    s = strip_accents(str(s or "")).lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_legal_suffix(name_norm):
    words = name_norm.split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    # tambien maneja "s a s" como 3 tokens sueltos al final
    while len(words) >= 2 and " ".join(words[-2:]) in LEGAL_SUFFIXES:
        words = words[:-2]
    return " ".join(words)


def similarity(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def match_empresa(pedido_cliente_text, empresas):
    """Encuentra la 'empresa' (nombre de cadena, sin sede) de la hoja de
    precios que mejor corresponde al texto de cliente del pedido.

    Devuelve (empresa_original_o_None, score_0_a_100).
    """
    text_norm = normalize(pedido_cliente_text)
    if not text_norm:
        return None, 0.0

    best = None
    best_score = 0.0
    for emp in empresas:
        emp_norm = normalize(emp)
        if not emp_norm:
            continue
        if text_norm.startswith(emp_norm):
            score = 1.0
        else:
            n_words = len(emp_norm.split())
            prefix = " ".join(text_norm.split()[:n_words])
            score = similarity(prefix, emp_norm)
            score = max(score, similarity(text_norm, emp_norm) * 0.9)
        if score > best_score:
            best_score = score
            best = emp

    if best is not None and best_score >= UMBRAL_EMPRESA:
        return best, round(best_score * 100, 1)
    return None, round(best_score * 100, 1)


def match_client_master(empresa_matched, pedido_cliente_candidates, client_rows):
    """Busca en la base de clientes activos (World Office) la fila que
    corresponde a la empresa/cliente ya identificada.

    Estrategia (en orden):
      1) Coincidencia exacta (normalizada) contra la columna 'Lista Precios'.
      2) Fuzzy match de la razon social contra el nombre de empresa / los
         textos candidatos del pedido, ignorando sufijos societarios
         (SAS, S.A., etc.)

    pedido_cliente_candidates: un string, o una lista de strings (ej. texto
    ingresado y sugerencia automatica) - se probam todos como respaldo.
    client_rows: lista de dicts con llaves razon_social, lista_precios, ...
    Devuelve el dict de la fila encontrada, o None.
    """
    if not client_rows:
        return None

    if isinstance(pedido_cliente_candidates, str):
        pedido_cliente_candidates = [pedido_cliente_candidates]

    emp_norm = normalize(empresa_matched) if empresa_matched else ""

    if emp_norm:
        for row in client_rows:
            if normalize(row.get("lista_precios", "")) == emp_norm:
                return row

    candidatos_norm = [normalize(c) for c in pedido_cliente_candidates]
    targets = []
    for t in [emp_norm] + candidatos_norm:
        if t and t not in targets:
            targets.append(t)
    best = None
    best_score = 0.0
    for row in client_rows:
        razon_norm = normalize(row.get("razon_social", ""))
        razon_stripped = strip_legal_suffix(razon_norm)
        for target in targets:
            target_stripped = strip_legal_suffix(target)
            if not razon_stripped or not target_stripped:
                continue
            score = similarity(razon_stripped, target_stripped)
            if razon_stripped in target_stripped or target_stripped in razon_stripped:
                score = max(score, 0.9)
            if score > best_score:
                best_score = score
                best = row

    if best is not None and best_score >= UMBRAL_CLIENTE_MASTER:
        return best
    return None


def match_nombre_comercial(pedido_cliente_candidates, nc_rows):
    """Busca en el mapa "RAZONES SOCIALES - NOMBRES COMERCIALES" el punto de
    venta que mejor corresponde al texto del pedido, y devuelve la razon
    social asociada a ese punto.

    Esta es la fuente de verdad para resolver el punto: muchos puntos NO
    tienen ningun parecido textual con la razon social ni con la "empresa"
    de la lista de precios (ej. "Astoria" / "Bombay" / "Sexy Seoul" son
    puntos de la razon social "ALTAS VISTAS SAS"; "Osaki" / "Sorella" /
    "Caccio y Pepe" son puntos de "TAKAMI SA"). Antes de este mapa, el cruce
    solo funcionaba cuando el nombre del punto empezaba igual que la cadena.

    pedido_cliente_candidates: string, o lista de strings (texto ingresado y
    sugerencia automatica) - se prueban todos.
    nc_rows: lista de dicts con llaves razon_social / nombre_comercial.
    Devuelve (razon_social_o_None, nombre_comercial_encontrado_o_None,
    score_0_a_100).
    """
    if not nc_rows:
        return None, None, 0.0
    if isinstance(pedido_cliente_candidates, str):
        pedido_cliente_candidates = [pedido_cliente_candidates]
    candidatos_norm = [normalize(c) for c in pedido_cliente_candidates]
    candidatos_norm = [c for c in candidatos_norm if c]
    if not candidatos_norm:
        return None, None, 0.0

    best_row = None
    best_score = 0.0
    for row in nc_rows:
        nc_norm = normalize(row.get("nombre_comercial", ""))
        if not nc_norm:
            continue
        for text_norm in candidatos_norm:
            if text_norm == nc_norm:
                score = 1.0
            elif text_norm.startswith(nc_norm) or nc_norm.startswith(text_norm):
                # prefijo en cualquier direccion (ej. pedido "astoria" vs
                # punto "astoria santafe", o al reves si el pedido trae mas
                # texto que el nombre corto del punto).
                shorter = min(len(text_norm), len(nc_norm))
                longer = max(len(text_norm), len(nc_norm))
                score = 0.85 + 0.15 * (shorter / longer)
            else:
                score = similarity(text_norm, nc_norm)
            if score > best_score:
                best_score = score
                best_row = row

    if best_row is not None and best_score >= UMBRAL_NOMBRE_COMERCIAL:
        razon = (best_row.get("razon_social") or "").strip() or None
        nc = (best_row.get("nombre_comercial") or "").strip() or None
        return razon, nc, round(best_score * 100, 1)
    return None, None, round(best_score * 100, 1)


def find_client_master_by_razon(razon_social, client_rows):
    """Busca en la base de clientes activos la fila cuya razon social
    corresponde (ignorando sufijos societarios como SAS/S.A./LTDA) a
    razon_social, tal como viene resuelta por match_nombre_comercial."""
    if not razon_social or not client_rows:
        return None
    target_norm = strip_legal_suffix(normalize(razon_social))
    if not target_norm:
        return None

    best = None
    best_score = 0.0
    for row in client_rows:
        razon_norm = strip_legal_suffix(normalize(row.get("razon_social", "")))
        if not razon_norm:
            continue
        if razon_norm == target_norm:
            return row
        score = similarity(razon_norm, target_norm)
        if score > best_score:
            best_score = score
            best = row

    if best is not None and best_score >= UMBRAL_CLIENTE_MASTER:
        return best
    return None


def match_product(pedido_producto, precios_rows_for_empresa):
    """precios_rows_for_empresa: lista de dicts codigo/descripcion/unidad/precio
    (ya filtrada a la empresa que se determino para el cliente).
    Devuelve el dict de precio encontrado, o None.
    """
    if not precios_rows_for_empresa:
        return None
    prod_norm = normalize(pedido_producto)
    best = None
    best_score = 0.0
    for row in precios_rows_for_empresa:
        desc_norm = normalize(row["descripcion"])
        score = 1.0 if desc_norm == prod_norm else similarity(prod_norm, desc_norm)
        if score > best_score:
            best_score = score
            best = row
    if best is not None and best_score >= UMBRAL_PRODUCTO:
        return best
    return None
