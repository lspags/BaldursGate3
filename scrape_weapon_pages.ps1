param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'equipment'),
    [string[]]$PageKeys
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $OutputDirectory)) { New-Item -ItemType Directory -Path $OutputDirectory | Out-Null }

$pages = [ordered]@{
    daggers = 'Daggers'
    handaxes = 'Handaxes'
    javelins = 'Javelins'
    light_hammers = 'Light_Hammers'
    maces = 'Maces'
    sickles = 'Sickles'
    quarterstaves = 'Quarterstaves'
    spears = 'Spears'
    greatclubs = 'Greatclubs'
    flails = 'Flails'
    morningstars = 'Morningstars'
    rapiers = 'Rapiers'
    scimitars = 'Scimitars'
    shortswords = 'Shortswords'
    war_picks = 'War_Picks'
    battleaxes = 'Battleaxes'
    longswords = 'Longswords'
    tridents = 'Tridents'
    warhammers = 'Warhammers'
    glaives = 'Glaives'
    greataxes = 'Greataxes'
    greatswords = 'Greatswords'
    halberds = 'Halberds'
    mauls = 'Mauls'
    pikes = 'Pikes'
    hand_crossbows = 'Hand_Crossbows'
    heavy_crossbows = 'Heavy_Crossbows'
    light_crossbows = 'Light_Crossbows'
    longbows = 'Longbows'
    shortbows = 'Shortbows'
}

function ConvertFrom-HtmlText([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $text = $Value -replace '(?is)<!--.*?-->', ''
    $text = $text -replace '(?i)<br\s*/?>|</(?:li|dd|dt|p|div)>', '; '
    $text = $text -replace '(?is)<[^>]+>', ''
    $text = [System.Net.WebUtility]::HtmlDecode($text)
    $text = $text -replace '[\u00A0\u202F\u200B\u2060]', ' '
    $text = $text -replace '\s*\(\s*\)', ''
    $text = $text -replace '\s*;\s*(?:;\s*)+', '; '
    $text = $text -replace '\s+', ' '
    return $text.Trim(' ', ';')
}

$selectedPages = if ($PageKeys) {
    $pages.GetEnumerator() | Where-Object { $_.Key -in $PageKeys }
} else {
    $pages.GetEnumerator()
}

foreach ($entry in $selectedPages) {
    $sourceUrl = "https://bg3.wiki/wiki/$($entry.Value)"
    Write-Host "Fetching $sourceUrl"
    $html = (Invoke-WebRequest -UseBasicParsing -Uri $sourceUrl).Content

    $propertiesMatch = [regex]::Match($html, '(?is)id="Properties".*?<div class="bg3wiki-property-list">(.*?)<h3')
    $propertyCells = @([regex]::Matches($propertiesMatch.Groups[1].Value, '(?is)<dd[^>]*>(.*?)</dd>'))
    $sharedProperties = if ($propertyCells.Count -gt 1) {
        $propertyValues = $propertyCells | Select-Object -Skip 1 | ForEach-Object { ConvertFrom-HtmlText $_.Groups[1].Value } | Where-Object { $_ }
        $propertyValues -join '; '
    } else { '' }

    $actionMatch = [regex]::Match($html, '(?is)id="Actions".*?<dl>\s*<dt[^>]*>(.*?)</dt>')
    $sharedAction = ConvertFrom-HtmlText $actionMatch.Groups[1].Value
    $sharedAction = $sharedAction -replace '\s*\(Action\)$', ''

    $listHeading = [regex]::Match($html, '(?is)id="List_of_[^"]+"')
    if (-not $listHeading.Success) { throw "Could not find item list on $sourceUrl" }
    $afterHeading = $html.Substring($listHeading.Index)
    $tableMatch = [regex]::Match($afterHeading, '(?is)<table class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>')
    if (-not $tableMatch.Success) { throw "Could not find item table on $sourceUrl" }

    $records = foreach ($rowMatch in [regex]::Matches($tableMatch.Groups[1].Value, '(?is)<tr[^>]*>(.*?)</tr>')) {
        $cells = @([regex]::Matches($rowMatch.Groups[1].Value, '(?is)<td[^>]*>(.*?)</td>'))
        if ($cells.Count -ne 7) { continue }
        $values = @($cells | ForEach-Object { ConvertFrom-HtmlText $_.Groups[1].Value })
        if ([string]::IsNullOrWhiteSpace($values[0])) { continue }

        $weight = if ($values[4] -match '([0-9]+(?:\.[0-9]+)?)\s*kg') { $Matches[1] } else { $values[4] }
        $price = if ($values[5] -match '([0-9][0-9,]*)') { $Matches[1] -replace ',', '' } else { $values[5] }

        [pscustomobject][ordered]@{
            item = $values[0]
            enchantment = $values[1]
            damage = $values[2]
            damage_type = $values[3]
            weight_kg = $weight
            price_gp = $price
            shared_properties = $sharedProperties
            shared_action = $sharedAction
            special = $values[6]
            source_url = $sourceUrl
        }
    }

    if (@($records).Count -eq 0) { throw "No item rows extracted from $sourceUrl" }
    $outputPath = Join-Path $OutputDirectory "$($entry.Key).csv"
    $records | Export-Csv -LiteralPath $outputPath -NoTypeInformation -Encoding utf8
    Write-Host "Wrote $(@($records).Count) rows to $outputPath"
}
