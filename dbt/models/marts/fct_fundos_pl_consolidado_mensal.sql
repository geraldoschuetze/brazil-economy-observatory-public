-- Consolidated (net-of-fund-of-funds) industry net worth, month by month.
-- The daily CVM informe sums EVERY class's PL, double-counting the slice a
-- feeder holds in cotas of other funds. Here we subtract exactly that — the
-- value of cota holdings (CDA BLC_2) whose target fund is itself in the month's
-- PL universe — yielding an ANBIMA-comparable consolidated figure
-- (~R$10–11 tri vs the ~R$13 tri gross sum).
WITH pl AS (
    SELECT anomes,
           sum(vl_patrim_liq) AS pl_bruto,
           count(*)           AS n_fundos
    FROM {{ ref('stg_cvm_cda_pl') }}
    GROUP BY anomes
),
universe AS (
    SELECT DISTINCT anomes, cnpj_digits
    FROM {{ ref('stg_cvm_cda_pl') }}
),
cotas AS (
    -- only cotas pointing AT a fund that is itself in the universe double-count
    SELECT c.anomes, sum(c.vl_mercado) AS vl_cotas_universo
    FROM {{ ref('stg_cvm_cda_cotas') }} c
    JOIN universe u
      ON u.anomes = c.anomes
     AND u.cnpj_digits = c.cnpj_investido_digits
    GROUP BY c.anomes
)
SELECT to_date(pl.anomes::text, 'YYYYMM')                       AS mes,
       pl.anomes,
       round(pl.pl_bruto, 2)                                    AS pl_bruto,
       round(coalesce(c.vl_cotas_universo, 0), 2)               AS vl_cotas_universo,
       round(pl.pl_bruto - coalesce(c.vl_cotas_universo, 0), 2) AS pl_consolidado,
       pl.n_fundos
FROM pl
LEFT JOIN cotas c USING (anomes)
ORDER BY pl.anomes
