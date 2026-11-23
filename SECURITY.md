# Segurança e privacidade

## Antes de tornar o repositório público

- **Não inclua `app_data/`**: ela guarda `cineduo.sqlite3`, capas em cache, backups e possivelmente chaves de API.
- Nunca publique `.env`, capturas de tela que mostrem chaves, arquivos de backup e exportações do ranking pessoal.
- O `.gitignore` impede a adição acidental de muitos desses arquivos, mas **não substitui a revisão do `git status` antes de cada commit**.
- Se você já mostrou uma chave/token em uma captura de tela compartilhada, gere outra credencial no serviço e substitua a antiga no aplicativo.
- Não execute o modo `--network` em redes públicas e não abra a porta 8765 no roteador para acesso pela internet.

## Limitação atual de segurança

Este projeto usa um servidor HTTP local, sem autenticação. A opção de rede local `--network` permite acesso de outros dispositivos na mesma rede. **Não é adequado expor esse servidor diretamente na internet**.

Para hospedar o CineDuo de forma pública ou com acesso remoto privado, o projeto precisa de autenticação, autorização, proteção de rotas, estratégia de armazenamento segura e revisão de segurança.

## Caso uma credencial seja incluída em um commit público

**Revogue/regenere a chave imediatamente.** Apagar o arquivo do último commit não remove a credencial do histórico Git. Siga a documentação oficial: https://docs.github.com/pt/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
