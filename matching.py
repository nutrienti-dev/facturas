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


def match_client_master(empresa_matched, pedido_cliente_text, client_rows):
    """Busca en la base de clientes activos (World Office) la fila que
    corresponde a la empresa/cliente ya identificada.

    Estrategia (en orden):
      1) Coincidencia exacta (normalizada) contra la columna 'Lista Precios'.
      2) Fuzzy match de la razon social contra el nombre de empresa / texto
         del pedido, ignorando sufijos societarios (SAS, S.A., etc.)

    client_rows: lista de dicts con llaves razon_social, lista_precios, ...
    Devuelve el dict de la fila encontrada, o None.
    """
    if not client_rows:
        return None

    emp_norm = normalize(empresa_matched) if empresa_matched else ""

    if emp_norm:
        for row in client_rows:
            if normalize(row.get("lista_precios", "")) == emp_norm:
                return row

    targets = [t for t in (emp_norm, normalize(pedido_cliente_text)) if t]
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
