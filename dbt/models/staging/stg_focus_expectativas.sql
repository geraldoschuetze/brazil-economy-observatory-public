-- BACEN Focus survey expectations, conformed for the marts layer.
SELECT
    indicador,
    data,
    data_referencia,
    mediana,
    respondentes
FROM {{ source('raw', 'focus_expectativas') }}
