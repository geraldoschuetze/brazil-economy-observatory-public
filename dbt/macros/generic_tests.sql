{#
    Project-local generic tests — no external packages required, so `dbt parse`
    and `dbt build` work offline without `dbt deps`.
#}

{# Fails for any row whose value is strictly negative (NULLs pass). #}
{% test non_negative(model, column_name) %}
SELECT {{ column_name }}
FROM {{ model }}
WHERE {{ column_name }} < 0
{% endtest %}

{# Fails for any value outside the inclusive [min_value, max_value] range. #}
{% test in_range(model, column_name, min_value, max_value) %}
SELECT {{ column_name }}
FROM {{ model }}
WHERE {{ column_name }} < {{ min_value }}
   OR {{ column_name }} > {{ max_value }}
{% endtest %}

{# Fails when the combination of the given columns is not unique across rows.
   Offline replacement for dbt_utils.unique_combination_of_columns: use on
   long-format marts where no single column is unique but a tuple is the grain.
   Quote mixed-case aliases in the list, e.g. ['"Estado"', 'tipo_pessoa']. #}
{% test unique_combination(model, combination_of_columns) %}
SELECT {{ combination_of_columns | join(', ') }}
FROM {{ model }}
GROUP BY {{ combination_of_columns | join(', ') }}
HAVING count(*) > 1
{% endtest %}
