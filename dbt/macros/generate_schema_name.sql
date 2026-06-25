{#
    Use the custom schema name verbatim (bare `staging` / `marts`) instead of
    dbt's default `<target_schema>_<custom>` concatenation. The warehouse schema
    layout is fixed and shared with the Airflow DAGs and Superset datasets, so
    the names must stay exactly `staging` and `marts`.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
