param([string]$OutputPath = (Join-Path $PSScriptRoot 'spells.csv'))

$ErrorActionPreference = 'Stop'
$baseUrl = 'https://bg3.wiki/wiki/'
$allSpellsUrl = $baseUrl + 'List_of_all_spells_(sortable)'
$descriptionCachePath = Join-Path $PSScriptRoot '.spell_description_cache.clixml'
$classPages = [ordered]@{
    'Bard' = 'List_of_Bard_spells'
    'Cleric' = 'List_of_Cleric_spells'
    'Druid' = 'List_of_Druid_spells'
    'Paladin' = 'List_of_Paladin_spells'
    'Ranger' = 'List_of_Ranger_spells'
    'Sorcerer' = 'List_of_Sorcerer_spells'
    'Warlock' = 'List_of_Warlock_spells'
    'Wizard' = 'List_of_Wizard_spells'
    'Arcane Trickster' = 'List_of_Arcane_Trickster_spells'
    'Eldritch Knight' = 'List_of_Eldritch_Knight_spells'
}
$schoolPages = [ordered]@{
    'Abjuration' = 'Abjuration'
    'Conjuration' = 'Conjuration'
    'Divination' = 'Divination'
    'Enchantment' = 'Enchantment_(school)'
    'Evocation' = 'Evocation'
    'Illusion' = 'Illusion'
    'Necromancy' = 'Necromancy'
    'Transmutation' = 'Transmutation'
}

function ConvertFrom-HtmlText([string]$Value) {
    $text = [regex]::Replace($Value, '(?is)<img\b[^>]*(?:alt|title)="([^"]*)"[^>]*>', ' $1 ')
    $text = $text -replace '(?is)<!--.*?-->|<br\s*/?>', ' ' -replace '(?is)<[^>]+>', ' '
    $text = [System.Net.WebUtility]::HtmlDecode($text)
    $text = ($text -replace '[\u00A0\u202F\u200B\u2060]', ' ' -replace '\S+\.png\b', ' ' -replace '\s+', ' ').Trim()
    foreach ($damageType in 'Acid','Bludgeoning','Cold','Fire','Force','Healing','Lightning','Necrotic','Piercing','Poison','Psychic','Radiant','Slashing','Thunder') {
        $text = $text -replace "\b$damageType\s+$damageType\b", $damageType
    }
    for ($pass = 0; $pass -lt 2; $pass++) {
        $text = [regex]::Replace($text, "\b([A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*)?)\s+\1\b", '$1', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    }
    $text = $text -replace '\s+([.,;:])', '$1'
    if ($text -match '^(.+?)\s+\1$') { $text = $Matches[1] }
    return $text
}

function Get-SpellName([string]$CellHtml) {
    $name = ConvertFrom-HtmlText ($CellHtml -replace '(?is)<img\b[^>]*>', '')
    return ($name -replace '\s*\(spell\)$', '').Trim()
}

function Get-SpellPageUrl([string]$CellHtml) {
    $link = [regex]::Match($CellHtml, '(?is)<a[^>]*href="([^"]+)"')
    if (-not $link.Success) { return '' }
    $href = [System.Net.WebUtility]::HtmlDecode($link.Groups[1].Value)
    if ($href -match '^https?://') { return $href }
    if ($href.StartsWith('/')) { return 'https://bg3.wiki' + $href }
    return $baseUrl + $href.TrimStart('.')
}

function Get-SpellDescription([string]$Html) {
    $heading = [regex]::Match($Html, '(?is)<h2[^>]*>.*?id="Description".*?</h2>')
    if (-not $heading.Success) { return '' }
    $start = $heading.Index + $heading.Length
    $nextHeading = [regex]::Match($Html.Substring($start), '(?is)<h2\b')
    $length = if ($nextHeading.Success) { $nextHeading.Index } else { [Math]::Min(8000, $Html.Length - $start) }
    $section = $Html.Substring($start, $length)
    $section = $section -replace '(?is)<div[^>]*class="[^"]*(?:mw-editsection|noprint)[^"]*"[^>]*>.*?</div>', ''
    return ConvertFrom-HtmlText $section
}

function Get-FirstSpellTable([string]$Html) {
    foreach ($table in [regex]::Matches($Html, '(?is)<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>')) {
        $firstRow = [regex]::Match($table.Groups[1].Value, '(?is)<tr[^>]*>(.*?)</tr>')
        $headers = @([regex]::Matches($firstRow.Groups[1].Value, '(?is)<th[^>]*>(.*?)</th>') | ForEach-Object { ConvertFrom-HtmlText $_.Groups[1].Value })
        if ($headers.Count -ge 2 -and $headers[0] -match '^Name$' -and $headers[1] -match '^Level$') { return $table.Groups[1].Value }
    }
    throw 'Spell table not found.'
}

function Get-SpellNamesFromPage([string]$Page) {
    $url = $baseUrl + $Page
    Write-Host "Fetching $url"
    $html = (Invoke-WebRequest -UseBasicParsing -Uri $url).Content
    $table = Get-FirstSpellTable $html
    $names = foreach ($row in [regex]::Matches($table, '(?is)<tr[^>]*>(.*?)</tr>') | Select-Object -Skip 1) {
        $cell = [regex]::Match($row.Groups[1].Value, '(?is)<(?:th|td)[^>]*>(.*?)</(?:th|td)>')
        if ($cell.Success) { Get-SpellName $cell.Groups[1].Value }
    }
    return @($names | Where-Object { $_ } | Sort-Object -Unique)
}

$classesBySpell = @{}
foreach ($entry in $classPages.GetEnumerator()) {
    foreach ($spell in Get-SpellNamesFromPage $entry.Value) {
        $key = $spell.ToLowerInvariant()
        if (-not $classesBySpell.ContainsKey($key)) { $classesBySpell[$key] = [System.Collections.Generic.List[string]]::new() }
        $classesBySpell[$key].Add($entry.Key)
    }
}

$schoolBySpell = @{}
foreach ($entry in $schoolPages.GetEnumerator()) {
    foreach ($spell in Get-SpellNamesFromPage $entry.Value) { $schoolBySpell[$spell.ToLowerInvariant()] = $entry.Key }
}

Write-Host "Fetching $allSpellsUrl"
$allHtml = (Invoke-WebRequest -UseBasicParsing -Uri $allSpellsUrl).Content
$allTable = Get-FirstSpellTable $allHtml
$records = foreach ($row in [regex]::Matches($allTable, '(?is)<tr[^>]*>(.*?)</tr>') | Select-Object -Skip 1) {
    $cells = @([regex]::Matches($row.Groups[1].Value, '(?is)<(?:th|td)[^>]*>(.*?)</(?:th|td)>'))
    if ($cells.Count -lt 7) { continue }
    $spell = Get-SpellName $cells[0].Groups[1].Value
    $level = ConvertFrom-HtmlText $cells[1].Groups[1].Value
    if (-not $spell -or $level -notmatch '^(C|[1-6])$') { continue }
    $key = $spell.ToLowerInvariant()
    $pageUrl = Get-SpellPageUrl $cells[0].Groups[1].Value
    [pscustomobject][ordered]@{
        spell = $spell
        level = $level
        school = if ($schoolBySpell.ContainsKey($key)) { $schoolBySpell[$key] } else { '' }
        classes = if ($classesBySpell.ContainsKey($key)) { ($classesBySpell[$key] | Sort-Object -Unique) -join '; ' } else { '' }
        cast_time = ConvertFrom-HtmlText $cells[$cells.Count - 5].Groups[1].Value
        duration = ConvertFrom-HtmlText $cells[$cells.Count - 4].Groups[1].Value
        range_area = ConvertFrom-HtmlText $cells[$cells.Count - 3].Groups[1].Value
        attack_save = ConvertFrom-HtmlText $cells[$cells.Count - 2].Groups[1].Value
        damage_effect = ConvertFrom-HtmlText $cells[$cells.Count - 1].Groups[1].Value
        description = ''
        source_url = $pageUrl
    }
}

$descriptionCache = if (Test-Path -LiteralPath $descriptionCachePath) { Import-Clixml -LiteralPath $descriptionCachePath } else { @{} }
if ($descriptionCache -isnot [hashtable]) {
    $rebuiltCache = @{}
    foreach ($property in $descriptionCache.PSObject.Properties) { $rebuiltCache[$property.Name] = [string]$property.Value }
    $descriptionCache = $rebuiltCache
}
$descriptionIndex = 0
foreach ($record in $records) {
    $descriptionIndex++
    if (-not $record.source_url) { continue }
    if (-not $descriptionCache.ContainsKey($record.source_url)) {
        if ($descriptionIndex % 20 -eq 1) { Write-Host "Fetching spell descriptions: $descriptionIndex / $($records.Count)" }
        $spellHtml = (Invoke-WebRequest -UseBasicParsing -Uri $record.source_url).Content
        $descriptionCache[$record.source_url] = Get-SpellDescription $spellHtml
    }
    $record.description = ConvertFrom-HtmlText ([System.Net.WebUtility]::HtmlEncode([string]$descriptionCache[$record.source_url]))
}
$descriptionCache | Export-Clixml -LiteralPath $descriptionCachePath

$records | Sort-Object @{Expression={if($_.level -eq 'C'){0}else{[int]$_.level}}},spell -Unique |
    Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
Write-Host "Wrote $(@($records).Count) spells to $OutputPath"
