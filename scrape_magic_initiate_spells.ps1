param([string]$OutputPath = (Join-Path $PSScriptRoot 'magic_initiate_spells.csv'))

$ErrorActionPreference = 'Stop'
$classes = 'Bard','Cleric','Druid','Sorcerer','Warlock','Wizard'

function ConvertFrom-HtmlText([string]$Value) {
    $text = $Value -replace '(?is)<!--.*?-->|<[^>]+>', ''
    $text = [System.Net.WebUtility]::HtmlDecode($text)
    return ($text -replace '[\u00A0\u202F\u200B\u2060]', ' ' -replace '\s+', ' ').Trim()
}

$records = foreach ($class in $classes) {
    $url = "https://bg3.wiki/wiki/List_of_${class}_spells"
    Write-Host "Fetching $url"
    $html = (Invoke-WebRequest -UseBasicParsing -Uri $url).Content
    $table = [regex]::Match($html, '(?is)<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>')
    if (-not $table.Success) { throw "Spell table not found for $class." }
    foreach ($row in [regex]::Matches($table.Groups[1].Value, '(?is)<tr[^>]*>(.*?)</tr>') | Select-Object -Skip 1) {
        $cells = @([regex]::Matches($row.Groups[1].Value, '(?is)<(?:th|td)[^>]*>(.*?)</(?:th|td)>'))
        if ($cells.Count -lt 2) { continue }
        $name = ConvertFrom-HtmlText $cells[0].Groups[1].Value
        $level = ConvertFrom-HtmlText $cells[1].Groups[1].Value
        if (-not $name -or $level -notin @('C','1')) { continue }
        [pscustomobject][ordered]@{ class = $class; spell = $name; level = $level; source_url = $url }
    }
}

$records | Sort-Object class,@{Expression={if($_.level -eq 'C'){0}else{1}}},spell -Unique |
    Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
Write-Host "Wrote $(@($records).Count) spell choices to $OutputPath"
