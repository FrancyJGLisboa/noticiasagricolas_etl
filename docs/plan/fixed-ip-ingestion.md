# Coleta com IP fixo

## Resultado

Executar o ETL diário por um único IP público liberado pelo Notícias Agrícolas.
Preservar os bloqueios de frescor e impedir publicação quando a coleta falhar.

## Restrições confirmadas

- O repositório `FrancyJGLisboa/noticiasagricolas_etl` é público e pertence a uma conta pessoal.
- O repositório não possui runner próprio cadastrado.
- O GitHub oferece IP fixo gerenciado somente para organizações elegíveis com GitHub Enterprise Cloud.
- O GitHub desaconselha runners persistentes em repositórios públicos.
- A solução não pode registrar tokens, chaves ou respostas protegidas no repositório público.

## Arquitetura recomendada

1. Criar uma VM Linux pequena com IP público reservado.
2. Registrar o runner em um repositório de controle privado, não no repositório público.
3. Permitir somente execução agendada e manual por proprietário.
4. Fazer checkout do ETL público em um commit identificado.
5. Gerar um token curto de GitHub App com acesso `Contents: write` somente ao ETL.
6. Executar `na-etl daily` e `na-etl validate-freshness`.
7. Publicar release e branch `data` somente após as duas validações.
8. Descartar o diretório de trabalho após cada execução.

## Controles de segurança

- O runner usa um usuário sem privilégios administrativos.
- A VM não contém chaves pessoais, arquivos locais ou acesso à rede doméstica.
- O firewall aceita somente SSH administrativo por endereço permitido.
- O runner recebe a etiqueta exclusiva `noticias-etl-fixed-ip`.
- Nenhum workflow de pull request pode solicitar essa etiqueta.
- O GitHub App não recebe acesso a Issues, Actions, Administration ou Secrets.
- Logs não mostram tokens, cabeçalhos de autorização ou conteúdo de segredos.
- A VM aplica atualizações de segurança e reinicia de forma controlada.

## Operação

- Horário: 19h BRT em dias úteis.
- Retentativa: uma vez após 30 minutos.
- Falha HTTP ou frescor insuficiente: código diferente de zero e nenhuma publicação.
- Alerta: registrar o run, o indicador e o código HTTP sem registrar credenciais.
- Feriado: informar `NA_ETL_EXPECTED_DATE` no disparo manual.

## Critérios de aceitação

- O IP observado pelo provedor é estável em duas execuções separadas.
- O Notícias Agrícolas confirma a liberação desse IP.
- Soja CBOT, milho CBOT e PTAX alcançam a data esperada.
- O branch `data` avança somente depois das validações.
- Uma simulação de HTTP 403 não altera release nem branch `data`.
- O runner não aceita trabalhos originados de pull requests.
- A rotação ou revogação da credencial não exige alterar o repositório público.

## Decisão necessária antes da implantação

Escolher o provedor da VM e aceitar o custo mensal.
Não criar infraestrutura até essa decisão.

## Solicitação de liberação do IP

Preencher somente depois que o provedor reservar o endereço público.
Não incluir token, chave, cabeçalho HTTP, cookie ou credencial na solicitação.

Dados necessários:

- IP público reservado: `<IP_FIXO>`
- Repositório público: `https://github.com/FrancyJGLisboa/noticiasagricolas_etl`
- Identificação do coletor: `noticiasagricolas-etl/1.0`
- Frequência: uma execução diária em dias úteis, com uma retentativa após 30 minutos
- Finalidade: atualização de séries de preços com citação visível do Notícias Agrícolas
- Contato técnico: `<EMAIL_DO_RESPONSAVEL>`

Texto sugerido:

> Solicitamos a liberação do IP `<IP_FIXO>` para o coletor do projeto
> `FrancyJGLisboa/noticiasagricolas_etl`. O coletor acessa as páginas públicas do
> Notícias Agrícolas uma vez por dia útil. Ele faz uma única retentativa após
> 30 minutos quando ocorre falha. O site e os arquivos derivados identificam o
> Notícias Agrícolas como fonte. O coletor usa o identificador
> `noticiasagricolas-etl/1.0`. Não solicitamos acesso autenticado nem alteração
> dos limites do site para outros endereços. Pedimos a confirmação da liberação
> e de qualquer limite técnico que devemos respeitar.

Registrar a confirmação recebida, o IP liberado e a data da liberação.
Não registrar dados pessoais além do contato responsável.

## Rollback

Desativar o workflow privado, revogar a instalação do GitHub App e remover a VM.
O workflow público permanece bloqueado por frescor e não publica dados antigos.
