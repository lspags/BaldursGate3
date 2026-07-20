param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'equipment'))

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $OutputDirectory)) { New-Item -ItemType Directory -Path $OutputDirectory | Out-Null }
$pages = [ordered]@{
    shields = 'Shields'
    rings = 'Rings'
    light_sources = 'Light_Sources'
    headwear = 'Headwear'
    handwear = 'Handwear'
    footwear = 'Footwear'
    clothing = 'Clothing'
    cloaks = 'Cloaks'
    armour = 'Armour'
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

function Get-SectionName([string]$Html, [int]$TableIndex) {
    $prefix = $Html.Substring(0, $TableIndex)
    $headings = @([regex]::Matches($prefix, '(?is)<h[23][^>]*>.*?<span[^>]*class="mw-headline"[^>]*>(.*?)</span>.*?</h[23]>'))
    if ($headings.Count -eq 0) { return '' }
    return ConvertFrom-HtmlText $headings[-1].Groups[1].Value
}

function Get-Rarity([string]$ItemCellHtml, [string]$Section) {
    if ($Section -in @('Common','Uncommon','Rare','Very rare','Legendary','Story Item')) { return $Section }
    $match = [regex]::Match($ItemCellHtml, 'bg3wiki-itemicon-(common|uncommon|rare|very-rare|legendary|story)')
    if (-not $match.Success) { return '' }
    return (Get-Culture).TextInfo.ToTitleCase(($match.Groups[1].Value -replace '-', ' '))
}

foreach ($entry in $pages.GetEnumerator()) {
    $sourceUrl = "https://bg3.wiki/wiki/$($entry.Value)"
    Write-Host "Fetching $sourceUrl"
    $html = (Invoke-WebRequest -UseBasicParsing -Uri $sourceUrl).Content
    $records = @()

    foreach ($table in [regex]::Matches($html, '(?is)<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>')) {
        $headers = @([regex]::Matches($table.Groups[1].Value, '(?is)<th[^>]*>(.*?)</th>') | ForEach-Object { (ConvertFrom-HtmlText $_.Groups[1].Value) -replace '\s*;\s*', ' ' })
        if ($headers.Count -eq 0 -or $headers[0] -ne 'Item') { continue }
        $section = Get-SectionName $html $table.Index

        foreach ($row in [regex]::Matches($table.Groups[1].Value, '(?is)<tr[^>]*>(.*?)</tr>')) {
            $cells = @([regex]::Matches($row.Groups[1].Value, '(?is)<td[^>]*>(.*?)</td>'))
            if ($cells.Count -ne $headers.Count) { continue }
            $values = @($cells | ForEach-Object { ConvertFrom-HtmlText $_.Groups[1].Value })
            if ([string]::IsNullOrWhiteSpace($values[0])) { continue }
            $data = @{}
            for ($i = 0; $i -lt $headers.Count; $i++) { $data[$headers[$i]] = $values[$i] }

            $armourType = ''
            if ($entry.Key -eq 'armour' -and $section -match 'List of (light|medium|heavy) armour') {
                $armourType = (Get-Culture).TextInfo.ToTitleCase($Matches[1])
            } elseif ($entry.Key -in @('headwear','handwear','footwear') -and $section -in @('Non-Armour','Light','Medium','Heavy')) {
                $armourType = $section
            }
            $proficiency = if ($entry.Key -eq 'shields') { 'Shields' } elseif ($armourType -in @('Light','Medium','Heavy')) { "$armourType Armour" } else { 'None' }
            $weight = if ($data['Weight'] -match '([0-9]+(?:\.[0-9]+)?)\s*kg') { $Matches[1] } else { $data['Weight'] }
            $price = if ($data['Price'] -match '([0-9][0-9,]*)') { $Matches[1] -replace ',', '' } else { $data['Price'] }

            $records += [pscustomobject][ordered]@{
                rarity = Get-Rarity $cells[0].Groups[1].Value $section
                item = $data['Item']
                armour_type = $armourType
                proficiency = $proficiency
                armour_class = $data['Armour Class']
                stealth_disadvantage = $data['Stealth disadvantage']
                glow_emitted = $data['Glow Emitted']
                damage = $data['Damage']
                description = $data['Description']
                first_seen = $data['First Seen']
                weight_kg = $weight
                price_gp = $price
                special = $data['Special']
                where_to_find = $data['Where to find']
                source_url = $sourceUrl
            }
        }
    }

    if ($records.Count -eq 0) { throw "No equipment rows extracted from $sourceUrl" }
    $core = @('rarity','item')
    $optional = @('armour_type','proficiency','armour_class','stealth_disadvantage','glow_emitted','damage','description','first_seen','weight_kg','price_gp','special','where_to_find')
    $usedOptional = @($optional | Where-Object { $column = $_; @($records | Where-Object { -not [string]::IsNullOrWhiteSpace($_.$column) }).Count -gt 0 })
    $columns = @($core + $usedOptional + 'source_url')
    $outputPath = Join-Path $OutputDirectory "$($entry.Key).csv"
    $records | Select-Object $columns | Export-Csv -LiteralPath $outputPath -NoTypeInformation -Encoding utf8
    Write-Host "Wrote $($records.Count) rows to $outputPath [$($columns -join ', ')]"
}
