# Diretrizes de Desenvolvimento e Workflow - Antigravity

## 1. Controle de Versão (Git & GitHub)
- **Regra de Push:** O usuário **SEMPRE** realiza o `git push` manualmente direto pelo seu próprio terminal / CMD do Windows.
- O agente **NÃO DEVE** tentar rodar `git push` automaticamente nem solicitar autorização para disparar push contra o repositório remoto.
- **Workflow Padrão do Agente:**
  1. Criar e editar os arquivos necessários.
  2. Adicionar as alterações (`git add ...`).
  3. Realizar o commit local com mensagens claras e semânticas (`git commit -m "tipo: mensagem"`).
  4. Informar ao usuário que as alterações foram commitadas localmente e fornecer o comando `git push origin main` para que ele execute no seu próprio terminal / CMD.
