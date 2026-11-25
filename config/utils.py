"""Pure value parsing and normalization helpers."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import urlparse
import re
import unicodedata

from .config import KNOWN_IMDB_IDS

def safe_title(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower())
                   if not unicodedata.combining(c)).strip()

def imdb_id_from_input(value):
    """Permite tt... ou URL do IMDb, mas não outros endereços."""
    value=str(value or '').strip()
    if not value: return ''
    match=re.fullmatch(r'tt\d{7,10}',value,re.IGNORECASE)
    if match: return value.lower()
    url=re.fullmatch(r'https?://(?:www\.)?imdb\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?title/(tt\d{7,10})(?:[/?#].*)?',value,re.IGNORECASE)
    if url: return url.group(1).lower()
    raise ValueError('Informe o ID IMDb (tt...) ou o link da ficha no IMDb.')

def movie_expected_id(item):
    title=safe_title(item.get('title'))
    year=str(item.get('year') or '')[:4]
    if title == 'ainda estou aqui' and year in ('2024','2025',''):
        return 'tt14961016'
    return KNOWN_IMDB_IDS.get((title,year)) or item.get('imdb_id') or ''

def cast_names(text):
    if isinstance(text,list):
        values=[item.get('name') if isinstance(item,dict) else item for item in text]
    else:
        values=str(text or '').split(',')
    names=[]
    seen=set()
    aliases={'zendaya coleman':'Zendaya','zendaya maree stoermer coleman':'Zendaya'}
    for raw in values:
        name=str(raw or '').strip()
        name=aliases.get(safe_title(name),name)
        canonical=safe_title(name)
        if not name or canonical in ('n/a','unknown','na') or re.fullmatch(r'q[0-9]+',canonical) or canonical in seen or len(name)>120:
            continue
        names.append(name)
        seen.add(canonical)
    return names

def commons_file_url(filename):
    return 'https://commons.wikimedia.org/wiki/Special:FilePath/' + quote(filename.replace(' ', '_'), safe='()') + '?width=320'

def commons_source_url(filename):
    return 'https://commons.wikimedia.org/wiki/File:' + quote(filename.replace(' ', '_'), safe='()')

def normalize_photo_url(value):
    value = str(value or '').strip()
    if not value: return ''
    if len(value) > 1500 or any(ch in value for ch in ('<','>','\\','\n','\r','\t')):
        raise ValueError('O link da foto é inválido ou muito longo.')
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Use um link HTTPS para a imagem.')
    if parsed.netloc.lower() == 'commons.wikimedia.org' and parsed.path.startswith('/wiki/File:'):
        filename = parsed.path[len('/wiki/File:'):]
        from urllib.parse import unquote
        return commons_file_url(unquote(filename))
    return value

def normalize_content_type(value):
    value = str(value or 'movie').strip().lower()
    if value not in ('movie', 'series'):
        raise ValueError('Escolha Filme ou Série como tipo de título.')
    return value

def normalize_trailer_url(url):
    """Aceita exclusivamente links públicos do YouTube, nunca HTML ou scripts."""
    value = str(url or '').strip()
    if not value: return None
    parsed = urlparse(value)
    host = (parsed.hostname or '').lower()
    video_id = ''
    if parsed.scheme != 'https':
        raise ValueError('O trailer precisa ser um link HTTPS do YouTube.')
    if host in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'):
        if parsed.path == '/watch':
            video_id = parse_qs(parsed.query).get('v',[''])[0]
        elif re.fullmatch(r'/(?:embed|shorts|live)/[A-Za-z0-9_-]{11}',parsed.path):
            video_id = parsed.path.rsplit('/',1)[-1]
    elif host in ('youtu.be','www.youtu.be'):
        video_id = parsed.path.lstrip('/')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id):
        raise ValueError('Informe um link válido de vídeo do YouTube (youtube.com/watch?v=... ou youtu.be/...).')
    return 'https://www.youtube.com/watch?v=' + video_id

def now():
    return datetime.now().isoformat(timespec='seconds')

def clean_value(v):
    return None if v is None or str(v).strip() in ('N/A','') else str(v).strip()

def parse_rating(v):
    if v is None or str(v).strip().lower() in ('','null','sem nota','none','-'):
        return None
    try:
        n=float(str(v).replace(',','.'))
    except (TypeError, ValueError):
        raise ValueError('A nota deve ser de 0 a 10 ou ficar sem nota.')
    if not n.is_integer() or not (0 <= n <= 10):
        raise ValueError('Escolha uma nota inteira de 0 a 10.')
    return int(n)

def norm_col(k):
    import unicodedata
    k=unicodedata.normalize('NFKD',str(k or '')).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+',' ',k).strip()