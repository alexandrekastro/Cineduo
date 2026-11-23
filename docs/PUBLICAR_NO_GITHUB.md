# Publicar o CineDuo no GitHub (Windows)

## 1. Segurança antes de começar

Use **esta pasta preparada para publicação**, e não a pasta do CineDuo em que vocês já usam o ranking. Ela não inclui `app_data/`, que guarda os dados pessoais e as chaves de API. Nunca compartilhe sua chave da OMDb/TMDb ou imagens com chaves visíveis.

## 2. Criar o repositório no GitHub

1. Entre em https://github.com/new.
2. Em **Repository name**, digite `CineDuo`.
3. Escolha **Public**.
4. Opcionalmente, use a descrição: `Ranking pessoal de filmes, séries e sagas em Python`.
5. **Não marque 'Add a README', '.gitignore' ou 'Choose a license'**: esses arquivos já foram preparados (a licença será decidida mais tarde).
6. Clique em **Create repository**.

## 3. Publicar pelo Git (PowerShell)

Abra o PowerShell na pasta que contém `app.py` e `README.md` (a pasta interna `CineDuo`). Execute os comandos abaixo **um por vez**:

```powershell
git init -b main
git add .
git status
git commit -m "docs: publicacao inicial do CineDuo"
git remote add origin https://github.com/SEU_USUARIO/CineDuo.git
git push -u origin main
```

Substitua `SEU_USUARIO` pelo nome de usuário da sua conta GitHub. Caso o `git commit` solicite nome e e-mail, configure com `git config --global user.name "Seu Nome"` e `git config --global user.email "email-da-sua-conta"`. O Git Credential Manager poderá pedir que você faça login no navegador para autorizar o push.

**Antes de confirmar o `git commit`**, confira a lista do `git status`: `app_data/`, arquivos `.db`/`.sqlite3`, backups e qualquer chave não podem aparecer. Em caso de dúvida, não dê o push.

## 4. Nas próximas alterações

Na mesma pasta:

```powershell
git status
git add .
git commit -m "feat: descreva a melhoria"
git push
```

Use mensagens `fix:` para correções e `docs:` para documentação. Para alterações grandes, crie uma branch, por exemplo `git switch -c feat/series`, e depois abra um Pull Request.

## 5. Não confundir GitHub e hospedagem

Um repositório público permite compartilhar o código, mas o CineDuo **continua local**. Não hospede o servidor atual diretamente na internet: ele não possui login nem proteção adequada para exposição pública.

Fonte oficial: https://docs.github.com/pt/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github?platform=windows
