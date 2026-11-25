"""Movie and series catalog, Top 3, and import/export operations."""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import time

from .config import OMDB_FIELDS, POSTERS
from .database import COLUMNS, connection
from .providers import cache_poster, get_remote, metadata_from_omdb
from .utils import cast_names, clean_value, imdb_id_from_input, movie_expected_id, norm_col, normalize_content_type, normalize_trailer_url, now, parse_rating, safe_title

def public_row(row):
    d=dict(row)
    d['poster_url']='/posters/'+d['poster_local'] if d.get('poster_local') else (d.get('poster') or '')
    return d

def all_movies():
    with connection() as db:
        rows=[public_row(r) for r in db.execute('SELECT * FROM movies ORDER BY personal_rating DESC, sort_order ASC, id ASC')]
        by_id={m['id']:m for m in rows}
        for record in db.execute('SELECT * FROM verified_movie_cast'):
            m=by_id.get(record['movie_id'])
            if m and m.get('imdb_id')==record['imdb_id']:
                try:
                    names=cast_names(json.loads(record['actors_json']))
                except (TypeError,ValueError,json.JSONDecodeError):continue
                m['verified_actors']=names
                m['cast_status']='verified'
        for record in db.execute('SELECT movie_id,artist_name FROM manual_movie_cast'):
            m=by_id.get(record['movie_id'])
            if m:m.setdefault('manual_actors',[]).append(record['artist_name'])
        for m in rows:m.setdefault('cast_status','unverified')
        return rows

def get_movie(movie_id):
    with connection() as db:
        row=db.execute('SELECT * FROM movies WHERE id=?',(movie_id,)).fetchone()
    if not row: raise ValueError('Filme não encontrado.')
    return public_row(row)

def next_order(db, rating):
    r=db.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM movies WHERE personal_rating IS ?', (rating,)).fetchone()
    return r[0]

def add_movie(data, fill_from_api=False):
    fields={k: data[k] for k in data if k in COLUMNS}
    if fill_from_api and data.get('imdb_id'):
        metadata=metadata_from_omdb(get_remote({'i':imdb_id_from_input(data['imdb_id']),'plot':'full'}))
        fields={**metadata,**{k:v for k,v in fields.items() if k in ('personal_rating','notes','watched_on','favorite','content_type')}}
    title=str(fields.get('title') or '').strip()
    if not title: raise ValueError('Informe o título do filme.')
    if len(title)>250: raise ValueError('O título está muito comprido.')
    fields['title']=title
    fields['personal_rating']=parse_rating(fields.get('personal_rating'))
    fields['favorite']=1 if fields.get('favorite') else 0
    fields['content_type']=normalize_content_type(fields.get('content_type'))
    if fields.get('imdb_id'): fields['imdb_id']=imdb_id_from_input(fields['imdb_id'])
    if 'trailer_url' in fields: fields['trailer_url']=normalize_trailer_url(fields['trailer_url'])
    for k in fields:
        if isinstance(fields[k],str) and len(fields[k])>20000: raise ValueError('Campo muito longo: '+k)
    with connection() as db:
        if fields.get('imdb_id') and db.execute('SELECT 1 FROM movies WHERE imdb_id=?',(fields['imdb_id'],)).fetchone():
            raise ValueError('Este filme já está no seu ranking.')
        fields['sort_order']=next_order(db,fields['personal_rating'])
        fields['created_at']=now(); fields['updated_at']=now()
        col=','.join(fields)
        cur=db.execute(f'INSERT INTO movies({col}) VALUES ({",".join("?" for _ in fields)})',tuple(fields.values()))
        movie_id=cur.lastrowid
    if fields.get('poster'):
        local=cache_poster(movie_id,fields['poster'])
        if local:
            with connection() as db: db.execute('UPDATE movies SET poster_local=? WHERE id=?',(local,movie_id))
    return get_movie(movie_id)

def edit_movie(movie_id, payload):
    fields={k:payload[k] for k in payload if k in COLUMNS}
    if not fields: return get_movie(movie_id)
    if 'personal_rating' in fields: fields['personal_rating']=parse_rating(fields['personal_rating'])
    if 'trailer_url' in fields: fields['trailer_url']=normalize_trailer_url(fields['trailer_url'])
    if 'favorite' in fields: fields['favorite']=1 if fields['favorite'] else 0
    if 'content_type' in fields:
        fields['content_type']=normalize_content_type(fields['content_type'])
        if fields['content_type']=='series' and get_movie(movie_id).get('top3_position'):
            raise ValueError('Remova o título do Top 3 antes de alterar para série.')
    if 'imdb_id' in fields:
        fields['imdb_id']=imdb_id_from_input(fields['imdb_id']) if fields['imdb_id'] else None
    if 'title' in fields and not str(fields['title']).strip(): raise ValueError('Informe o título.')
    for k in fields:
        if isinstance(fields[k],str) and len(fields[k])>20000: raise ValueError('Texto muito longo em '+k)
    current=get_movie(movie_id)
    old_score=current['personal_rating']
    if fields.get('personal_rating',old_score)!=old_score:
        with connection() as db:
            fields['sort_order']=next_order(db,fields['personal_rating'])
    fields['updated_at']=now()
    with connection() as db:
        db.execute('UPDATE movies SET '+', '.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),movie_id))
    if 'poster' in fields:
        local=cache_poster(movie_id,fields['poster'])
        with connection() as db: db.execute('UPDATE movies SET poster_local=? WHERE id=?',(local,movie_id))
    return get_movie(movie_id)

def sync_movie(movie_id, payload=None):
    """Reidentifica um título por ID e busca metadados sem perder a nota do casal.

    A entrada nova tem prioridade sobre o ID já salvo. Uma busca por IMDb ID
    não é rejeitada por um ano previamente cadastrado incorretamente.
    """
    item=get_movie(movie_id)
    payload=payload if isinstance(payload,dict) else {}
    supplied_id=imdb_id_from_input(payload.get('imdb_id')) if payload.get('imdb_id') else ''
    imdb_id=supplied_id or movie_expected_id(item)
    params={'plot':'full'}
    if imdb_id:
        params['i']=imdb_id
    else:
        params['t']=item['original_title'] or item['title']
        if item['year'] and re.fullmatch(r'\d{4}',str(item['year'])):
            params['y']=item['year']
    raw=get_remote(params)
    remote_type=raw.get('Type') or 'movie'
    if remote_type not in ('movie','series'):
        raise ValueError('O ID retornou um tipo de produção não suportado (episódio ou jogo).')
    if remote_type != normalize_content_type(item.get('content_type')):
        raise ValueError('O ID pertence a '+('uma série' if remote_type=='series' else 'um filme')+'. Altere primeiro o tipo na ficha e salve.')
    response_id=str(raw.get('imdbID') or '').lower()
    if imdb_id and response_id!=imdb_id.lower():
        raise ValueError('A OMDb devolveu um ID diferente do solicitado. Nenhum dado foi alterado.')
    if not imdb_id:
        # Busca só por título: valida o ano para não associar outro homônimo.
        received_year=str(raw.get('Year') or '')[:4]
        expected_year=str(item.get('year') or '')[:4]
        if expected_year.isdigit() and received_year.isdigit() and expected_year != received_year:
            raise ValueError('A busca por título encontrou outro ano. Cole o ID do IMDb na ficha.')
    canonical=metadata_from_omdb(raw)
    identity_changed=bool(response_id and response_id!=str(item.get('imdb_id') or '').lower())
    changes={}
    for field in OMDB_FIELDS:
        new_value=canonical.get(field)
        if identity_changed:
            # Ao trocar ID, nunca manter capas/notas/elenco do filme incorreto.
            changes[field]=new_value
        elif new_value is not None:
            # OMDb pode dizer N/A: não destrua uma nota válida já armazenada.
            # Elenco enriquecido ou manual não deve ser reduzido aos 3 atores da OMDb.
            if field=='actors':
                old=cast_names(item.get('actors'))
                fresh=cast_names(new_value)
                seen={safe_title(n) for n in old}
                changes[field]=', '.join(old+[n for n in fresh if safe_title(n) not in seen])
            else:
                changes[field]=new_value
    if identity_changed or not item.get('original_title'):
        changes['original_title']=clean_value(raw.get('Title'))
    if imdb_id or identity_changed or not item.get('year'):
        # O ID exato é autoritativo, mesmo que um ano anterior esteja errado.
        changes['year']=clean_value(raw.get('Year'))
    if response_id: changes['imdb_id']=response_id
    changes['content_type']=remote_type
    # Mantém o nome personalizado em português e toda avaliação do casal.
    updated=edit_movie(movie_id,changes)
    missing=[]
    if not updated.get('imdb_rating'): missing.append('IMDb')
    if not updated.get('metascore'): missing.append('Metascore')
    updated['_sync']={'source':'OMDb','matched_id':response_id,
                      'identity_changed':identity_changed,'missing':missing}
    return updated

def move_movie(movie_id, rating, before_id=None):
    target=parse_rating(rating)
    with connection() as db:
        old=db.execute('SELECT personal_rating FROM movies WHERE id=?',(movie_id,)).fetchone()
        if not old: raise ValueError('Filme não encontrado.')
        old_rating=old[0]
        affected=[old_rating] if old_rating==target else [old_rating,target]
        orders={}
        for score in affected:
            orders[score]=[r[0] for r in db.execute(
                'SELECT id FROM movies WHERE personal_rating IS ? ORDER BY sort_order,id',(score,))]
        orders[old_rating].remove(movie_id)
        goal=orders[target]
        if before_id and before_id in goal:
            goal.insert(goal.index(before_id),movie_id)
        else:
            goal.append(movie_id)
        for score, ids in orders.items():
            for i, mid in enumerate(ids):
                db.execute('UPDATE movies SET personal_rating=?,sort_order=?,updated_at=? WHERE id=?',
                           (score,i,now(),mid))
    return get_movie(movie_id)

def change_top3(movie_id,action):
    """Três vagas ordenadas; um título só pode ocupar uma vaga. Série não entra."""
    if action not in ('add','remove','up','down'):
        raise ValueError('Ação inválida para o Top 3.')
    with connection() as db:
        target=db.execute('SELECT id,content_type FROM movies WHERE id=?',(movie_id,)).fetchone()
        if not target: raise ValueError('Título não encontrado.')
        if target['content_type']=='series':
            raise ValueError('O Top 3 é reservado aos filmes. Séries continuam no ranking normal.')
        ids=[r[0] for r in db.execute('SELECT id FROM movies WHERE top3_position IS NOT NULL ORDER BY top3_position, id')]
        if action=='add':
            if movie_id not in ids:
                if len(ids)>=3: raise ValueError('O Top 3 já tem três filmes. Retire um antes de adicionar outro.')
                ids.append(movie_id)
        elif action=='remove':
            if movie_id in ids: ids.remove(movie_id)
        elif movie_id in ids:
            old=ids.index(movie_id)
            new=max(0,old-1) if action=='up' else min(len(ids)-1,old+1)
            ids.pop(old);ids.insert(new,movie_id)
        db.execute('UPDATE movies SET top3_position=NULL,updated_at=? WHERE top3_position IS NOT NULL',(now(),))
        for i,mid in enumerate(ids,1):
            db.execute('UPDATE movies SET top3_position=?,updated_at=? WHERE id=?',(i,now(),mid))
    return {'top3':ids,'movie':get_movie(movie_id)}

def import_data(filename, content, mode='merge'):
    if len(content)>6*1024*1024: raise ValueError('Arquivo muito grande (máximo 6 MB).')
    incoming=[]
    is_backup=False
    if filename.lower().endswith('.json'):
        doc=json.loads(content)
        is_backup=isinstance(doc,dict) and doc.get('format')=='CineDuo' and doc.get('version') in (1,2,3)
        incoming=doc.get('movies',[]) if isinstance(doc,dict) else doc
        if not isinstance(incoming,list): raise ValueError('JSON inválido.')
    else:
        sample=content[:4000]
        try: delimiter=csv.Sniffer().sniff(sample,delimiters=',;\t').delimiter
        except csv.Error: delimiter=','
        rdr=csv.DictReader(io.StringIO(content.lstrip('\ufeff')),delimiter=delimiter)
        for row in rdr:
            r={norm_col(k):v for k,v in row.items() if k}
            def pick(*ks):
                for k in ks:
                    val=r.get(k)
                    if val is not None and str(val).strip(): return str(val).strip()
                return None
            title=pick('title','titulo','movie','filme','name','primary title','original title')
            if not title: continue
            score=pick('nossa nota','nota pessoal','nota do casal','personal rating','personal rating 0 10',
                       'you rated','your rating','minha nota','my rating','score','rating pessoal','nota')
            mid=pick('const','imdb id','imdbid','imdb id imdb','tconst')
            url=pick('url','imdb url','link imdb')
            if not mid and url:
                match=re.search(r'tt\d{7,10}',url)
                if match: mid=match.group()
            incoming.append({'title':title,'original_title':pick('original title','titulo original'),
              'year':pick('year','ano','release year','ano de lancamento'),
              'content_type':pick('type','tipo','content type') or 'movie',
              'personal_rating':score,'imdb_id':mid,'trailer_url':pick('trailer url','trailer','link do trailer'),
              'imdb_rating':pick('imdb rating','imdbrating'),
              'notes':pick('notes','description','observacoes','comentario') or '',
              'genre':pick('genres','genre','genero'),
              'runtime':pick('runtime mins','runtime'),
              'poster':pick('poster','poster url','capa')})
    if mode=='replace':
        if not is_backup or not incoming or len(incoming)>2000 or not all(isinstance(x,dict) and (x.get('title') or x.get('Title')) for x in incoming):
            raise ValueError('Backup inválido. Nenhum filme existente foi alterado.')
        with connection() as db:
            db.execute('DELETE FROM verified_movie_cast')
            db.execute('DELETE FROM manual_movie_cast')
            db.execute('DELETE FROM saga_part_order')
            db.execute('DELETE FROM movie_tmdb')
            db.execute('DELETE FROM saga_parts')
            db.execute('DELETE FROM saga_folders')
            db.execute('DELETE FROM actor_photos')
            db.execute('DELETE FROM movies')
        for f in POSTERS.glob('*'):
            if f.is_file(): f.unlink(missing_ok=True)
    inserted=0; skipped=0; problems=[]
    restored_top3=[]
    for data in incoming[:2000]:
        try:
            if not isinstance(data,dict): skipped+=1; continue
            title=data.get('title') or data.get('Title')
            if not title: skipped+=1; continue
            m=data.get('imdb_id') or data.get('imdbID')
            yr=str(data.get('year') or '')[:4]
            with connection() as db:
                already=(db.execute('SELECT 1 FROM movies WHERE imdb_id=?',(m,)).fetchone() if m else None)
                if not already:
                    already=db.execute('SELECT 1 FROM movies WHERE (LOWER(title)=LOWER(?) OR LOWER(COALESCE(original_title,\'\'))=LOWER(?)) AND COALESCE(year,\'\')=?',
                                      (title,title,yr)).fetchone()
            if already: skipped+=1; continue
            fields={k:v for k,v in data.items() if k in COLUMNS}
            fields['title']=title
            if m: fields['imdb_id']=m
            newly_added=add_movie(fields)
            if is_backup and data.get('top3_position') is not None:
                try:
                    place=int(data['top3_position'])
                    if 1 <= place <= 3 and newly_added['content_type']=='movie':
                        restored_top3.append((place,newly_added['id']))
                except (ValueError,TypeError): pass
            inserted+=1
        except (ValueError,sqlite3.IntegrityError) as err:
            skipped+=1
            if len(problems)<5: problems.append(f'{title}: {str(err)}')
    if is_backup and mode=='replace':
        for _,mid in sorted(restored_top3)[:3]:
            change_top3(mid,'add')
        if doc.get('version') in (2,3):
            # A segunda versão preserva notas e pastas personalizadas de sagas,
            # fotografias escolhidas manualmente, sem exportar chaves secretas.
            with connection() as db:
                imported=set()
                for item in (doc.get('saga_folders') or [])[:500]:
                    if not isinstance(item,dict):continue
                    key=str(item.get('saga_key') or '')
                    if not re.fullmatch(r'(?:known|tmdb|manual):[A-Za-z0-9_-]{1,100}',key):continue
                    name=str(item.get('name') or '')[:100]
                    if not name:continue
                    source=str(item.get('source') or 'manual')
                    if source not in ('manual','curated','tmdb'):continue
                    rating=item.get('rating')
                    try:rating=parse_rating(rating)
                    except ValueError:rating=None
                    db.execute('INSERT OR IGNORE INTO saga_folders(saga_key,name,source,tmdb_collection_id,rating,hidden,created_at) VALUES(?,?,?,?,?,?,?)',
                               (key,name,source,item.get('tmdb_collection_id') if isinstance(item.get('tmdb_collection_id'),int) else None,
                                rating,0,now()))
                    imported.add(key)
                for item in (doc.get('saga_parts') or [])[:3000]:
                    if not isinstance(item,dict) or item.get('saga_key') not in imported:continue
                    title=str(item.get('title') or '')[:220]
                    if not title:continue
                    imdb_id=item.get('imdb_id')
                    if imdb_id and not re.fullmatch(r'tt\d{7,10}',str(imdb_id)):imdb_id=None
                    tmdb_id=item.get('tmdb_id') if isinstance(item.get('tmdb_id'),int) else None
                    db.execute('INSERT INTO saga_parts(saga_key,title,year,imdb_id,tmdb_id,poster,part_order) VALUES(?,?,?,?,?,?,?)',
                        (item['saga_key'],title,str(item.get('year') or '')[:4],imdb_id,tmdb_id,
                         str(item.get('poster') or '')[:500] or None,int(item.get('part_order') or 0)))
                for item in (doc.get('actor_photos') or [])[:3000]:
                    if not isinstance(item,dict):continue
                    key=safe_title(str(item.get('artist_key') or ''))
                    url=str(item.get('url') or '')
                    if key and len(key)<=100 and url.startswith(('https://image.tmdb.org/','https://upload.wikimedia.org/',
                            'https://commons.wikimedia.org/','https://m.media-amazon.com/')):
                        db.execute('INSERT OR REPLACE INTO actor_photos(artist_key,url,checked_at) VALUES(?,?,?)',(key,url,str(time.time())))
    if is_backup and mode=='replace' and doc.get('version')==3:
        # IDs autoincrementados mudam ao restaurar; mapas por IMDb ID.
        with connection() as db:
            db_map={str(r['imdb_id']):r['id'] for r in db.execute(
                'SELECT id,imdb_id FROM movies WHERE imdb_id IS NOT NULL')}
            for item in (doc.get('verified_cast') or [])[:2000]:
                if not isinstance(item,dict):continue
                imdb=str(item.get('imdb_id') or '')
                names=cast_names(item.get('actors') or [])[:300]
                if imdb in db_map and names:
                    db.execute('INSERT OR REPLACE INTO verified_movie_cast(movie_id,imdb_id,actors_json,checked_at,source) VALUES(?,?,?,?,?)',
                               (db_map[imdb],imdb,json.dumps(names,ensure_ascii=False),now(),'TMDb'))
            for item in (doc.get('manual_cast') or [])[:4000]:
                if not isinstance(item,dict):continue
                imdb=str(item.get('imdb_id') or '')
                name=str(item.get('artist_name') or '').strip()[:100]
                if imdb in db_map and name:
                    db.execute('INSERT OR IGNORE INTO manual_movie_cast(movie_id,artist_key,artist_name) VALUES(?,?,?)',
                               (db_map[imdb],safe_title(name),name))
            for item in (doc.get('saga_part_order') or [])[:3000]:
                if not isinstance(item,dict):continue
                key=str(item.get('saga_key') or '')
                part=str(item.get('part_key') or '')
                seq=item.get('sort_index')
                if key and part and isinstance(seq,int) and 0<=seq<1000:
                    db.execute('INSERT OR IGNORE INTO saga_part_order(saga_key,part_key,sort_index) VALUES(?,?,?)',
                               (key,part,seq))
    return {'inserted':inserted,'skipped':skipped,'problems':problems,
            'tip':'Filmes sem nota pessoal aparecem em “A avaliar”. Use Atualizar capas para completar dados.'}

def csv_export():
    rows=all_movies()
    buf=io.StringIO(); names=['Nossa nota','Title','Original Title','Year','IMDb ID','IMDb Rating',
       'Metascore','Rotten Tomatoes','Notes','Watched On','Tipo','Top 3','Genre','Runtime','Director','Actors','Plot','Poster URL','Trailer URL']
    writer=csv.writer(buf); writer.writerow(names)
    for m in rows:
        writer.writerow([m.get(k) for k in ['personal_rating','title','original_title','year','imdb_id',
            'imdb_rating','metascore','rotten_tomatoes','notes','watched_on','content_type','top3_position','genre',
            'runtime','director','actors','plot','poster','trailer_url']])
    return buf.getvalue().encode('utf-8-sig')