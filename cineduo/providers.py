"""External OMDb/TMDb lookups and poster caching."""

from __future__ import annotations

from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen
import json
import os
import re
import ssl

from .config import OMDB_URL, POSTERS
from .database import MAPPING, get_setting
from .utils import cast_names, clean_value, normalize_content_type, safe_title

def external_json(url,timeout=6):
    """Consulta apenas os endpoints pré-definidos. Não recebe URLs arbitrárias do cliente."""
    req=Request(url,headers={
        'User-Agent':'CineDuo/1.8 (personal film catalog; metadata lookup)',
        'Accept':'application/json'})
    with urlopen(req,timeout=timeout) as response:
        raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024: raise ValueError('Resposta externa muito grande.')
    return json.loads(raw.decode('utf-8'))

VOICE_ROLE_RE=re.compile(r'\b(?:voice|voiceover|voice-over|dubbing|dubbed|narration|narrator|archive\s+footage|stock\s+footage)\b',re.I)
NON_ACTING_ROLE_RE=re.compile(r'^(?:self|himself|herself|themselves|musician|singer|band|soundtrack|performer|host|presenter)(?:\b|\s*\()',re.I)

def is_on_screen_cast(person,kind='movie'):
    """Considera crédito de elenco (não equipe); dispensa apenas voz/arquivo e
    participações como si mesmo que não são atuação dramática.
    """
    if not isinstance(person,dict) or not str(person.get('name') or '').strip():return False
    if person.get('job') and not person.get('character') and not person.get('roles'):return False
    roles=person.get('roles') if kind=='series' else None
    characters=[str(p.get('character') or '') for p in roles if isinstance(p,dict)] if isinstance(roles,list) else []
    if not characters:characters=[str(person.get('character') or '')]
    for value in characters:
        if VOICE_ROLE_RE.search(value) or NON_ACTING_ROLE_RE.search(value.strip()):continue
        return True
    return False

def tmdb_cast(imdb_id,kind):
    """Apenas pessoas na seção cast da TMDb, sem vozes nem equipe técnica.

    Para séries, aggregate_credits fornece roles; só basta um papel presencial.
    """
    key=get_setting('tmdb_key')
    if not key:return [],{}
    query=urlencode({'api_key':key,'external_source':'imdb_id'})
    found=external_json(f'https://api.themoviedb.org/3/find/{imdb_id}?{query}',timeout=9)
    choices=found.get('tv_results' if kind=='series' else 'movie_results') or []
    if not choices:return [],{}
    internal_id=choices[0].get('id')
    if not isinstance(internal_id,int):return [],{}
    endpoint=f'tv/{internal_id}/aggregate_credits' if kind=='series' else f'movie/{internal_id}/credits'
    credits=external_json(f'https://api.themoviedb.org/3/{endpoint}?'+urlencode({'api_key':key}),timeout=9)
    cast=credits.get('cast') or []
    on_screen=[person for person in cast if is_on_screen_cast(person,kind)]
    names=cast_names(on_screen)[:300]
    images={}
    for person in on_screen:
        name=str(person.get('name') or '').strip()
        path=str(person.get('profile_path') or '')
        if name and re.fullmatch(r'/[A-Za-z0-9_./-]{6,160}\.(?:jpg|jpeg|png)',path,re.I):
            images[safe_title(name)]='https://image.tmdb.org/t/p/w185'+path
    return names,images

def friendly_omdb_error(message):
    """Transforma erros da OMDb em ações claras, sem mostrar a chave."""
    message = (str(message or 'erro desconhecido')).strip()[:220]
    lower = message.lower()
    if 'invalid api key' in lower or 'no api key' in lower or 'activate your api key' in lower:
        return ('A chave OMDb foi recusada ou ainda não está ativada. '
                'Abra o e-mail da OMDb, clique no link de ativação e confirme que copiou a chave completa. '
                f'Detalhe: {message}')
    if 'limit' in lower or 'quota' in lower or 'too many' in lower:
        return 'Limite de consultas da OMDb atingido. Tente novamente amanhã. Detalhe: ' + message
    if 'movie not found' in lower or 'not found!' in lower or 'series not found' in lower:
        return 'Filme não encontrado na OMDb. Confira título original e ano. Detalhe: ' + message
    return 'OMDb: ' + message

def get_remote(params):
    key=get_setting('omdb_key') or os.environ.get('OMDB_API_KEY','')
    if not key: raise ValueError('Configure sua chave gratuita da OMDb em Ajustes.')
    from urllib.parse import urlencode
    qs=urlencode(dict(params,apikey=key))
    req=Request(OMDB_URL+'?'+qs,headers={'User-Agent':'CineDuo/1.4 (personal movie catalog)'})
    try:
        with urlopen(req,timeout=14) as res:
            raw=res.read(1024*1024)
    except HTTPError as e:
        try:
            payload=json.loads(e.read(8192).decode('utf-8'))
            detail=payload.get('Error') or payload.get('Message')
        except (ValueError,UnicodeDecodeError,OSError):
            detail=None
        if detail: raise ValueError(friendly_omdb_error(detail)) from e
        if e.code in (401,403):
            raise ValueError(f'A OMDb recusou a consulta (HTTP {e.code}). Verifique se a chave foi ativada por e-mail.') from e
        if e.code==429: raise ValueError('Limite temporário de consultas da OMDb (HTTP 429). Tente mais tarde.') from e
        raise ValueError(f'A OMDb respondeu com erro HTTP {e.code}. Tente mais tarde.') from e
    except URLError as e:
        reason=e.reason
        if isinstance(reason, ssl.SSLCertVerificationError) or 'certificate verify failed' in str(reason).lower():
            raise ValueError('Falha no certificado de segurança HTTPS do Python. Atualize o Python ou os certificados do Windows.') from e
        raise ValueError('Não foi possível conectar à OMDb. Verifique internet, antivírus ou firewall. '
                         f'Detalhe: {type(reason).__name__}: {str(reason)[:100]}') from e
    except (TimeoutError, OSError) as e:
        raise ValueError('Não foi possível conectar à OMDb (tempo esgotado ou rede indisponível).') from e
    try:
        result=json.loads(raw.decode('utf-8'))
    except (ValueError,UnicodeDecodeError) as e:
        raise ValueError('A OMDb respondeu em formato inesperado. Tente novamente mais tarde.') from e
    if result.get('Response') == 'False':
        raise ValueError(friendly_omdb_error(result.get('Error','filme não encontrado')))
    return result

def metadata_from_omdb(doc):
    data={dest:clean_value(doc.get(src)) for src,dest in MAPPING.items()}
    data['content_type']=normalize_content_type(doc.get('Type') or 'movie')
    scores=doc.get('Ratings') or []
    # O IMDb também pode chegar pela lista Ratings mesmo se imdbRating vier N/A.
    if not data.get('imdb_rating'):
        for score in scores:
            if score.get('Source')=='Internet Movie Database':
                v=str(score.get('Value','')).split('/')[0].strip()
                data['imdb_rating']=clean_value(v)
                break
    for s in scores:
        if s.get('Source')=='Rotten Tomatoes': data['rotten_tomatoes']=clean_value(s.get('Value'))
    return data

def cache_poster(movie_id, url):
    if not url or url=='N/A': return None
    parsed=urlparse(url)
    host=(parsed.hostname or '').lower()
    # Somente hosts conhecidos de cartazes de cinema; impede pedidos a URLs locais.
    allowed={'m.media-amazon.com','images-na.ssl-images-amazon.com','img.omdbapi.com',
             'image.tmdb.org','img.amodb.dev','ia.media-imdb.com'}
    if parsed.scheme!='https' or host not in allowed: return None
    try:
        req=Request(url,headers={'User-Agent':'Mozilla/5.0 (CineDuo personal)'})
        with urlopen(req,timeout=9) as resp:
            kind=resp.headers.get('Content-Type','').split(';')[0].lower()
            if kind not in ('image/jpeg','image/png','image/webp'): return None
            image=resp.read(4*1024*1024+1)
            if not image or len(image)>4*1024*1024: return None
        ext={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[kind]
        name=f'{movie_id}.{ext}'
        (POSTERS/name).write_bytes(image)
        for stale in POSTERS.glob(f'{movie_id}.*'):
            if stale.name!=name: stale.unlink(missing_ok=True)
        return name
    except (HTTPError,URLError,TimeoutError, OSError):
        return None