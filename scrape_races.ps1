param([string]$OutputPath = (Join-Path $PSScriptRoot 'races.csv'))

$ErrorActionPreference = 'Stop'
$sourceUrl = 'https://bg3.wiki/wiki/Races'

function ConvertFrom-HtmlText([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $text = $Value -replace '(?is)<!--.*?-->', ''
    $text = $text -replace '(?i)<br\s*/?>|</(?:li|dd|dt|p|div)>', '; '
    $text = $text -replace '(?is)<[^>]+>', ''
    $text = [System.Net.WebUtility]::HtmlDecode($text)
    $text = $text -replace '[\u00A0\u202F\u200B\u2060]', ' '
    $text = $text -replace '\s*;\s*(?:;\s*)+', '; '
    $text = $text -replace '\s+', ' '
    return $text.Trim(' ', ';')
}

Write-Host "Fetching $sourceUrl"
$html = (Invoke-WebRequest -UseBasicParsing -Uri $sourceUrl).Content
$table = [regex]::Match($html, '(?is)<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>')
if (-not $table.Success) { throw 'Playable races table was not found.' }

$activeSpans = @{}
$gridRows = @()
foreach ($rowMatch in [regex]::Matches($table.Groups[1].Value, '(?is)<tr[^>]*>(.*?)</tr>')) {
    $grid = New-Object 'object[]' 7

    foreach ($key in @($activeSpans.Keys)) {
        $column = [int]$key
        $grid[$column] = $activeSpans[$key].Value
        $activeSpans[$key].Remaining--
        if ($activeSpans[$key].Remaining -le 0) { $activeSpans.Remove($key) }
    }

    $columnIndex = 0
    foreach ($cell in [regex]::Matches($rowMatch.Groups[1].Value, '(?is)<(th|td)([^>]*)>(.*?)</\1>')) {
        while ($columnIndex -lt $grid.Count -and $null -ne $grid[$columnIndex]) { $columnIndex++ }
        if ($columnIndex -ge $grid.Count) { break }

        $attributes = $cell.Groups[2].Value
        $value = ConvertFrom-HtmlText $cell.Groups[3].Value
        $rowspan = if ($attributes -match 'rowspan\s*=\s*["'']?([0-9]+)') { [int]$Matches[1] } else { 1 }
        $colspan = if ($attributes -match 'colspan\s*=\s*["'']?([0-9]+)') { [int]$Matches[1] } else { 1 }

        for ($offset = 0; $offset -lt $colspan -and ($columnIndex + $offset) -lt $grid.Count; $offset++) {
            $targetColumn = $columnIndex + $offset
            $grid[$targetColumn] = $value
            if ($rowspan -gt 1) {
                $activeSpans[$targetColumn] = [pscustomobject]@{ Value = $value; Remaining = $rowspan - 1 }
            }
        }
        $columnIndex += $colspan
    }
    $gridRows += ,$grid
}

# The table has two header rows; the remaining rows are playable race variants.
$records = foreach ($grid in $gridRows | Select-Object -Skip 2) {
    if ([string]::IsNullOrWhiteSpace([string]$grid[0])) { continue }
    $race = [string]$grid[0]
    $subrace = [string]$grid[1]
    if ($subrace -eq $race) { $subrace = '' }
    $baseSpeed = ([string]$grid[2]) -replace '^(Standard|Fast|Slow)\s*(?=[0-9])', '$1; '

    [pscustomobject][ordered]@{
        race = $race
        subrace = $subrace
        base_speed = $baseSpeed
        race_proficiencies = [string]$grid[3]
        subrace_proficiencies = [string]$grid[4]
        race_features = [string]$grid[5]
        subrace_features = [string]$grid[6]
        source_url = $sourceUrl
    }
}

if (@($records).Count -eq 0) { throw 'No playable race rows were extracted.' }
$records | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
Write-Host "Wrote $(@($records).Count) rows to $OutputPath"
