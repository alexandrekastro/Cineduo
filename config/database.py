"""SQLite schema, settings, data migrations, and defensive backups."""

from __future__ import annotations
from contextlib import contextmanager
import sqlite3
import time

from .config import CURATED_ACTOR_PHOTOS, DATA, DB
from .utils import commons_file_url

COLUMNS = {'title', 'original_title', 'year', 'personal_rating', 'notes', 'watched_on', 'favorite',
           'imdb_id', 'imdb_rating', 'metascore', 'rotten_tomatoes', 'runtime', 'genre', 'director',
           'actors', 'plot', 'poster', 'country', 'awards', 'language', 'box_office', 'trailer_url', 'content_type'}

MAPPING = {'Title':'title','Year':'year','imdbID':'imdb_id','imdbRating':'imdb_rating',
           'Metascore':'metascore','Runtime':'runtime','Genre':'genre','Director':'director',
           'Actors':'actors','Plot':'plot','Poster':'poster','Country':'country',
           'Awards':'awards','Language':'language','BoxOffice':'box_office'}

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

def backup_before_v18():
    """Uma cópia única de segurança antes de adicionar sagas e participações."""
    if not DB.is_file(): return
    folder=DATA/'backups';folder.mkdir(exist_ok=True)
    backup=folder/'antes-da-v1.8.sqlite3'
    if not backup.exists():
        with sqlite3.connect(DB) as source,sqlite3.connect(backup) as dest: source.backup(dest)

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

def backup_before_v14():
    """Cópia única do banco antes de adicionar trailer_url (sem perdas)."""
    if not DB.is_file(): return
    backup_dir = DATA / 'backups'
    backup_dir.mkdir(exist_ok=True)
    target = backup_dir / 'antes-da-v1.4.sqlite3'
    if target.exists(): return
    with sqlite3.connect(DB) as source, sqlite3.connect(target) as replica:
        source.backup(replica)

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