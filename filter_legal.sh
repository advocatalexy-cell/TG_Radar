#!/bin/bash

# Legal keywords
LEGAL_KEYWORDS=("закон" "суд" "регулирование" "право" "ГК" "АПК" "ФЗ" "Минюст" "legaltech" "AI Act" "арбитраж" "практика" "договор")

# Channel mapping for URLs
declare -A CHANNEL_MAP=(
    ["allthingslegal"]="allthingslegal"
    ["gpt-for-lawyers"]="GPT_for_Lawyers"
    ["ai-skrepka"]="AI_Skrepka"
    ["legalmindai"]="LegalMindAI"
)

# Create filter JSON for jq
KEYWORDS_JSON=$(printf '"%s",' "${LEGAL_KEYWORDS[@]}" | sed 's/,$//')

# Extract legal signals using jq
find data/processed -name "2026-06-30-*-processed.json" -type f -print0 | while IFS= read -r -d '' file; do
    jq -r '
    .[] | 
    select(
        .classification.signal == true or
        (.classification.category | IN("legal", "law", "regulation")) or
        (.classification.keywords[]? | IN('"$KEYWORDS_JSON"'))
    ) |
    {
        id: .id,
        channel_id: .channel_id,
        date: .date,
        summary: .classification.summary,
        keywords: .classification.keywords,
        category: .classification.category,
        score: .classification.score,
        text: .text
    }
    ' "$file" 2>/dev/null
done
