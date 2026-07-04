$python = "D:\Users\advoc\AppData\Local\Programs\Python\Python314\python.exe"
$claude = "C:\Users\advoc\AppData\Roaming\npm\claude.ps1"
$root   = "D:\YandexDisk\Zerocoder\ClaudeCode\Radar"
$date   = Get-Date -Format "yyyy-MM-dd"

Set-Location $root

# Шаг 1: сбор и классификация постов
& $python "$root\scripts\fetch-posts.py"
if (-not $?) { exit 1 }

& $python "$root\scripts\filter-signals.py"
if (-not $?) { exit 1 }

# Шаг 2: обновить state.json (без публикации)
& $python "$root\agents\digest-agent.py"
if (-not $?) { exit 1 }

# Шаг 3: мультиагентный анализ через Claude — перезаписывает дайджест и публикует в Telegram
& $claude -p "/run-analysis $date"
