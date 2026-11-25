#!/usr/bin/env python3
"""CineDuo — catálogo e ranking particular do casal. Apenas biblioteca padrão."""
from __future__ import annotations

import argparse
import csv
import shutil
import unicodedata
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import ssl
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, urlencode, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import webbrowser

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'app_data'
POSTERS = DATA / 'posters'
DB = DATA / 'cineduo.sqlite3'
DATA.mkdir(exist_ok=True)
POSTERS.mkdir(exist_ok=True)
OMDB_URL = 'https://www.omdbapi.com/'
# IDs verificados para corrigir registros antigos quando uma busca por título
# vinculou, por engano, uma produção homônima. Não contém notas inventadas.
KNOWN_IMDB_IDS = {
    ('ainda estou aqui', '2024'): 'tt14961016',
    ('verity', '2026'): 'tt32261958',
}
OMDB_FIELDS = ('imdb_id','imdb_rating','metascore','rotten_tomatoes', 'runtime','genre','director','actors','plot','poster','country', 'awards','language','box_office','content_type')

def safe_title(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower()) if not unicodedata.combining(c)).strip()

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

def backup_before_v111():
    """Garante cópia antes das novas regras de crédito e cronologia."""
    if not DB.is_file():return
    folder=DATA/'backups';folder.mkdir(exist_ok=True)
    output=folder/'antes-da-v1.11.sqlite3'
    if not output.exists():
        with sqlite3.connect(DB) as old,sqlite3.connect(output) as saved:old.backup(saved)

def backup_before_v17():
    """Cópia única anterior à atualização de elenco e avatares."""
    if not DB.is_file(): return
    backup_dir=DATA / 'backups'
    backup_dir.mkdir(exist_ok=True)
    target=backup_dir / 'antes-da-v1.7.sqlite3'
    if target.exists(): return
    with sqlite3.connect(DB) as source, sqlite3.connect(target) as replica:
        source.backup(replica)

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

def external_json(url,timeout=6):
    """Consulta apenas os endpoints pré-definidos. Não recebe URLs arbitrárias do cliente."""
    req=Request(url,headers={
        'User-Agent':'CineDuo/1.8 (personal film catalog; metadata lookup)',
        'Accept':'application/json'})
    with urlopen(req,timeout=timeout) as response:
        raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024: raise ValueError('Resposta externa muito grande.')
    return json.loads(raw.decode('utf-8'))

def cinemeta_cast(imdb_id,kind):
    url=f'https://v3-cinemeta.strem.io/meta/{kind}/{imdb_id}.json'
    doc=external_json(url,timeout=7)
    meta=doc.get('meta') or {}
    if str(meta.get('id') or '').split(':')[0]!=imdb_id: return []
    return cast_names(meta.get('cast') or [])[:90]

def wikidata_cast(imdb_id):
    query=('SELECT DISTINCT ?personLabel WHERE { '
        f'?film wdt:P345 "{imdb_id}"; wdt:P161 ?person. '
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,pt". } } LIMIT 80')
    url='https://query.wikidata.org/sparql?'+urlencode({'query':query,'format':'json'})
    doc=external_json(url,timeout=7)
    return cast_names([r.get('personLabel',{}).get('value') for r in
                       doc.get('results',{}).get('bindings',[]) if r.get('personLabel',{}).get('type')=='literal'])

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

# Retratos consultados nas páginas do Wikimedia Commons (links remotos, não baixados).
# Crédito, autoria e licenças estão nas páginas de cada arquivo; consultáveis
# em "Fonte da foto" no aplicativo. Só sugerimos nomes identificados com segurança.
CURATED_ACTOR_PHOTOS = {
    'vera farmiga': 'Vera Farmiga by Gage Skidmore.jpg',
    'patrick wilson': 'Patrick Wilson by Gage Skidmore.jpg',
    'tom holland': 'Tom Holland by Gage Skidmore.jpg',
    'zendaya': 'Zendaya 2024.jpg',
    'amanda seyfried': 'Amanda Seyfried at Berlinale 2024, cropped.jpg',
    'anne hathaway': 'Anne Hathaway at Berlinale 2023 (close-up).jpg',
}

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
        # Wikipédia pode bloquear requisições. Wikidata P18 fornece a foto Commons
        # vinculada ao artista, sem assumir que todo homônimo é a mesma pessoa.
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


def backup_before_v18():
    """Uma cópia única de segurança antes de adicionar sagas e participações."""
    if not DB.is_file(): return
    folder=DATA/'backups';folder.mkdir(exist_ok=True)
    backup=folder/'antes-da-v1.8.sqlite3'
    if not backup.exists():
        with sqlite3.connect(DB) as source,sqlite3.connect(backup) as dest: source.backup(dest)

# Catálogo inicial validado por títulos e datas. Outras sagas vêm da TMDb,
# pelo identificador correto de cada filme, quando configurada.
# Em especial, o universo Invocação do Mal reúne três subfranquias que a
# TMDb normalmente trata como coleções separadas.
SAGA_CATALOG={
 # Duologia lançada. Novas produções anunciadas só entram no catálogo quando
 # lançadas e identificadas, para não declarar incompleta uma duologia assistida.
 'orphan': {'name':'A Órfã','parts':[
  ('A Órfã',2009,'tt1148204',['orphan','a orfa','orfa','a orfa 1']),
  ('Órfã 2: A Origem',2022,'tt11851548',[
   'orphan first kill','orphan: first kill','a orfa 2 a origem',
   'orfa 2 a origem','orfa 2','a orfa a origem','orfa a origem'])]},
 'avatar': {'name':'Avatar','parts':[
  ('Avatar',2009,'tt0499549',['avatar']),
  ('Avatar: O Caminho da Água',2022,'tt1630029',['avatar the way of water','avatar o caminho da agua']),
  ('Avatar: Fogo e Cinzas',2025,'tt1757678',['avatar fire and ash','avatar fogo e cinzas'])]},
 'conjuring-universe': {'name':'Universo Invocação do Mal','parts':[
  ('Invocação do Mal',2013,'tt1457767',['the conjuring','invocacao do mal']),
  ('Annabelle',2014,'tt3322940',['annabelle']),
  ('A Maldição da Chorona',2019,'tt4913966',['the curse of la llorona','the curse of the weeping woman','a maldicao da chorona','maldicao da chorona','la llorona']),
  ('Invocação do Mal 2',2016,'tt3065204',['the conjuring 2','invocacao do mal 2']),
  ('Annabelle 2: A Criação do Mal',2017,'tt5140878',['annabelle creation','annabelle a criacao do mal']),
  ('A Freira',2018,'tt5814060',['the nun','a freira']),
  ('Annabelle 3: De Volta para Casa',2019,'tt8350360',['annabelle comes home','annabelle 3']),
  ('Invocação do Mal 3: A Ordem do Demônio',2021,'tt7069210',['the conjuring the devil made me do it','the conjuring 3','invocacao do mal 3']),
  ('A Freira 2',2023,'tt10160976',['the nun ii','the nun 2','a freira ii']),
  ('Invocação do Mal 4: O Último Ritual',2025,'tt22898462',['the conjuring last rites','the conjuring 4','invocacao do mal 4'])]},
 'purge': {'name':'Uma Noite de Crime','parts':[
  ('Uma Noite de Crime',2013,'tt2184339',['the purge','uma noite de crime']),
  ('Uma Noite de Crime: Anarquia',2014,'tt2975578',['the purge anarchy','uma noite de crime anarquia']),
  ('12 Horas para Sobreviver: O Ano da Eleição',2016,'tt4094724',['the purge election year','12 horas para sobreviver o ano da eleicao']),
  ('A Primeira Noite de Crime',2018,'tt6133466',['the first purge','a primeira noite de crime']),
  ('Uma Noite de Crime: A Fronteira',2021,'tt10327252',['the forever purge','uma noite de crime a fronteira'])]},
 'john-wick': {'name':'John Wick','parts':[
  ('John Wick',2014,'tt2911666',['john wick de volta ao jogo']),
  ('John Wick 2',2017,'tt4425200',['john wick chapter 2','john wick um novo dia para matar']),
  ('John Wick 3',2019,'tt6146586',['john wick chapter 3 parabellum']),
  ('John Wick 4',2023,'tt10366206',['john wick chapter 4','john wick baba yaga'])]},
 'dark-knight': {'name':'Trilogia Batman — Nolan','parts':[
  ('Batman Begins',2005,'tt0372784',['batman begins']),
  ('Batman: O Cavaleiro das Trevas',2008,'tt0468569',['the dark knight','batman o cavaleiro das trevas']),
  ('Batman: O Cavaleiro das Trevas Ressurge',2012,'tt1345836',['the dark knight rises','batman o cavaleiro das trevas ressurge'])]},
 'maze-runner': {'name':'Maze Runner','parts':[
  ('Maze Runner: Correr ou Morrer',2014,'tt1790864',['the maze runner','maze runner correr ou morrer']),
  ('Maze Runner: Prova de Fogo',2015,'tt4046784',['maze runner the scorch trials','maze runner prova de fogo']),
  ('Maze Runner: A Cura Mortal',2018,'tt4500922',['maze runner the death cure','maze runner a cura mortal'])]},
 'butterfly-effect': {'name':'Efeito Borboleta','parts':[
  ('Efeito Borboleta',2004,'tt0289879',['the butterfly effect','efeito borboleta']),
  ('Efeito Borboleta 2',2006,'tt0457297',['the butterfly effect 2','efeito borboleta 2']),
  ('Efeito Borboleta 3',2009,'tt1234541',['the butterfly effect 3 revelations','efeito borboleta 3'])]},
 'spider-man-holland': {'name':'Homem-Aranha — Tom Holland','parts':[
  ('Homem-Aranha: De Volta ao Lar',2017,'tt2250912',['spider man homecoming','homem aranha de volta ao lar']),
  ('Homem-Aranha: Longe de Casa',2019,'tt6320628',['spider man far from home','homem aranha longe de casa']),
  ('Homem-Aranha: Sem Volta para Casa',2021,'tt10872600',['spider man no way home','homem aranha sem volta para casa']),
  ('Homem-Aranha: Um Novo Dia',2026,None,['spider man brand new day','homem aranha um novo dia'])]},
 'hunger-games': {'name':'Jogos Vorazes','parts':[
  ('Jogos Vorazes',2012,'tt1392170',['the hunger games']),
  ('Jogos Vorazes: Em Chamas',2013,'tt1951264',['the hunger games catching fire']),
  ('Jogos Vorazes: A Esperança — Parte 1',2014,'tt1951265',['the hunger games mockingjay part 1']),
  ('Jogos Vorazes: A Esperança — Parte 2',2015,'tt1951266',['the hunger games mockingjay part 2']),
  ('Jogos Vorazes: A Cantiga dos Pássaros e das Serpentes',2023,'tt10545296',['the ballad of songbirds and snakes'])]},
 'lotr': {'name':'O Senhor dos Anéis','parts':[
  ('A Sociedade do Anel',2001,'tt0120737',['the lord of the rings the fellowship of the ring','o senhor dos aneis a sociedade do anel']),
  ('As Duas Torres',2002,'tt0167261',['the lord of the rings the two towers','o senhor dos aneis as duas torres']),
  ('O Retorno do Rei',2003,'tt0167260',['the lord of the rings the return of the king','o senhor dos aneis o retorno do rei'])]},
 'godfather': {'name':'O Poderoso Chefão','parts':[
  ('O Poderoso Chefão',1972,'tt0068646',['the godfather','o poderoso chefao']),
  ('O Poderoso Chefão II',1974,'tt0071562',['the godfather part ii','o poderoso chefao 2']),
  ('O Poderoso Chefão III',1990,'tt0099674',['the godfather part iii','o poderoso chefao 3'])]},
}

# Ordem pelo ano principal dos acontecimentos na ficção. Para coletâneas
# cuja narrativa não é linear, usa-se a posição mais apropriada para a história.
# IMDb IDs identificam os capítulos e evitam confundir filmes homônimos.
SAGA_STORY_ORDER = {
    'conjuring-universe': [
        'tt5814060', 'tt5140878', 'tt10160976', 'tt3322940',
        'tt1457767', 'tt8350360', 'tt4913966', 'tt3065204',
        'tt7069210', 'tt22898462',
    ],
    'orphan': ['tt11851548', 'tt1148204'],
    'purge': ['tt6133466', 'tt2184339', 'tt2975578', 'tt4094724', 'tt10327252'],
    'hunger-games': ['tt10545296', 'tt1392170', 'tt1951264', 'tt1951265', 'tt1951266'],
}
SAGA_STORY_YEARS = {
    'tt5814060':'1952', 'tt5140878':'1955', 'tt10160976':'1956',
    'tt3322940':'1967', 'tt1457767':'1971', 'tt8350360':'1972',
    'tt4913966':'1973', 'tt3065204':'1977', 'tt7069210':'1981',
    'tt22898462':'1986',
}


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

def upgrade_backup():
    """Salva uma cópia de segurança da base existente UMA VEZ antes da v1.3."""
    if not DB.is_file(): return
    backups=DATA/'backups'
    backups.mkdir(exist_ok=True)
    target=backups/'antes-da-v1.3.sqlite3'
    if target.exists(): return
    source=sqlite3.connect(DB)
    replica=sqlite3.connect(target)
    try: source.backup(replica)
    finally: replica.close(); source.close()

def backup_before_v16():
    """Backup transacional prévio para atualização das séries e do Top 3."""
    if not DB.is_file(): return
    backup_dir = DATA / 'backups'
    backup_dir.mkdir(exist_ok=True)
    target = backup_dir / 'antes-da-v1.6.sqlite3'
    if target.exists(): return
    with sqlite3.connect(DB) as source, sqlite3.connect(target) as replica:
        source.backup(replica)


def normalize_content_type(value):
    value = str(value or 'movie').strip().lower()
    if value not in ('movie', 'series'):
        raise ValueError('Escolha Filme ou Série como tipo de título.')
    return value


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


def backup_before_v14():
    """Cópia única do banco antes de adicionar trailer_url (sem perdas)."""
    if not DB.is_file(): return
    backup_dir = DATA / 'backups'
    backup_dir.mkdir(exist_ok=True)
    target = backup_dir / 'antes-da-v1.4.sqlite3'
    if target.exists(): return
    with sqlite3.connect(DB) as source, sqlite3.connect(target) as replica:
        source.backup(replica)


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


# Instalações públicas começam vazias. Os dados do usuário são criados apenas no cadastro/importação.
# Nunca incluir filmes pessoais ou credenciais como dados de exemplo automáticos.
COLUMNS = {'title', 'original_title', 'year', 'personal_rating', 'notes', 'watched_on', 'favorite',
           'imdb_id', 'imdb_rating', 'metascore', 'rotten_tomatoes', 'runtime', 'genre', 'director',
           'actors', 'plot', 'poster', 'country', 'awards', 'language', 'box_office', 'trailer_url', 'content_type'}
MAPPING = {'Title':'title','Year':'year','imdbID':'imdb_id','imdbRating':'imdb_rating',
           'Metascore':'metascore','Runtime':'runtime','Genre':'genre','Director':'director',
           'Actors':'actors','Plot':'plot','Poster':'poster','Country':'country',
           'Awards':'awards','Language':'language','BoxOffice':'box_office'}


def now():
    return datetime.now().isoformat(timespec='seconds')

@contextmanager
def connection():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def setup():
    upgrade_backup()
    backup_before_v14()
    backup_before_v16()
    backup_before_v17()
    backup_before_v18()
    backup_before_v111()
    with connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS movies (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, original_title TEXT,
          year TEXT, personal_rating INTEGER CHECK(personal_rating BETWEEN 0 AND 10),
          notes TEXT DEFAULT '', watched_on TEXT, favorite INTEGER DEFAULT 0,
          imdb_id TEXT UNIQUE, imdb_rating TEXT, metascore TEXT, rotten_tomatoes TEXT,
          runtime TEXT, genre TEXT, director TEXT, actors TEXT, plot TEXT, poster TEXT,
          poster_local TEXT, country TEXT, awards TEXT, language TEXT, box_office TEXT,
          sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL)''')
        cols = {row[1] for row in db.execute('PRAGMA table_info(movies)')}
        if 'trailer_url' not in cols:
            db.execute('ALTER TABLE movies ADD COLUMN trailer_url TEXT')
        if 'content_type' not in cols:
            db.execute("ALTER TABLE movies ADD COLUMN content_type TEXT NOT NULL DEFAULT 'movie'")
        if 'top3_position' not in cols:
            db.execute('ALTER TABLE movies ADD COLUMN top3_position INTEGER')
        db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS actor_photos (artist_key TEXT PRIMARY KEY, url TEXT, checked_at TEXT NOT NULL)')
        actor_columns={row[1] for row in db.execute('PRAGMA table_info(actor_photos)')}
        if 'source' not in actor_columns:
            db.execute("ALTER TABLE actor_photos ADD COLUMN source TEXT NOT NULL DEFAULT 'auto'")
        # Caches de erro vazios (versões anteriores) não devem ocultar fotos
        # cuidadosamente identificadas; nunca sobrepõe a escolha manual.
        for artist_key, filename in CURATED_ACTOR_PHOTOS.items():
            url=commons_file_url(filename)
            db.execute('INSERT INTO actor_photos(artist_key,url,checked_at,source) VALUES(?,?,?,?) '
                       "ON CONFLICT(artist_key) DO UPDATE SET url=excluded.url,checked_at=excluded.checked_at,source='curated' "
                       "WHERE actor_photos.source != 'manual' AND (actor_photos.url IS NULL OR actor_photos.url='')",
                       (artist_key,url,str(time.time()),'curated'))
        db.execute('''CREATE TABLE IF NOT EXISTS saga_folders (
          saga_key TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL,
          tmdb_collection_id INTEGER, rating INTEGER CHECK(rating BETWEEN 0 AND 10),
          hidden INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS saga_parts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, saga_key TEXT NOT NULL,
          title TEXT NOT NULL, year TEXT, imdb_id TEXT, tmdb_id INTEGER,
          poster TEXT, part_order INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(saga_key) REFERENCES saga_folders(saga_key))''')
        db.execute('CREATE INDEX IF NOT EXISTS saga_part_idx ON saga_parts(saga_key,part_order)')
        db.execute('''CREATE TABLE IF NOT EXISTS movie_tmdb (
          movie_id INTEGER PRIMARY KEY, tmdb_id INTEGER NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS saga_part_order (
          saga_key TEXT NOT NULL, part_key TEXT NOT NULL, sort_index INTEGER NOT NULL,
          PRIMARY KEY(saga_key,part_key))''')
        db.execute('''CREATE TABLE IF NOT EXISTS verified_movie_cast (
          movie_id INTEGER PRIMARY KEY, imdb_id TEXT NOT NULL,
          actors_json TEXT NOT NULL, checked_at TEXT NOT NULL, source TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS manual_movie_cast (
          movie_id INTEGER NOT NULL, artist_key TEXT NOT NULL, artist_name TEXT NOT NULL,
          PRIMARY KEY(movie_id,artist_key))''')
        db.execute('CREATE INDEX IF NOT EXISTS movies_score_order ON movies (personal_rating,sort_order)')
        # Não cadastrar filmes automaticamente. Bancos existentes permanecem intactos.
        # Marca a primeira inicialização para fins de compatibilidade com versões antigas.
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('seeded','disabled-v1.12')")


def get_setting(key):
    with connection() as db:
        r=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return r['value'] if r else ''


def save_setting(key,value):
    with connection() as db:
        db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (key,value))


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


def norm_col(k):
    import unicodedata
    k=unicodedata.normalize('NFKD',str(k or '')).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+',' ',k).strip()


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


class Handler(BaseHTTPRequestHandler):
    server_version='CineDuo/1.11'
    def log_message(self,fmt,*args):
        if os.environ.get('CINEDUO_QUIET')!='1': super().log_message(fmt,*args)

    def respond(self, data, status=200, mime='application/json; charset=utf-8'):
        if isinstance(data,bytes): body=data
        elif isinstance(data,str): body=data.encode('utf-8')
        else: body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store' if mime.startswith('application/json') else 'no-cache, max-age=0, must-revalidate')
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError): pass

    def serve_static(self,path):
        path=urlparse(path).path
        static={'/':'index.html','/index.html':'index.html','/style.css':'style.css',
                '/app.js':'app.js','/favicon.svg':'favicon.svg'}
        if path in static:
            filename=ROOT/static[path]
        elif re.fullmatch(r'/posters/\d+\.(jpg|jpeg|png|webp)',path):
            filename=POSTERS/path.split('/')[-1]
        else:
            self.respond({'error':'Caminho não encontrado.'},404); return
        if not filename.is_file(): self.respond({'error':'Arquivo não encontrado.'},404); return
        typ=mimetypes.guess_type(str(filename))[0] or 'application/octet-stream'
        if filename.suffix=='.js': typ='text/javascript'
        self.respond(filename.read_bytes(),mime=typ+'; charset=utf-8' if typ.startswith('text/') else typ)

    def parse_body(self):
        n=int(self.headers.get('Content-Length','0'))
        if n<0 or n>7*1024*1024: raise ValueError('Arquivo enviado muito grande.')
        return json.loads(self.rfile.read(n) or b'{}')

    def dispatch(self,method):
        parsed=urlparse(self.path)
        path=parsed.path
        q=parse_qs(parsed.query)
        if method=='GET' and path=='/api/movies': return all_movies()
        if method=='GET' and path=='/api/actors':
            return {'artists':actor_rankings(q.get('include_series',['0'])[0]=='1')}
        if method=='POST' and path=='/api/actors/manual':
            p=self.parse_body();return actor_manual_add(int(p['movie_id']),p.get('name'),p.get('photo_url'))
        if method=='GET' and path=='/api/sagas':return {'sagas':saga_list()}
        if method=='POST' and path=='/api/sagas/reorder':
            p=self.parse_body();return reorder_saga(p['key'],p.get('index',0),p.get('action','up'))
        if method=='POST' and path=='/api/sagas/scan':
            p=self.parse_body();return saga_scan_tmdb(p.get('limit',6),p.get('offset',0))
        if method=='POST' and path=='/api/sagas':
            p=self.parse_body();return saga_create(p.get('name'))
        if method=='POST' and path=='/api/sagas/rating':
            raise ValueError('As notas de sagas agora são calculadas automaticamente a partir das notas dos filmes. Atualize a página (Ctrl+F5).')
        if method=='POST' and path=='/api/sagas/part':
            p=self.parse_body();return saga_add_part(p['key'],p.get('title'),p.get('year'),p.get('imdb_id'))
        if method=='GET' and path=='/api/actor-photo':
            return actor_photo(q.get('name',[''])[0])
        if method=='POST' and path=='/api/actor-photo':
            p=self.parse_body();return set_actor_photo(p.get('name'),p.get('photo_url'))
        if method=='GET' and path=='/api/test-tmdb':
            key=get_setting('tmdb_key')
            if not key:raise ValueError('A chave TMDb ainda não foi configurada em Ajustes.')
            try:
                doc=external_json('https://api.themoviedb.org/3/configuration?'+urlencode({'api_key':key}),timeout=9)
                if not doc.get('images'):
                    raise ValueError('A TMDb respondeu, mas não devolveu a configuração esperada.')
                return {'ok':True,'message':'Conexão TMDb funcionando. Pode usar Completar elencos.'}
            except HTTPError as err:
                if err.code in (401,403):raise ValueError('A TMDb recusou a chave (HTTP 401/403). Utilize a chave API v3, não o token Read Access.')
                raise ValueError(f'A TMDb respondeu HTTP {err.code}.')
            except (URLError,TimeoutError,OSError):
                raise ValueError('Não foi possível acessar a TMDb. Confira sua conexão de internet.')
        if method=='GET' and path=='/api/actors/diagnostics':
            with connection() as db:
                total=db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]
                filled=db.execute("SELECT COUNT(*) FROM movies WHERE actors IS NOT NULL AND TRIM(actors)!=''").fetchone()[0]
                photos=db.execute("SELECT COUNT(*) FROM actor_photos WHERE url IS NOT NULL AND url!=''").fetchone()[0]
                confirmed=db.execute('SELECT COUNT(*) FROM verified_movie_cast').fetchone()[0]
            return {'titles':total,'with_cast':filled,'with_photo':photos,'verified_cast':confirmed,
                    'tmdb_key_configured':bool(get_setting('tmdb_key'))}
        if method=='POST' and path=='/api/actors/enrich':
            body=self.parse_body()
            return enrich_movie_cast(int(body['id']))
        if method=='GET' and path=='/api/settings':
            return {'has_tmdb_key':bool(get_setting('tmdb_key')),
                    'has_key':bool(get_setting('omdb_key') or os.environ.get('OMDB_API_KEY')),
                    'key_source':'ambiente' if os.environ.get('OMDB_API_KEY') and not get_setting('omdb_key') else 'configuração'}
        if method=='POST' and path=='/api/tmdb-settings':
            key=str(self.parse_body().get('tmdb_key') or '').strip()
            if key and not re.fullmatch(r'[A-Za-z0-9._-]{20,300}',key):
                raise ValueError('Chave TMDb inválida. Use a chave API v3.3 ou deixe vazio para removê-la.')
            save_setting('tmdb_key',key)
            return {'ok':True,'has_tmdb_key':bool(key)}
        if method=='POST' and path=='/api/settings':
            key=str(self.parse_body().get('omdb_key') or '').strip()
            if key and not re.fullmatch(r'[A-Za-z0-9]{5,64}',key): raise ValueError('Chave OMDb inválida.')
            save_setting('omdb_key',key)
            return {'ok':True,'has_key':bool(key)}
        if method=='GET' and path=='/api/search':
            term=q.get('q',[''])[0].strip()
            # O mesmo campo aceita título, IMDb ID e URL completa do IMDb.
            imdb_match=re.fullmatch(r'tt\d{7,10}',term,re.I)
            imdb_url=re.fullmatch(r'https?://(?:www\.)?imdb\.com/(?:[a-z]{2}/)?title/(tt\d{7,10})(?:[/?#].*)?',term,re.I)
            imdb_id=(imdb_match.group(0) if imdb_match else imdb_url.group(1) if imdb_url else '').lower()
            if imdb_id:
                found=get_remote({'i':imdb_id,'plot':'full'})
                if found.get('imdbID','').lower()!=imdb_id:
                    raise ValueError('A OMDb retornou um ID diferente. Tente novamente.')
                if found.get('Type') not in (None,'movie','series'):
                    raise ValueError('Esse ID do IMDb não corresponde a um filme ou série. Confira o link ou código.')
                return {'Search':[found],'totalResults':'1','Response':'True','searchMode':'imdb_id'}
            if len(term)<2: return {'Search':[]}
            desired=q.get('type',['movie'])[0]
            if desired not in ('movie','series'): raise ValueError('Tipo inválido.')
            return get_remote({'s':term,'type':desired,'page':q.get('page',['1'])[0]})
        if method=='GET' and path=='/api/test-omdb':
            # Teste com ID fixo: diferencia problemas de conexão/chave de títulos que não existem.
            result=get_remote({'i':'tt0133093','plot':'short'})
            if result.get('imdbID')!='tt0133093':
                raise ValueError('A OMDb retornou uma resposta inesperada. Tente novamente.')
            return {'ok':True,'message':'Conexão com a OMDb funcionando. Chave válida!'}
        if method=='GET' and path=='/api/omdb':
            imdb=q.get('i',[''])[0]
            if not re.fullmatch(r'tt\d{7,10}',imdb): raise ValueError('Informe um ID IMDb válido.')
            return get_remote({'i':imdb,'plot':'full'})
        if method=='GET' and path=='/api/export.csv':
            self.respond(csv_export(),mime='text/csv; charset=utf-8'); return None
        if method=='GET' and path=='/api/export.json':
            with connection() as db:
                folders=[dict(r) for r in db.execute('SELECT * FROM saga_folders')]
                parts=[dict(r) for r in db.execute('SELECT * FROM saga_parts ORDER BY saga_key,part_order')]
                photos=[dict(r) for r in db.execute('SELECT * FROM actor_photos WHERE url IS NOT NULL AND url != ? ',('',))]
                verified=[{'imdb_id':r['imdb_id'],'actors':json.loads(r['actors_json'])}
                          for r in db.execute('SELECT imdb_id,actors_json FROM verified_movie_cast')]
                manual=[{'imdb_id':r['imdb_id'],'artist_name':r['artist_name']}
                        for r in db.execute('SELECT m.imdb_id,c.artist_name FROM manual_movie_cast c '
                                            'JOIN movies m ON m.id=c.movie_id WHERE m.imdb_id IS NOT NULL')]
                saga_order=[dict(r) for r in db.execute('SELECT * FROM saga_part_order ORDER BY saga_key,sort_index')]
            backup={'format':'CineDuo','version':3,'exported_at':now(),
                'movies':[{k:v for k,v in m.items() if k in COLUMNS or k in ('sort_order','top3_position')} for m in all_movies()],
                'saga_folders':folders,'saga_parts':parts,'actor_photos':photos,
                'verified_cast':verified,'manual_cast':manual,'saga_part_order':saga_order}
            self.respond(json.dumps(backup,ensure_ascii=False,indent=2),mime='application/json; charset=utf-8'); return None
        if method=='POST' and path=='/api/import':
            body=self.parse_body(); return import_data(str(body.get('filename','ranking.csv')),str(body.get('content','')),str(body.get('mode','merge')))
        if method=='POST' and path=='/api/movies':
            p=self.parse_body(); return add_movie(p,fill_from_api=bool(p.get('lookup')))
        if method=='POST' and path=='/api/top3':
            p=self.parse_body()
            return change_top3(int(p['id']),str(p.get('action','add')))
        if method=='POST' and path=='/api/move':
            p=self.parse_body(); return move_movie(int(p['id']),p.get('personal_rating'),p.get('before_id'))
        match=re.fullmatch(r'/api/movies/(\d+)(/sync)?',path)
        if match:
            mid=int(match.group(1))
            if method=='GET' and not match.group(2): return get_movie(mid)
            if method=='POST' and match.group(2): return sync_movie(mid,self.parse_body())
            if method=='PATCH' and not match.group(2): return edit_movie(mid,self.parse_body())
            if method=='DELETE' and not match.group(2):
                get_movie(mid)
                with connection() as db:
                    db.execute('DELETE FROM verified_movie_cast WHERE movie_id=?',(mid,))
                    db.execute('DELETE FROM manual_movie_cast WHERE movie_id=?',(mid,))
                    db.execute('DELETE FROM movies WHERE id=?',(mid,))
                for f in POSTERS.glob(f'{mid}.*'): f.unlink(missing_ok=True)
                return {'ok':True}
        raise ValueError('Operação não encontrada.')

    def handle_route(self,method):
        try:
            if not self.path.startswith('/api/') and method=='GET':
                self.serve_static(self.path); return
            result=self.dispatch(method)
            if result is not None: self.respond(result)
        except (ValueError,KeyError,TypeError,json.JSONDecodeError,sqlite3.IntegrityError) as e:
            self.respond({'error':str(e)},400)
        except Exception as e:
            print('ERRO INTERNO:',repr(e))
            self.respond({'error':'Erro interno. Verifique o terminal do CineDuo.'},500)

    def do_GET(self): self.handle_route('GET')
    def do_POST(self): self.handle_route('POST')
    def do_PATCH(self): self.handle_route('PATCH')
    def do_DELETE(self): self.handle_route('DELETE')


def main():
    parser=argparse.ArgumentParser(description='CineDuo — seu ranking de filmes e séries')
    parser.add_argument('--network',action='store_true',help='Permitir acesso pelo celular na mesma rede Wi-Fi (sem senha).')
    parser.add_argument('--port',type=int,default=8765)
    opts=parser.parse_args()
    setup()
    host='0.0.0.0' if opts.network else '127.0.0.1'
    server=ThreadingHTTPServer((host,opts.port),Handler)
    link=f'http://127.0.0.1:{server.server_port}'
    print('\n'+'='*55+'\n   CINEDUO  |  Catálogo de filmes e séries\n'+'='*55)
    print(f'\n   Abra no computador: {link}')
    if opts.network:
        print('   No celular: http://IP-DO-COMPUTADOR:'+str(server.server_port))
        print('   Use somente em rede Wi-Fi confiável: não há senha de acesso.')
    print('   Os dados ficam salvos em:',DB)
    print('   Pressione Ctrl+C para encerrar.\n')
    if os.environ.get('CINEDUO_NO_BROWSER')!='1':
        threading.Timer(0.8,lambda: webbrowser.open(link)).start()
    try: server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt: print('\nCineDuo encerrado. Seus filmes continuam salvos.')
    finally: server.server_close()

if __name__=='__main__': main()
