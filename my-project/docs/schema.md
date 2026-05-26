# Schema Documentation

## sources
Stores data source information.

## topics
Stores topic definitions.

## clusters
Stores grouped topic clusters.

## raw_signals
Stores unprocessed incoming signals.

## scores
Stores scoring output for raw signals.

## predictions
Stores predicted labels and confidence values.

## reports
Stores summary reporting data.

## ER Diagram

```mermaid
erDiagram
    SOURCES ||--o{ RAW_SIGNALS : has
    TOPICS ||--o{ CLUSTERS : contains
    RAW_SIGNALS ||--o{ SCORES : gets
    TOPICS ||--o{ SCORES : used_in
    CLUSTERS ||--o{ SCORES : grouped_in
    RAW_SIGNALS ||--o{ PREDICTIONS : receives
    TOPICS ||--o{ PREDICTIONS : used_in
    CLUSTERS ||--o{ PREDICTIONS : grouped_in
    TOPICS ||--o{ REPORTS : summarized_in
    CLUSTERS ||--o{ REPORTS : summarized_in

    
## 6) Run migrations on a clean DB

From the project root in PowerShell:

```powershell
Get-ChildItem .\db\migrations\*.sql | Sort-Object Name | ForEach-Object {
    Get-Content $_.FullName | docker exec -i my-project-db-1 psql -U myuser -d my_project_db
}