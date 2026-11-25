"""Franchise discovery, catalog grouping, and average scores."""

from __future__ import annotations

from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
import re

from .database import connection, get_setting
from .library import all_movies
from .providers import external_json
from .saga_data import SAGA_CATALOG, SAGA_STORY_ORDER, SAGA_STORY_YEARS
from .utils import imdb_id_from_input, now, safe_title

def saga_part_key(part):
    """Identificador estável para guardar a ordem manual de cada pasta."""
    if part.get('imdb_id'):return 'imdb:'+str(part['imdb_id']).lower()
    if part.get('tmdb_id'):return 'tmdb:'+str(part['tmdb_id'])
    return 'title:'+re.sub(r'[^a-z0-9]+','-',safe_title(part.get('title') or '')).strip('-')+':'+str(part.get('year') or '')

def reorder_saga(key,index,action):
    """Permite ordenar coleções TMDb pela história, inclusive após ressincronizar."""
    if action not in ('up','down'):raise ValueError('Movimento inválido.')
    folder=next((x for x in saga_list() if x['key']==key),None)
    if not folder:raise ValueError('Saga não encontrada.')
    parts=folder['parts'];index=int(index)
    other=index+(-1 if action=='up' else 1)
    if index<0 or index>=len(parts) or other<0 or other>=len(parts):return {'ok':True}
    parts[index],parts[other]=parts[other],parts[index]
    with connection() as db:
        db.execute('DELETE FROM saga_part_order WHERE saga_key=?',(key,))
        db.executemany('INSERT INTO saga_part_order(saga_key,part_key,sort_index) VALUES(?,?,?)',
                       [(key,saga_part_key(part),i) for i,part in enumerate(parts)])
    return {'ok':True}

def saga_norm(s):
    return re.sub(r'[^a-z0-9]+',' ',safe_title(s)).strip()

def saga_movie_match(part,m):
    imdb=part.get('imdb_id')
    if imdb and imdb==str(m.get('imdb_id') or '').lower(): return True
    # Comparamos ano e títulos normalizados para não confundir remakes homônimos.
    year=str(part.get('year') or '')[:4];myear=str(m.get('year') or '')[:4]
    if year and myear and year!=myear: return False
    names={saga_norm(a) for a in [m.get('title'),m.get('original_title')] if a}
    aliases={saga_norm(a) for a in [part.get('title')]+part.get('aliases',[]) if a}
    return bool(names & aliases)

def saga_detected():
    """Pastas locais confiáveis, ativadas somente se há filme cadastrado."""
    items=all_movies()
    result=[]
    for slug,data in SAGA_CATALOG.items():
        order={imdb:i for i,imdb in enumerate(SAGA_STORY_ORDER.get(slug,[]))}
        source_parts=sorted(data['parts'],key=lambda p:(order.get(p[2],1000),data['parts'].index(p))) if order else data['parts']
        parts=[{'title':p[0],'year':str(p[1]),'imdb_id':p[2],
                'aliases':p[3],'tmdb_id':None,'poster':None,'timeline_year':SAGA_STORY_YEARS.get(p[2])} for p in source_parts]
        if any(m.get('content_type')!='series' and saga_movie_match(part,m) for part in parts for m in items):
            result.append({'key':'known:'+slug,'name':data['name'],'source':'curated',
                           'order_basis':'story' if order else 'series','parts':parts})
    return result

def safe_numeric_rating(raw, low, high):
    """Converte valores OMDb ou notas já registradas, ignorando N/A e inválidos.

    Nunca converte 0 para ausência: Metascore 0 e nota pessoal 0 são válidos.
    """
    if raw is None or isinstance(raw, bool):return None
    value=str(raw).strip().replace(',', '.')
    if not value or value.lower() in ('n/a','none','null','—','-'):return None
    try: number=float(value)
    except (ValueError,OverflowError):return None
    import math
    if not math.isfinite(number) or not low<=number<=high:return None
    return number

def numeric_average(values):
    return round(sum(values)/len(values)+1e-9, 1) if values else None

def saga_list():
    """Calcula médias ao vivo pelos títulos CADASTRADOS, nunca por nota manual.

    IMDb e Metascore não são inventados para filmes que ainda não constam do
    catálogo pessoal. Uma saga está completa quando todos os filmes listados
    nela foram adicionados ao ranking, mesmo que falte nota externa.
    """
    movies=[m for m in all_movies() if m.get('content_type')!='series']
    with connection() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM saga_folders')]
        parts={r['saga_key']:[] for r in rows}
        for r in db.execute('SELECT * FROM saga_parts ORDER BY part_order,id'):
            if r['saga_key'] in parts: parts[r['saga_key']].append(dict(r))
        mappings={r['movie_id']:r['tmdb_id'] for r in db.execute('SELECT * FROM movie_tmdb')}
        manual_order={}
        for item in db.execute('SELECT saga_key,part_key,sort_index FROM saga_part_order'):
            manual_order.setdefault(item['saga_key'],{})[item['part_key']]=item['sort_index']
    result=[];matching_known=set()
    for folder in saga_detected():
        if any(row['saga_key']==folder['key'] and row['hidden'] for row in rows):continue
        for part in folder['parts']:
            part['movie']=next((m for m in movies if saga_movie_match(part,m)),None)
            if part['movie']:matching_known.add(part['movie']['id'])
        result.append(folder)
    for row in rows:
        if row['saga_key'].startswith('known:') or row['hidden']:continue
        folder={'key':row['saga_key'],'name':row['name'],'source':row['source'],
                'order_basis':'release' if row['source']=='tmdb' else 'manual','parts':[]}
        for part in parts.get(row['saga_key'],[]):
            linked=next((m for m in movies if (part['tmdb_id'] and mappings.get(m['id'])==part['tmdb_id']) or
                          saga_movie_match({'title':part['title'],'year':part['year'],
                                            'imdb_id':part['imdb_id'],'aliases':[]},m)),None)
            folder['parts'].append({'title':part['title'],'year':part['year'],'imdb_id':part['imdb_id'],
                                    'tmdb_id':part['tmdb_id'],'poster':part['poster'],'id':part['id'],
                                    'movie':linked})
        if row['source']=='tmdb' and folder['parts'] and all(
            (part.get('movie') and part['movie']['id'] in matching_known)
            for part in folder['parts'] if part.get('movie')) and any(
                part.get('movie') for part in folder['parts']):
            continue
        if row['source']=='manual' or any(part.get('movie') for part in folder['parts']):result.append(folder)
    for folder in result:
        overrides=manual_order.get(folder['key']) or {}
        if overrides:
            folder['parts'].sort(key=lambda part:(overrides.get(saga_part_key(part),10_000),))
            folder['order_basis']='custom'
        viewed=[part for part in folder['parts'] if part.get('movie')]
        folder['registered']=len(viewed);folder['total']=len(folder['parts'])
        folder['missing']=folder['total']-folder['registered']
        folder['complete']=bool(folder['total']>=2 and folder['missing']==0)
        # Os três conjuntos usam SOMENTE os filmes registrados. As médias
        # independem de votos de saga de versões antigas.
        fields=(('movie_average','personal_rating',0,10),
                ('imdb_average','imdb_rating',0,10),
                ('metascore_average','metascore',0,100))
        for output, field, low, high in fields:
            values=[v for part in viewed if (v:=safe_numeric_rating(
                part['movie'].get(field),low,high)) is not None]
            folder[output]=numeric_average(values)
            folder[output+'_count']=len(values)
        # Alias para clientes que esperam um campo rating. Não salva nada.
        folder['rating']=folder['movie_average']
        folder['parts']=[{k:v for k,v in part.items() if k!='aliases'}
                         for part in folder['parts']]
    result.sort(key=lambda d:(d['movie_average'] is None,
                   -(d['movie_average'] if d['movie_average'] is not None else 0),
                   not d['complete'],-d['registered'],saga_norm(d['name'])))
    return result

def saga_create(name):
    name=str(name or '').strip()
    if len(name)<2 or len(name)>100:raise ValueError('Informe o nome da saga (2–100 caracteres).')
    import secrets
    key='manual:'+secrets.token_hex(7)
    with connection() as db:
        db.execute('INSERT INTO saga_folders(saga_key,name,source,created_at) VALUES(?,?,?,?)',(key,name,'manual',now()))
    return {'key':key,'name':name}

def saga_add_part(key,title,year=None,imdb_id=None):
    if not re.fullmatch(r'manual:[a-z0-9]{14}',key):raise ValueError('Adições manuais são permitidas em sagas criadas por você.')
    title=str(title or '').strip()
    if not 2<=len(title)<=220:raise ValueError('Título inválido.')
    year=str(year or '').strip()[:4]
    if year and not re.fullmatch(r'(?:19|20)\d{2}',year):raise ValueError('Informe ano válido.')
    imdb_id=imdb_id_from_input(imdb_id) if imdb_id else None
    with connection() as db:
        if not db.execute('SELECT 1 FROM saga_folders WHERE saga_key=?',(key,)).fetchone():raise ValueError('Saga não encontrada.')
        order=db.execute('SELECT COALESCE(MAX(part_order),0)+1 FROM saga_parts WHERE saga_key=?',(key,)).fetchone()[0]
        db.execute('INSERT INTO saga_parts (saga_key,title,year,imdb_id,part_order) VALUES(?,?,?,?,?)',
                   (key,title,year or None,imdb_id,order))
    return {'ok':True}

def saga_scan_tmdb(limit=6,offset=0):
    """TMDb: IMDb ID → filme → belongs_to_collection → todas as partes.

    O usuário deve configurar sua chave API v3; sem ela o catálogo local
    continua acessível e editável. Não altera nenhuma nota do ranking.
    """
    key=get_setting('tmdb_key')
    if not key:raise ValueError('Para descobrir automaticamente sagas além do catálogo inicial, configure a chave gratuita da TMDb em Ajustes.')
    all_eligible=[m for m in all_movies() if m.get('content_type')!='series' and re.fullmatch(r'tt\d{7,10}',str(m.get('imdb_id') or ''))]
    total=len(all_eligible)
    offset=max(0,min(int(offset),total))
    limit=max(1,min(int(limit),8))
    movies=all_eligible[offset:offset+limit]
    found={};processed=0;errors=[]
    for m in movies:
        try:
            doc=external_json('https://api.themoviedb.org/3/find/'+m['imdb_id']+'?'+urlencode({'api_key':key,'external_source':'imdb_id'}),timeout=8)
            match=next((x for x in doc.get('movie_results',[]) if isinstance(x.get('id'),int)),None)
            if not match:continue
            internal=match['id']
            with connection() as db:db.execute('INSERT INTO movie_tmdb(movie_id,tmdb_id) VALUES(?,?) ON CONFLICT(movie_id) DO UPDATE SET tmdb_id=excluded.tmdb_id',(m['id'],internal))
            detail=external_json('https://api.themoviedb.org/3/movie/'+str(internal)+'?'+urlencode({'api_key':key,'language':'pt-BR'}),timeout=8)
            coll=detail.get('belongs_to_collection') or {}
            if isinstance(coll.get('id'),int):found[coll['id']]=coll.get('name','Coleção')
            processed+=1
        except (ValueError,TypeError,HTTPError,URLError,OSError,TimeoutError) as e:
            errors.append(m['title']+': '+type(e).__name__)
    new=0
    for cid,name in found.items():
        try:
            doc=external_json('https://api.themoviedb.org/3/collection/'+str(cid)+'?'+urlencode({'api_key':key,'language':'pt-BR'}),timeout=8)
            entries=doc.get('parts') or []
            if len(entries)<2:continue
            slug='tmdb:'+str(cid)
            with connection() as db:
                previous=db.execute('SELECT 1 FROM saga_folders WHERE saga_key=?',(slug,)).fetchone()
                if not previous:
                    db.execute('INSERT INTO saga_folders(saga_key,name,source,tmdb_collection_id,created_at) VALUES(?,?,?,?,?)',
                               (slug,str(doc.get('name') or name)[:100],'tmdb',cid,now()))
                    new+=1
                else:db.execute('UPDATE saga_folders SET name=? WHERE saga_key=?',(str(doc.get('name') or name)[:100],slug))
                # Recolhe as partes; não remove as edições e avaliações próprias.
                for i,p in enumerate(sorted(entries,key=lambda x:(x.get('release_date') or '9999',x.get('id') or 0))):
                    tmdb_id=p.get('id');title=p.get('title') or p.get('name')
                    if not isinstance(tmdb_id,int) or not title:continue
                    year=(p.get('release_date') or '')[:4]
                    cover=p.get('poster_path') or ''
                    poster=('https://image.tmdb.org/t/p/w342'+cover if re.fullmatch(r'/[A-Za-z0-9_./-]+\.(?:jpg|png)',cover,re.I) else None)
                    existing=db.execute('SELECT id FROM saga_parts WHERE saga_key=? AND tmdb_id=?',(slug,tmdb_id)).fetchone()
                    if existing:
                        db.execute('UPDATE saga_parts SET title=?,year=?,poster=?,part_order=? WHERE id=?',(str(title)[:220],year,poster,i,existing[0]))
                    else:
                        db.execute('INSERT INTO saga_parts(saga_key,title,year,tmdb_id,poster,part_order) VALUES(?,?,?,?,?,?)',
                                   (slug,str(title)[:220],year,tmdb_id,poster,i))
        except (ValueError,TypeError,HTTPError,URLError,OSError,TimeoutError) as e:
            errors.append(name+': '+type(e).__name__)
    return {'scanned':processed,'total':total,'attempted':len(movies),'collections':len(found),'new':new,'errors':errors[:10],
            'message':'Sagas pesquisadas na TMDb; títulos já vistos permanecem intactos.'}