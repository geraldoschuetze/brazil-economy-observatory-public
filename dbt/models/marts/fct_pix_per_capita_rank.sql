-- State ranking of PIX paid per inhabitant, latest complete month, LONG by
-- payer type (CPF/CNPJ) so the CPF/CNPJ filter slices the table and the map.
-- With no filter the charts SUM over both types (CPF + CNPJ per capita = total
-- per capita, since both divide by the same state population); a filter narrows
-- it to the chosen type. Column names are kept human-friendly for the table.
WITH ultimo AS (
    SELECT max(mes) AS mes
    FROM {{ ref('fct_pix_pessoa_mensal') }}
    WHERE mes < date_trunc('month', current_date)
)
SELECT estado                                          AS "Estado",
       uf_iso,
       sigla_regiao                                    AS "Região",
       tipo_pessoa,
       mes,
       vl_pago,
       qt_pago,
       populacao,
       round((vl_pago / nullif(populacao, 0))::numeric, 2) AS vl_pago_per_capita,
       round((vl_pago / nullif(qt_pago, 0))::numeric, 2)   AS ticket_medio
FROM {{ ref('fct_pix_pessoa_mensal') }}
WHERE estado_ibge > 0
  AND mes = (SELECT mes FROM ultimo)
ORDER BY vl_pago_per_capita DESC
