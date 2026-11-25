"""Curated franchise lists and storyline order."""

from __future__ import annotations

SAGA_CATALOG={
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
