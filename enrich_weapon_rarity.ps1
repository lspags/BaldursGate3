param([string]$EquipmentDirectory = (Join-Path $PSScriptRoot 'equipment'))

$ErrorActionPreference = 'Stop'
$nonWeapons = @('amulets.csv','armour.csv','cloaks.csv','clothing.csv','footwear.csv','handwear.csv','headwear.csv','light_sources.csv','rings.csv','shields.csv')
$rarityNames = @{
    'common' = 'Common'; 'uncommon' = 'Uncommon'; 'rare' = 'Rare'
    'very-rare' = 'Very Rare'; 'legendary' = 'Legendary'; 'story' = 'Story Item'
}

Get-ChildItem -LiteralPath $EquipmentDirectory -Filter '*.csv' | Where-Object { $_.Name -notin $nonWeapons } | ForEach-Object {
    $path = $_.FullName
    $records = @(Import-Csv -LiteralPath $path)
    if (-not $records.Count) { return }
    $sourceUrl = $records[0].source_url
    Write-Host "Fetching $sourceUrl"
    $html = (Invoke-WebRequest -UseBasicParsing -Uri $sourceUrl).Content
    $heading = [regex]::Match($html, '(?is)id="List_of_[^"]+"')
    if (-not $heading.Success) { throw "Item list not found: $sourceUrl" }
    $table = [regex]::Match($html.Substring($heading.Index), '(?is)<table class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>')
    if (-not $table.Success) { throw "Item table not found: $sourceUrl" }

    $rarities = @{}
    foreach ($row in [regex]::Matches($table.Groups[1].Value, '(?is)<tr[^>]*>(.*?)</tr>')) {
        $cell = [regex]::Match($row.Groups[1].Value, '(?is)<td[^>]*>(.*?)</td>')
        if (-not $cell.Success) { continue }
        $rarityMatch = [regex]::Match($cell.Groups[1].Value, 'bg3wiki-itemicon-([a-z-]+)')
        $titleMatch = [regex]::Match($cell.Groups[1].Value, '(?is)<a[^>]+href="/wiki/[^"]+"[^>]+title="([^"]+)"')
        if (-not $titleMatch.Success) { continue }
        $item = [System.Net.WebUtility]::HtmlDecode($titleMatch.Groups[1].Value)
        $rarityKey = if ($rarityMatch.Success) { $rarityMatch.Groups[1].Value.ToLowerInvariant() } else { 'common' }
        $rarities[$item] = if ($rarityNames.ContainsKey($rarityKey)) { $rarityNames[$rarityKey] } else { 'Common' }
    }

    $output = foreach ($record in $records) {
        $ordered = [ordered]@{ item = $record.item; rarity = $(if ($rarities.ContainsKey($record.item)) { $rarities[$record.item] } else { 'Common' }) }
        foreach ($property in $record.PSObject.Properties) {
            if ($property.Name -notin @('item','rarity')) { $ordered[$property.Name] = $property.Value }
        }
        [pscustomobject]$ordered
    }
    $output | Export-Csv -LiteralPath $path -NoTypeInformation -Encoding utf8
    Write-Host "Updated $($_.Name): $($rarities.Count) rarity entries"
}
