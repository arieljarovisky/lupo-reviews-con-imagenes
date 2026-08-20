#!/usr/bin/env python3
"""Cruza opiniones de Mercado Libre con productos de Tiendanube e importa a Supabase."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import ssl

import certifi
import pandas as pd
import urllib.error
import urllib.request

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = Path('/Users/arieljarovisky/Downloads/opiniones_mercadolibre_20260820.xlsx')
DEFAULT_CSV = Path('/Users/arieljarovisky/Downloads/productos_tiendanube_20260820.csv')
REPORT_DIR = ROOT / 'scripts' / 'import-output'

CATS = [
    ('correa', 'correa'),
    ('hilo dental', 'hilo'),
    ('vedetina', 'vedetina'),
    ('bombacha', 'bombacha'),
    ('corpino', 'corpino'),
    ('corpiño', 'corpino'),
    ('boxer', 'boxer'),
    ('slip', 'slip'),
    ('faja', 'faja'),
    ('bermuda', 'bermuda'),
    ('soquete', 'soquete'),
    ('medias', 'medias'),
    ('media', 'medias'),
    ('body', 'body'),
    ('top', 'top'),
    ('calza', 'calza'),
    ('short', 'short'),
    ('colaless', 'colaless'),
    ('colales', 'colaless'),
]

# Categorías equivalentes para matching
CAT_ALIASES = {
    'hilo': {'hilo', 'faja', 'colaless', 'bombacha'},
    'colaless': {'colaless', 'faja', 'hilo', 'vedetina', 'bombacha'},
    'vedetina': {'vedetina', 'bombacha'},
    'bombacha': {'bombacha', 'vedetina', 'colaless'},
}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


def strip_accents(s: str) -> str:
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = strip_accents(str(s).lower())
    s = re.sub(r'[^a-z0-9\s-]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def category(text: str) -> str | None:
    t = norm(text)
    for needle, cat in CATS:
        if needle in t:
            return cat
    return None


def cats_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    if a == b:
        return True
    return b in CAT_ALIASES.get(a, set()) or a in CAT_ALIASES.get(b, set())


def gender(text: str) -> str | None:
    t = norm(text)
    if any(x in t for x in ('hombre', 'masculino', 'caballero')):
        return 'm'
    if any(x in t for x in ('mujer', 'femenin', 'dama', 'loba')):
        return 'f'
    return None


def model_codes(text: str) -> set[str]:
    t = norm(text)
    t = re.sub(r'\b(mod|art|modelo)\b\.?', ' ', t)
    # códigos pegados al texto: 47183apto, 40460pack
    t = re.sub(r'(\d{3,5}(?:-\d{1,3})?)[a-z]+', r'\1 ', t)
    codes: set[str] = set()
    for m in re.findall(r'\b\d{3,5}(?:-\d{1,3})?\b', t):
        codes.add(m)
        codes.add(m.replace('-', ''))
    return codes


def tokens(text: str) -> set[str]:
    stop = {
        'lupo', 'loba', 'by', 'de', 'la', 'el', 'en', 'y', 'con', 'sin', 'pack',
        'talle', 'talla', 'color', 'negro', 'beige', 'blanco', 'mujer', 'hombre',
        'unidad', 'unidades', 'premium', 'comodo', 'clasica', 'clasico', 'para',
    }
    return {w for w in norm(text).split() if len(w) > 2 and w not in stop and not w.isdigit()}


def build_products(tn: pd.DataFrame) -> list[dict]:
    products = []
    for _, r in tn.iterrows():
        name = str(r['name'])
        url = str(r['url'])
        sku = str(r.get('sku', ''))
        blob = f'{name} {url} {sku}'
        products.append({
            'product_id': str(r['product_id']),
            'name': name,
            'url': url,
            'cat': category(blob),
            'gender': gender(name),
            'codes': model_codes(blob),
            'tokens': tokens(name),
        })
    return products


def score_pair(ml_title: str, p: dict) -> tuple[float, dict]:
    ml_codes = model_codes(ml_title)
    ml_cat = category(ml_title)
    ml_g = gender(ml_title)
    ml_tok = tokens(ml_title)
    inter_codes = ml_codes & p['codes']
    code_bonus = max((len(c) for c in inter_codes), default=0)

    if ml_cat and p['cat']:
        if ml_cat == p['cat']:
            cat_ok = 2
        elif cats_compatible(ml_cat, p['cat']):
            cat_ok = 1
        else:
            cat_ok = 0
    else:
        cat_ok = 1

    if ml_g and p['gender'] and ml_g != p['gender']:
        gender_pen = -4
    elif ml_g and p['gender'] and ml_g == p['gender']:
        gender_pen = 1
    else:
        gender_pen = 0

    tok_inter = ml_tok & p['tokens']
    tok_union = ml_tok | p['tokens']
    jacc = len(tok_inter) / len(tok_union) if tok_union else 0
    score = code_bonus * 10 + cat_ok * 5 + gender_pen + jacc * 20 + len(tok_inter)
    if cat_ok == 0 and code_bonus == 0:
        score -= 20
    return score, {
        'code_bonus': code_bonus,
        'codes': sorted(inter_codes),
        'cat_ok': cat_ok,
        'ml_cat': ml_cat,
        'tn_cat': p['cat'],
        'jacc': round(jacc, 3),
        'gender_pen': gender_pen,
    }


def match_product(title: str, products: list[dict]) -> tuple[dict, str, dict, float, float]:
    scored = []
    for p in products:
        s, meta = score_pair(title, p)
        scored.append((s, meta, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_s, meta, best_p = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0

    conf = 'low'
    if meta['code_bonus'] >= 4 and meta['cat_ok'] >= 1:
        conf = 'high'
    elif meta['cat_ok'] >= 1 and meta['jacc'] >= 0.45 and best_s - second >= 1.5:
        conf = 'high'
    elif meta['cat_ok'] == 2 and meta['jacc'] >= 0.35:
        conf = 'high'
    elif meta['cat_ok'] >= 1 and meta['jacc'] >= 0.25:
        conf = 'medium'
    elif meta['code_bonus'] >= 3 and meta['cat_ok'] >= 1:
        conf = 'medium'
    elif best_s >= 16 and meta['cat_ok'] >= 1:
        conf = 'medium'
    return best_p, conf, meta, best_s, second


def ensure_comment(title: str, content: str) -> str:
    title = (title or '').strip()
    content = (content or '').strip()
    if content.lower() in {'nan', 'none'}:
        content = ''
    if title.lower() in {'nan', 'none'}:
        title = ''
    parts = [p for p in (title, content) if p]
    text = '. '.join(parts).strip() if parts else 'Reseña importada desde Mercado Libre.'
    text = re.sub(r'\s+', ' ', text)
    if len(text) < 10:
        text = f'{text} Producto recomendado.'.strip()
    return text[:1200]


def supabase_request(method: str, path: str, body=None, params: str = '') -> object:
    base = os.environ['SUPABASE_URL'].rstrip('/')
    key = os.environ['SUPABASE_SERVICE_ROLE_KEY']
    url = f'{base}/rest/v1/{path}{params}'
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('apikey', key)
    req.add_header('Authorization', f'Bearer {key}')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Prefer', 'return=representation')
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        detail = err.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Supabase {method} {path}: {err.code} {detail}') from err


def fetch_existing_ml_emails() -> set[str]:
    from urllib.parse import quote
    filt = quote('like.ml-review-*@import.lupo.local', safe='')
    rows = supabase_request(
        'GET',
        'reviews',
        params=f'?customer_email={filt}&select=customer_email'
    ) or []
    return {r['customer_email'] for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description='Importar opiniones ML a Lupo Reviews')
    parser.add_argument('--xlsx', type=Path, default=DEFAULT_XLSX)
    parser.add_argument('--products', type=Path, default=DEFAULT_CSV)
    parser.add_argument('--apply', action='store_true', help='Inserta en Supabase (sin esto solo genera reporte)')
    parser.add_argument(
        '--status',
        choices=('approved', 'pending'),
        default='approved',
        help='Estado de las reseñas importadas (default: approved)',
    )
    parser.add_argument('--min-confidence', choices=('high', 'medium'), default='medium')
    args = parser.parse_args()

    load_dotenv(ROOT / '.env')
    if args.apply and (not os.environ.get('SUPABASE_URL') or not os.environ.get('SUPABASE_SERVICE_ROLE_KEY')):
        print('Faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY en .env', file=sys.stderr)
        return 1

    ml_summary = pd.read_excel(args.xlsx, sheet_name='Resumen publicaciones')
    opinions = pd.read_excel(args.xlsx, sheet_name='Opiniones')
    tn = pd.read_csv(args.products)
    products = build_products(tn)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    mapping_path = REPORT_DIR / 'ml-to-tiendanube-mapping.csv'
    preview_path = REPORT_DIR / 'reviews-preview.csv'

    allowed = {'high'} if args.min_confidence == 'high' else {'high', 'medium'}
    mapping_rows = []
    item_match: dict[str, dict] = {}

    for _, row in ml_summary.iterrows():
        item_id = str(row['Item ID'])
        title = str(row['Título'])
        product, conf, meta, score, second = match_product(title, products)
        item_match[item_id] = {
            'product': product,
            'confidence': conf,
            'meta': meta,
            'score': score,
        }
        mapping_rows.append({
            'item_id': item_id,
            'ml_title': title,
            'opiniones': int(row['Opiniones (total)']),
            'confidence': conf,
            'score': round(score, 2),
            'score_2nd': round(second, 2),
            'tn_product_id': product['product_id'],
            'tn_name': product['name'],
            'tn_url': product['url'],
            'shared_codes': '|'.join(meta['codes']),
            'ml_cat': meta['ml_cat'] or '',
            'tn_cat': meta['tn_cat'] or '',
            'jaccard': meta['jacc'],
            'will_import': conf in allowed,
        })

    with mapping_path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(mapping_rows[0].keys()))
        writer.writeheader()
        writer.writerows(mapping_rows)

    preview_rows = []
    for _, op in opinions.iterrows():
        item_id = str(op['Item ID'])
        match = item_match.get(item_id)
        if not match or match['confidence'] not in allowed:
            continue
        product = match['product']
        review_id = str(op['Review ID'])
        comment = ensure_comment(str(op.get('Título opinión', '')), str(op.get('Contenido', '')))
        title = str(op.get('Título opinión', '') or '').strip()
        if title.lower() in {'nan', 'none'}:
            title = ''
        preview_rows.append({
            'ml_review_id': review_id,
            'item_id': item_id,
            'confidence': match['confidence'],
            'product_id': product['product_id'],
            'product_name': product['name'],
            'product_url': product['url'],
            'customer_name': 'Cliente Mercado Libre',
            'customer_email': f'ml-review-{review_id}@import.lupo.local',
            'rating': int(op['Estrellas']),
            'title': title[:100],
            'comment': comment,
            'status': args.status,
            'verified_purchase': True,
            'created_at': str(op.get('Fecha opinión') or ''),
            'image_urls': [],
        })

    with preview_path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(preview_rows[0].keys()) if preview_rows else ['ml_review_id'])
        writer.writeheader()
        writer.writerows(preview_rows)

    counts = defaultdict(int)
    for row in mapping_rows:
        counts[row['confidence']] += 1

    print(f'Publicaciones ML: {len(mapping_rows)}')
    print(f'  high={counts["high"]} medium={counts["medium"]} low={counts["low"]}')
    print(f'Opiniones a importar ({args.min_confidence}+): {len(preview_rows)} / {len(opinions)}')
    print(f'Reporte matching: {mapping_path}')
    print(f'Preview reseñas: {preview_path}')

    if not args.apply:
        print('\nDry-run OK. Volvé a correr con --apply para insertar en Supabase.')
        return 0

    existing = fetch_existing_ml_emails()
    to_insert = [r for r in preview_rows if r['customer_email'] not in existing]
    skipped = len(preview_rows) - len(to_insert)
    print(f'Ya existían: {skipped}. Nuevas: {len(to_insert)}.')

    batch_size = 50
    inserted = 0
    for i in range(0, len(to_insert), batch_size):
        batch = []
        for row in to_insert[i:i + batch_size]:
            payload = {
                'product_id': row['product_id'],
                'product_name': row['product_name'],
                'product_url': row['product_url'],
                'customer_name': row['customer_name'],
                'customer_email': row['customer_email'],
                'rating': row['rating'],
                'title': row['title'],
                'comment': row['comment'],
                'image_urls': row['image_urls'],
                'status': row['status'],
                'verified_purchase': row['verified_purchase'],
            }
            if row['created_at'] and row['created_at'] not in {'nan', 'NaT', 'None'}:
                payload['created_at'] = row['created_at']
            batch.append(payload)
        supabase_request('POST', 'reviews', body=batch)
        inserted += len(batch)
        print(f'  insertadas {inserted}/{len(to_insert)}')

    print(f'\nListo: {inserted} reseñas importadas con status={args.status}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
