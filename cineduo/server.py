"""Local HTTP server and JSON endpoints."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlparse
import argparse
import json
import mimetypes
import os
import re
import sqlite3
import threading
import webbrowser

from .artists import actor_manual_add, actor_photo, actor_rankings, enrich_movie_cast, set_actor_photo
from .config import DB, POSTERS, ROOT
from .database import COLUMNS, connection, get_setting, save_setting, setup
from .library import add_movie, all_movies, change_top3, csv_export, edit_movie, get_movie, import_data, move_movie, sync_movie
from .providers import external_json, get_remote
from .sagas import reorder_saga, saga_add_part, saga_create, saga_list, saga_scan_tmdb
from .utils import now


class Handler(BaseHTTPRequestHandler):
    server_version='CineDuo/1.15'
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
