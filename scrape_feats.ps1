param([string]$OutputPath = (Join-Path $PSScriptRoot 'feats.csv'))

$ErrorActionPreference = 'Stop'
$sourceUrl = 'https://bg3.wiki/wiki/Feats'

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
if (-not $table.Success) { throw 'Feats table was not found.' }

$records = [System.Collections.Generic.List[object]]::new()
$currentName = ''
$currentParts = [System.Collections.Generic.List[string]]::new()

function Add-CurrentRecord {
    if ([string]::IsNullOrWhiteSpace($script:currentName)) { return }
    $parts = @($script:currentParts | Where-Object { $_ -and $_ -ne $script:currentName })
    $description = ($parts -join '; ') -replace '\s*;\s*(?:;\s*)+', '; '
    $script:records.Add([pscustomobject][ordered]@{
        feat = $script:currentName
        description = $description.Trim(' ', ';')
        source_url = $script:sourceUrl
    })
}

foreach ($row in [regex]::Matches($table.Groups[1].Value, '(?is)<tr[^>]*>(.*?)</tr>')) {
    $cells = @([regex]::Matches($row.Groups[1].Value, '(?is)<(th|td)([^>]*)>(.*?)</\1>'))
    if ($cells.Count -eq 0) { continue }

    $nameCell = $cells | Where-Object { $_.Groups[2].Value -match 'scope\s*=\s*["'']rowgroup["'']' } | Select-Object -First 1
    if ($null -ne $nameCell) {
        Add-CurrentRecord
        $currentName = ConvertFrom-HtmlText $nameCell.Groups[3].Value
        $currentParts = [System.Collections.Generic.List[string]]::new()
    }

    if ([string]::IsNullOrWhiteSpace($currentName)) { continue }
    foreach ($cell in $cells) {
        if ($null -ne $nameCell -and $cell.Index -eq $nameCell.Index) { continue }
        $value = ConvertFrom-HtmlText $cell.Groups[3].Value
        if ($value -and ($currentParts.Count -eq 0 -or $currentParts[$currentParts.Count - 1] -ne $value)) {
            $currentParts.Add($value)
        }
    }
}
Add-CurrentRecord

if ($records.Count -eq 0) { throw 'No feat rows were extracted.' }
$records | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
Write-Host "Wrote $($records.Count) rows to $OutputPath"
