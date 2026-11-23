# Próximos aprimoramentos do CineDuo

Este documento é um roteiro sugerido. Nenhum dos itens abaixo é considerado implementado só por constar aqui.

## Prioridade 1 — Qualidade e confiabilidade

- [ ] Adicionar testes automatizados de cadastro, notas, sagas, artistas, backup e restauração.
- [ ] Melhorar os relatórios de erros de OMDb/TMDb e evitar respostas vazias silenciosas.
- [ ] Centralizar as integrações externas em módulos separados do servidor.
- [ ] Melhorar o mecanismo de atualização de elencos, com créditos verificáveis e exclusão de voz/narração/arquivo.
- [ ] Revisar a documentação de créditos, fontes e atribuição de imagens.

## Prioridade 2 — Experiência do casal

- [ ] Permitir notas individuais de cada pessoa e média do casal (opcional).
- [ ] Criar filtros por ano, gênero, nota, plataforma e data assistida.
- [ ] Melhorar busca e ordenação dos filmes que não possuem notas externas.
- [ ] Adicionar comparações entre notas pessoais, IMDb e Metascore.
- [ ] Criar exportações CSV legíveis e backups periódicos.

## Prioridade 3 — Sagas e séries

- [ ] Revisar lista e cronologia dos universos cinematográficos com fonte e opção de correção.
- [ ] Separar 'não cadastrado', 'não assistido' e 'ainda não lançado'.
- [ ] Criar página para marcar séries e temporadas assistidas.
- [ ] Exibir progresso por temporada/episódio.

## Prioridade 4 — Acesso remoto

- [ ] Planejar autenticação e autorização para as duas pessoas.
- [ ] Migrar dados locais para banco de dados hospedado de forma segura.
- [ ] Preparar deploy com TLS/HTTPS e revisão de segurança.
- [ ] Suporte para instalar como PWA na tela inicial do celular.

## Organização no GitHub

Criar Issues separadas para cada melhoria, com rótulos como `bug`, `enhancement`, `documentation` e `security`. Trabalhar em branches de funcionalidade e abrir Pull Requests antes de atualizar a branch `main`.
