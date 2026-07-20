param(
    [string]$CsvDirectory = (Join-Path $PSScriptRoot 'equipment'),
    [int]$DelayMilliseconds = 150
)

$ErrorActionPreference = 'Stop'
$cachePath = Join-Path $PSScriptRoot '.where_to_find_cache.clixml'
$cache = if (Test-Path -LiteralPath $cachePath) { Import-Clixml -LiteralPath $cachePath } else { @{} }

function ConvertFrom-HtmlText([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $text = $Value -replace '(?is)<!--.*?-->', ''
    $text = $text -replace '(?i)<br\s*/?>|</(?:li|dd|dt|p|div|h3|h4)>', '; '
    $text = $text -replace '(?is)<[^>]+>', ''
    $text = [System.Net.WebUtility]::HtmlDecode($text)
    $text = $text -replace '[\u00A0\u202F\u200B\u2060]', ' '
    $text = $text -replace '\s*;\s*(?:;\s*)+', '; '
    $text = $text -replace '\s+', ' '
    return $text.Trim(' ', ';')
}

function Get-WhereToFind([string]$ItemName) {
    if ($cache.ContainsKey($ItemName)) { return [string]$cache[$ItemName] }

    $pageTitle = $ItemName -replace ' ', '_'
    $itemUrl = 'https://bg3.wiki/wiki/' + [uri]::EscapeDataString($pageTitle).Replace('%2F', '/')
    $whereToFind = ''
    try {
        $html = (Invoke-WebRequest -UseBasicParsing -Uri $itemUrl).Content
        $section = [regex]::Match(
            $html,
            '(?is)<h2[^>]*>\s*<span[^>]*id="Where_to_find"[^>]*>.*?</h2>(.*?)(?=<h2\b|<div[^>]+class="printfooter"|<div[^>]+id="catlinks")'
        )
        if ($section.Success) { $whereToFind = ConvertFrom-HtmlText $section.Groups[1].Value }
    } catch {
        Write-Warning "Failed to fetch $ItemName at $itemUrl : $($_.Exception.Message)"
    }

    $cache[$ItemName] = $whereToFind
    Start-Sleep -Milliseconds $DelayMilliseconds
    return $whereToFind
}

$csvFiles = Get-ChildItem -LiteralPath $CsvDirectory -Filter '*.csv' | Sort-Object Name
$fetchCount = 0
foreach ($csvFile in $csvFiles) {
    $rows = @(Import-Csv -LiteralPath $csvFile.FullName)
    if ($rows.Count -eq 0 -or -not $rows[0].PSObject.Properties['source_url']) { continue }

    Write-Host "Enriching $($csvFile.Name) ($($rows.Count) items)"
    $enrichedRows = foreach ($row in $rows) {
        $existingLocation = if ($row.PSObject.Properties['where_to_find']) { [string]$row.where_to_find } else { '' }
        if (-not [string]::IsNullOrWhiteSpace($existingLocation)) {
            $location = $existingLocation
            $cache[$row.item] = $location
            $wasCached = $true
        } else {
            $wasCached = $cache.ContainsKey($row.item)
            $location = Get-WhereToFind $row.item
        }
        if (-not $wasCached) {
            $fetchCount++
            if (($fetchCount % 20) -eq 0) { $cache | Export-Clixml -LiteralPath $cachePath }
        }

        $output = [ordered]@{}
        foreach ($property in $row.PSObject.Properties) {
            if ($property.Name -notin @('where_to_find', 'source_url')) {
                $output[$property.Name] = $property.Value
            }
        }
        $output['where_to_find'] = $location
        if ($row.PSObject.Properties['source_url']) { $output['source_url'] = $row.source_url }
        [pscustomobject]$output
    }

    $enrichedRows | Export-Csv -LiteralPath $csvFile.FullName -NoTypeInformation -Encoding utf8
}

$cache | Export-Clixml -LiteralPath $cachePath
Write-Host "Finished. Fetched $fetchCount unique item pages; cache now contains $($cache.Count) items."
