"""Paths and constants shared across CineDuo modules."""

from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'app_data'
POSTERS = DATA / 'posters'
DB = DATA / 'cineduo.sqlite3'
# Data is local and never part of the public repository.
DATA.mkdir(parents=True, exist_ok=True)
POSTERS.mkdir(parents=True, exist_ok=True)
OMDB_URL = 'https://www.omdbapi.com/'
KNOWN_IMDB_IDS = {('ainda estou aqui', '2024'): 'tt14961016', ('verity', '2026'): 'tt32261958',}
OMDB_FIELDS = ('imdb_id','imdb_rating','metascore','rotten_tomatoes', 'runtime','genre','director','actors','plot','poster','country', 'awards','language','box_office','content_type')
CURATED_ACTOR_PHOTOS = {
    'vera farmiga': 'Vera Farmiga by Gage Skidmore.jpg',
    'patrick wilson': 'Patrick Wilson by Gage Skidmore.jpg',
    'tom holland': 'Tom Holland by Gage Skidmore.jpg',
    'zendaya': 'Zendaya 2024.jpg',
    'amanda seyfried': 'Amanda Seyfried at Berlinale 2024, cropped.jpg',
    'anne hathaway': 'Anne Hathaway at Berlinale 2023 (close-up).jpg',
}
