# 🎬 CineDuo

**Nossa história em filmes — um catálogo e ranking pessoal de filmes e séries, feito com Python.**

O CineDuo é uma aplicação web local para organizar os filmes e as séries assistidos por duas pessoas. Permite criar o próprio ranking, comparar avaliações externas, acompanhar franquias e descobrir quais atores apareceram mais vezes nos títulos cadastrados.

> **Estado do projeto:** versão 1.11 · projeto pessoal em desenvolvimento · interface em português.

## ✨ Funcionalidades

- **Ranking por notas** (de 0 a 10) e **ranking geral** com posições numeradas;
- **Top 3 especial**, acima das notas comuns, sem duplicação na categoria 10;
- Cadastro de **filmes e séries**, com capas, sinopses, informações e trailers;
- Integração opcional com **OMDb** (IMDb/Metascore, quando disponíveis) e **TMDb** (coleções, elencos e fotos);
- Ranking de **atores e atrizes** por quantidade de obras cadastradas, com correção manual de participações;
- **Sagas, duologias e trilogias**, mostrando capítulos já cadastrados e capítulos ausentes;
- Médias automáticas das sagas e destaque dourado para coleções completas;
- Ordenação cronológica da história nos agrupamentos conhecidos e ajuste manual nos demais;
- Busca por título, ID ou link do IMDb;
- Armazenamento local em **SQLite** e exportação/importação de backups.

## 💻 Requisitos

- Windows (inicialização por arquivo `.bat`) ou outro sistema com Python;
- **Python 3** instalado e disponível no terminal;
- Navegador web;
- Internet para consultar as APIs externas e carregar pôsteres ou trailers.

Não há dependências externas de Python: a aplicação usa a **biblioteca padrão**.

## 🚀 Como executar

### No Windows

1. Baixe o código do projeto e extraia a pasta.
2. Dê dois cliques em `INICIAR_WINDOWS.bat`.
3. Abra `http://127.0.0.1:8765` caso o navegador não abra sozinho.
4. Em **Ajustes**, configure opcionalmente as chaves de OMDb e TMDb.

### No terminal (Windows, Linux ou macOS)

```bash
python app.py
```

Depois acesse `http://127.0.0.1:8765`.

Para permitir uso em um **celular na mesma rede Wi-Fi**, execute `INICIAR_CELULAR_MESMA_REDE.bat` no Windows ou `python app.py --network` e abra `http://IP-DO-COMPUTADOR:8765` no celular. **Atenção:** esse modo não tem login; use somente em redes confiáveis.

## 🔑 Chaves de API

- **OMDb:** [solicitar chave](https://www.omdbapi.com/apikey.aspx)
- **TMDb:** [configurações de API](https://www.themoviedb.org/settings/api)

Insira as chaves **dentro de Ajustes, na interface do CineDuo**. Os valores são salvos localmente em `app_data/cineduo.sqlite3`, que está listado no `.gitignore` e **não deve ser enviado ao GitHub**.

A OMDb não retorna todos os campos em todas as obras. Os dados de elenco também podem variar entre fontes; edições manuais estão disponíveis quando necessário.

## 🗂️ Estrutura do projeto

```text
CineDuo/
├── app.py                         # Servidor HTTP e SQLite (Python)
├── app.js                         # Interface e interações
├── index.html                     # Estrutura da interface
├── style.css                      # Layout responsivo
├── favicon.svg
├── INICIAR_WINDOWS.bat
├── INICIAR_CELULAR_MESMA_REDE.bat
├── docs/
│   ├── PUBLICAR_NO_GITHUB.md
│   ├── PROXIMOS_APRIMORAMENTOS.md
│   └── HISTORICO_v1_11.txt
└── .github/workflows/validar.yml
```

A pasta `app_data/` é **criada automaticamente ao executar o projeto**. Ela contém dados pessoais, banco SQLite, configurações, capas armazenadas e backups; por isso, não está no repositório.

## 🔒 Privacidade e segurança

O repositório contém apenas o **código-fonte**, não a coleção pessoal dos usuários. Não envie `app_data/`, arquivos de backup, exportações JSON com dados pessoais nem chaves de API para commits ou issues públicos. Veja [SECURITY.md](SECURITY.md).

> **Importante:** o CineDuo, na versão atual, foi feito para funcionar **localmente**. Ele **não está pronto para ser hospedado publicamente sem autenticação e revisão de segurança**. Um repositório público no GitHub **não é** uma hospedagem da aplicação.

## 🧭 Próximos passos

Veja o [plano de aprimoramentos](docs/PROXIMOS_APRIMORAMENTOS.md) para acompanhar as próximas versões. Sugestões e bugs podem ser organizados em **Issues** no GitHub.

## 📄 Licenciamento

O projeto está publicado para fins de portfólio e demonstração. **Nenhuma licença de redistribuição ou reutilização foi escolhida até o momento.** A visibilidade pública do repositório não concede automaticamente uma licença de código aberto. Caso o projeto passe a aceitar colaboração ou reutilização, será escolhida e adicionada uma licença apropriada.

## Créditos

Informações de filmes, capas e elencos podem ser obtidas de serviços de terceiros, incluindo [OMDb](https://www.omdbapi.com/) e [TMDb](https://www.themoviedb.org/). Respeite os termos de uso, atribuições e licenças de cada serviço ao exibir informações ou imagens fornecidas por ele. O CineDuo não é afiliado ao IMDb, OMDb ou TMDb.
