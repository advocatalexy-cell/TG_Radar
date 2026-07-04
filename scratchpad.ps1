# Скрипт для обработки файлов и отбора правовых сигналов
$processedDir = "data/processed"
$legalKeywords = @("закон", "суд", "регулирование", "право", "ГК", "АПК", "ФЗ", "Минюст", "legaltech", "AI Act", "арбитраж", "практика", "договор")
$legalCategories = @("legal", "law", "regulation")

$allSignals = @()
$fileCount = 0

Get-ChildItem -Path $processedDir -Filter "2026-06-30-*-processed.json" | ForEach-Object {
    $fileCount++
    $json = Get-Content $_.FullName -Encoding UTF8 | ConvertFrom-Json
    
    if ($json -is [array]) {
        foreach ($item in $json) {
            $isLegal = $false
            
            # Check signal
            if ($item.classification.signal -eq $true) {
                $isLegal = $true
            }
            
            # Check category
            if ($item.classification.category -in $legalCategories) {
                $isLegal = $true
            }
            
            # Check keywords
            if ($item.classification.keywords) {
                foreach ($keyword in $item.classification.keywords) {
                    if ($keyword -in $legalKeywords) {
                        $isLegal = $true
                        break
                    }
                }
            }
            
            if ($isLegal) {
                $allSignals += @{
                    id = $item.id
                    channel_id = $item.channel_id
                    date = $item.date
                    summary = $item.classification.summary
                    keywords = $item.classification.keywords
                    category = $item.classification.category
                    score = $item.classification.score
                    text = $item.text
                }
            }
        }
    }
}

Write-Host "Files processed: $fileCount"
Write-Host "Legal signals found: $($allSignals.Count)"

# Export to JSON for further processing
$allSignals | ConvertTo-Json | Out-File "legal_signals.json" -Encoding UTF8
