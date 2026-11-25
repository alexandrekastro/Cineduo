"""Cast verification, actor photos, and appearance rankings."""

from __future__ import annotations
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.parse import urlparse

import json
import re
import time

from .config import CURATED_ACTOR_PHOTOS
from .database import connection, get_setting
from .library import all_movies, edit_movie, get_movie
from .providers import external_json, tmdb_cast
from .utils import cast_names, commons_file_url, commons_source_url, normalize_photo_url, now, safe_title

def enrich_movie_cast(movie_id):
    """Confirma atores em vez de juntar elencos parciais e créditos duvidosos.

    A lista antiga permanece em movies.actors; verified_movie_cast é a fonte
    exclusiva da contagem após conferência, somada a inclusões manuais.
    """
    item=get_movie(movie_id)
    imdb_id=str(item.get('imdb_id') or '')
    if not re.fullmatch(r'tt\d{7,10}',imdb_id):
        return {'id':movie_id,'added':0,'sources':[],
                'note':'Título sem ID IMDb. Não foi possível validar o elenco.'}
    if not get_setting('tmdb_key'):
        return {'id':movie_id,'added':0,'sources':[],
                'note':'Configure a chave TMDb em Ajustes para validar somente atores e atrizes.'}
    try:actors,images=tmdb_cast(imdb_id,item.get('content_type') or 'movie')
    except (ValueError,TypeError,HTTPError,URLError,TimeoutError,OSError,KeyError) as e:
        return {'id':movie_id,'added':0,'sources':[], 'note':'TMDb indisponível: '+type(e).__name__}
    if not actors:
        return {'id':movie_id,'added':0,'sources':[],
                'note':'A TMDb não retornou créditos de atuação válidos para este título.'}
    with connection() as db:
        prior=db.execute('SELECT actors_json FROM verified_movie_cast WHERE movie_id=?',(movie_id,)).fetchone()
        old=cast_names(json.loads(prior['actors_json'])) if prior else []
        db.execute('INSERT INTO verified_movie_cast(movie_id,imdb_id,actors_json,checked_at,source) '
                   'VALUES(?,?,?,?,?) ON CONFLICT(movie_id) DO UPDATE SET '
                   'imdb_id=excluded.imdb_id,actors_json=excluded.actors_json,'
                   'checked_at=excluded.checked_at,source=excluded.source',
                   (movie_id,imdb_id,json.dumps(actors,ensure_ascii=False),now(),'TMDb'))
        for key,url in images.items():
            db.execute('INSERT INTO actor_photos(artist_key,url,checked_at,source) VALUES(?,?,?,?) '
                       'ON CONFLICT(artist_key) DO UPDATE SET url=excluded.url,checked_at=excluded.checked_at,source=excluded.source '
                       "WHERE actor_photos.source NOT IN ('manual','curated')",
                       (key,url,str(time.time()),'tmdb'))
    return {'id':movie_id,'title':item['title'],'added':len(set(safe_title(n) for n in actors)-set(safe_title(n) for n in old)),
            'count':len(actors),'sources':['TMDb'],'verified':True,
            'note':'Créditos de atuação confirmados; vozes e equipe excluídos.'}

def set_actor_photo(name, photo_url):
    name = str(name or '').strip()
    if not name or len(name) > 100 or any(ch in name for ch in '<>{}\\'):
        raise ValueError('Nome do artista inválido.')
    url = normalize_photo_url(photo_url)
    key = safe_title(name)
    with connection() as db:
        db.execute('INSERT INTO actor_photos(artist_key,url,checked_at,source) VALUES(?,?,?,?) '
                   'ON CONFLICT(artist_key) DO UPDATE SET url=excluded.url,checked_at=excluded.checked_at,source=excluded.source',
                   (key,url,str(time.time()),'manual' if url else 'retry'))
    return {'name':name,'url':url or None,'source':'manual' if url else 'retry'}

def actor_photo(name):
    name=str(name or '').strip()
    if not name or len(name)>100 or any(c in name for c in '<>{}\\'):
        raise ValueError('Nome de artista inválido.')
    key=safe_title(name)
    with connection() as db:
        row=db.execute('SELECT url,checked_at,source FROM actor_photos WHERE artist_key=?',(key,)).fetchone()
    if row:
        try:
            if row['source'] in ('manual','curated') or time.time()-float(row['checked_at']) < (30*86400 if row['url'] else 6*3600):
                filename=CURATED_ACTOR_PHOTOS.get(key) if row['source']=='curated' else None
                return {'name':name,'url':row['url'] or None,'source':row['source'],
                        'attribution':commons_source_url(filename) if filename else None}
        except (ValueError,TypeError): pass
    filename=CURATED_ACTOR_PHOTOS.get(key)
    if filename:
        photo=commons_file_url(filename)
        with connection() as db:
            db.execute("INSERT INTO actor_photos(artist_key,url,checked_at,source) VALUES(?,?,?,?) ON CONFLICT(artist_key) DO UPDATE SET url=excluded.url,checked_at=excluded.checked_at,source=excluded.source WHERE actor_photos.source != 'manual'",
                       (key,photo,str(time.time()),'curated'))
        return {'name':name,'url':photo,'source':'curated','attribution':commons_source_url(filename)}
    photo=''
    for title in (name,name+' (actor)',name+' (actress)'):
        url='https://en.wikipedia.org/w/api.php?'+urlencode({
            'action':'query','format':'json','formatversion':'2',
            'titles':title,'prop':'pageimages','pithumbsize':'260','pilicense':'any'})
        try:
            doc=external_json(url,timeout=6)
            pages=doc.get('query',{}).get('pages',[])
            for page in pages:
                thumb=(page.get('thumbnail') or {}).get('source','')
                if thumb.startswith('https://upload.wikimedia.org/') and not page.get('missing'):
                    photo=thumb
                    break
            if photo: break
        except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError): pass
    if not photo:
        try:
            lookup=external_json('https://www.wikidata.org/w/api.php?'+urlencode({
              'action':'wbsearchentities','search':name,'language':'en','format':'json','limit':'5'}),timeout=7)
            for candidate in lookup.get('search',[]):
                label=safe_title(candidate.get('label',''))
                description=safe_title(candidate.get('description',''))
                if label!=key or not any(x in description for x in ('actor','actress','performer','artista','atriz','ator')): continue
                qid=candidate.get('id','')
                if not re.fullmatch(r'Q\d+',qid):continue
                entity=external_json('https://www.wikidata.org/w/api.php?'+urlencode({
                   'action':'wbgetentities','ids':qid,'props':'claims','format':'json'}),timeout=7)
                claims=entity.get('entities',{}).get(qid,{}).get('claims',{}).get('P18',[])
                if claims:
                    filename=claims[0].get('mainsnak',{}).get('datavalue',{}).get('value','')
                    if isinstance(filename,str) and len(filename)<250 and not any(ch in filename for ch in '<>'):
                        photo='https://commons.wikimedia.org/wiki/Special:FilePath/'+quote(filename.replace(' ','_'))+'?width=300'
                if photo:break
        except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,KeyError): pass
    with connection() as db:
        db.execute('INSERT INTO actor_photos (artist_key,url,checked_at) VALUES (?,?,?) '
                   'ON CONFLICT(artist_key) DO UPDATE SET url=excluded.url,checked_at=excluded.checked_at',
                   (key,photo,str(time.time())))
    return {'name':name,'url':photo or None,'source':'auto'}

def actor_manual_add(movie_id,name,photo=''):
    name=str(name or '').strip();photo=str(photo or '').strip()
    if not (2<=len(name)<=100) or any(c in name for c in '<>{}\\'):
        raise ValueError('Digite o nome correto do artista.')
    if photo:
        u=urlparse(photo)
        if u.scheme!='https' or u.hostname not in ('image.tmdb.org','upload.wikimedia.org','commons.wikimedia.org','m.media-amazon.com'):
            raise ValueError('Use o link HTTPS de uma foto da TMDb, Wikimedia Commons ou IMDb.')
        if len(photo)>800:raise ValueError('Link de foto muito longo.')
    movie=get_movie(movie_id)
    actors=cast_names(movie.get('actors'))
    with connection() as db:
        db.execute('INSERT INTO manual_movie_cast(movie_id,artist_key,artist_name) VALUES(?,?,?) '
                   'ON CONFLICT(movie_id,artist_key) DO UPDATE SET artist_name=excluded.artist_name',
                   (movie_id,safe_title(name),name))
    if safe_title(name) not in {safe_title(a) for a in actors}:
        actors.append(name)
        edit_movie(movie_id,{'actors':', '.join(actors)})
    if photo:
        with connection() as db:
            db.execute('INSERT INTO actor_photos(artist_key,url,checked_at) VALUES(?,?,?) '
                       'ON CONFLICT(artist_key) DO UPDATE SET url=excluded.url,checked_at=excluded.checked_at',
                       (safe_title(name),photo,str(time.time())))
    return {'ok':True,'artist':name,'title':movie['title']}

def actor_rankings(include_series=False):
    """Apenas elenco de atuação validado + inclusões manuais explícitas."""
    artists={}
    for m in all_movies():
        if m.get('content_type')=='series' and not include_series:continue
        names=m.get('verified_actors') if m.get('cast_status')=='verified' else ([] if get_setting('tmdb_key') else cast_names(m.get('actors')))
        seen=set()
        for name in cast_names(list(names)+m.get('manual_actors',[])):
            key=safe_title(name)
            if key in seen:continue
            seen.add(key)
            if key not in artists:artists[key]={'name':name,'titles':[]}
            artists[key]['titles'].append({'id':m['id'],'title':m['title'],
                'year':m['year'],'poster_url':m['poster_url'], 'content_type':m.get('content_type','movie')})
    listing=[dict(data,appearances=len(data['titles'])) for data in artists.values()]
    listing.sort(key=lambda x:(-x['appearances'],safe_title(x['name'])))
    for i,data in enumerate(listing,1):data['rank']=i
    return listing