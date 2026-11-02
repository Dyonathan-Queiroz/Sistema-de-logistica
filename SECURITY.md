# Política de Segurança

## Reportando uma vulnerabilidade

Não abra uma issue pública. Use **Security → Report a vulnerability** neste repositório (relato privado do GitHub). Descreva o impacto e como reproduzir; respondo assim que possível.

## Boas práticas para quem executar o projeto

- Defina `SECRET_KEY` forte e fixa e use `COOKIE_SECURE=true` atrás de HTTPS.
- Nunca versione `.env`; use o `.env.example` como modelo.
- Defina `ADMIN_SENHA` forte no primeiro deploy e `BACKUP_OWNER` para liberar o backup.
- Mantenha as dependências atualizadas (`pip-audit -r requirements.txt`).
