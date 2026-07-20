param(
    [string]$PageName = 'Amulets',
    [string]$OutputPath = (Join-Path (Join-Path $PSScriptRoot 'equipment') 'amulets.csv')
)

$ErrorActionPreference = 'Stop'
$outputDirectory = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDirectory)) { New-Item -ItemType Directory -Path $outputDirectory | Out-Null }
$sourceUrl = "https://bg3.wiki/wiki/$PageName"

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

Write-Host "Fetching $sourceUrl"
$html = (Invoke-WebRequest -UseBasicParsing -Uri $sourceUrl).Content
$listStart = [regex]::Match($html, '(?is)id="List_of_[^"]+"')
if (-not $listStart.Success) { throw "Could not locate equipment list on $sourceUrl" }
$listHtml = $html.Substring($listStart.Index)

$records = foreach ($section in [regex]::Matches(
    $listHtml,
    '(?is)<h3[^>]*>\s*<span[^>]*class="mw-headline"[^>]*>(.*?)</span>.*?</h3>\s*(<table.*?</table>)'
)) {
    $rarity = ConvertFrom-HtmlText $section.Groups[1].Value
    if ($rarity -eq 'Legacy content') { continue }

    foreach ($row in [regex]::Matches($section.Groups[2].Value, '(?is)<tr[^>]*>(.*?)</tr>')) {
        $cells = @([regex]::Matches($row.Groups[1].Value, '(?is)<td[^>]*>(.*?)</td>'))
        if ($cells.Count -ne 4) { continue }
        $values = @($cells | ForEach-Object { ConvertFrom-HtmlText $_.Groups[1].Value })
        if ([string]::IsNullOrWhiteSpace($values[0])) { continue }
        $price = if ($values[2] -match '([0-9][0-9,]*)') { $Matches[1] -replace ',', '' } else { $values[2] }

        [pscustomobject][ordered]@{
            rarity = $rarity
            item = $values[0]
            price_gp = $price
            special = $values[3]
            source_url = $sourceUrl
        }
    }
}

if (@($records).Count -eq 0) { throw "No equipment rows extracted from $sourceUrl" }
$records | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
Write-Host "Wrote $(@($records).Count) rows to $OutputPath"
