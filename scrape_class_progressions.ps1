param(
    [string[]]$Classes = @('Bard','Cleric','Druid','Fighter','Monk','Paladin','Ranger','Rogue','Sorcerer','Warlock','Wizard')
)

$ErrorActionPreference = 'Stop'
$classDirectory = Join-Path $PSScriptRoot 'classes'
$classCatalog = Import-Csv (Join-Path $classDirectory 'classes.csv')

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

function ConvertTo-SnakeCase([string]$Value) {
    $name = $Value.ToLowerInvariant() -replace '[^a-z0-9]+', '_'
    return $name.Trim('_')
}

function Get-HtmlGrid([string]$TableBody) {
    $rowMatches = @([regex]::Matches($TableBody, '(?is)<tr[^>]*>(.*?)</tr>'))
    $maxColumns = 0
    foreach ($row in $rowMatches) {
        $width = 0
        foreach ($cell in [regex]::Matches($row.Groups[1].Value, '(?is)<(th|td)([^>]*)>(.*?)</\1>')) {
            $attributes = $cell.Groups[2].Value
            $width += if ($attributes -match 'colspan\s*=\s*["'']?([0-9]+)') { [int]$Matches[1] } else { 1 }
        }
        if ($width -gt $maxColumns) { $maxColumns = $width }
    }

    $activeSpans = @{}
    $result = [System.Collections.Generic.List[object]]::new()
    foreach ($row in $rowMatches) {
        $grid = New-Object 'object[]' $maxColumns
        foreach ($key in @($activeSpans.Keys)) {
            $column = [int]$key
            $grid[$column] = $activeSpans[$key].Value
            $activeSpans[$key].Remaining--
            if ($activeSpans[$key].Remaining -le 0) { $activeSpans.Remove($key) }
        }

        $columnIndex = 0
        foreach ($cell in [regex]::Matches($row.Groups[1].Value, '(?is)<(th|td)([^>]*)>(.*?)</\1>')) {
            while ($columnIndex -lt $maxColumns -and $null -ne $grid[$columnIndex]) { $columnIndex++ }
            if ($columnIndex -ge $maxColumns) { break }
            $attributes = $cell.Groups[2].Value
            $value = ConvertFrom-HtmlText $cell.Groups[3].Value
            $rowspan = if ($attributes -match 'rowspan\s*=\s*["'']?([0-9]+)') { [int]$Matches[1] } else { 1 }
            $colspan = if ($attributes -match 'colspan\s*=\s*["'']?([0-9]+)') { [int]$Matches[1] } else { 1 }
            for ($offset = 0; $offset -lt $colspan -and ($columnIndex + $offset) -lt $maxColumns; $offset++) {
                $target = $columnIndex + $offset
                $grid[$target] = $value
                if ($rowspan -gt 1) {
                    $activeSpans[$target] = [pscustomobject]@{ Value = $value; Remaining = $rowspan - 1 }
                }
            }
            $columnIndex += $colspan
        }
        $result.Add($grid)
    }
    return $result.ToArray()
}

function Get-ColumnName([string[]]$Parts, [int]$Index) {
    $useful = @($Parts | Where-Object {
        $_ -and $_ -notmatch '(?i)class progression$|spell slots per spell level'
    } | Select-Object -Unique)
    $label = if ($useful.Count) { $useful -join ' ' } else { "column $($Index + 1)" }
    if ($label -match '^(1st|2nd|3rd|[4-9]th)$') {
        return 'spell_slots_' + ([regex]::Match($label, '\d+').Value)
    }
    return ConvertTo-SnakeCase $label
}

foreach ($className in $Classes) {
    $catalogRow = $classCatalog | Where-Object { $_.class -eq $className } | Select-Object -First 1
    if ($null -eq $catalogRow) { throw "Class '$className' was not found in classes.csv." }
    $subclasses = @($catalogRow.subclasses -split '; ')
    $subclassColumns = @{}
    foreach ($subclass in $subclasses) { $subclassColumns[$subclass] = ConvertTo-SnakeCase $subclass }

    $sourceUrl = "https://bg3.wiki/wiki/$className"
    Write-Host "Fetching $sourceUrl"
    $html = (Invoke-WebRequest -UseBasicParsing -Uri $sourceUrl).Content
    $tables = @([regex]::Matches($html, '(?is)<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>'))
    if ($tables.Count -eq 0) { throw "No progression table found for $className." }

    $progression = @(Get-HtmlGrid $tables[0].Groups[1].Value)
    $firstDataRow = -1
    for ($rowIndex = 0; $rowIndex -lt $progression.Count; $rowIndex++) {
        if ([string]$progression[$rowIndex][0] -match '^\s*([0-9]+)(?:st|nd|rd|th)?\s*$') {
            $firstDataRow = $rowIndex
            break
        }
    }
    if ($firstDataRow -lt 1) { throw "Could not identify progression rows for $className." }

    $columnNames = [System.Collections.Generic.List[string]]::new()
    for ($column = 0; $column -lt $progression[0].Count; $column++) {
        $parts = for ($headerRow = 0; $headerRow -lt $firstDataRow; $headerRow++) { [string]$progression[$headerRow][$column] }
        $candidate = Get-ColumnName $parts $column
        $baseCandidate = $candidate
        $suffix = 2
        while ($columnNames.Contains($candidate)) { $candidate = "${baseCandidate}_$suffix"; $suffix++ }
        $columnNames.Add($candidate)
    }
    $columnNames[0] = 'level'
    if ($columnNames.Count -gt 2) { $columnNames[2] = 'class_features' }

    $levelSubclassFeatures = @{}
    foreach ($level in 1..12) {
        $levelSubclassFeatures[$level] = @{}
        foreach ($subclass in $subclasses) { $levelSubclassFeatures[$level][$subclass] = '' }
    }

    foreach ($table in $tables | Select-Object -Skip 1) {
        $prefix = $html.Substring(0, $table.Index)
        $levelHeadings = @([regex]::Matches($prefix, '(?is)<h3[^>]*>.*?Level\s+([0-9]+).*?</h3>'))
        if ($levelHeadings.Count -eq 0) { continue }
        $level = [int]$levelHeadings[-1].Groups[1].Value
        if ($level -lt 1 -or $level -gt 12) { continue }

        $grid = @(Get-HtmlGrid $table.Groups[1].Value)
        $activeHeaders = @()
        foreach ($gridRow in $grid) {
            $values = @($gridRow | ForEach-Object { [string]$_ })
            $recognized = @($values | Where-Object { $_ -in $subclasses })
            if ($recognized.Count -gt 0) {
                $activeHeaders = $values
                continue
            }
            if ($activeHeaders.Count -eq 0) { continue }
            for ($i = 0; $i -lt [Math]::Min($activeHeaders.Count, $values.Count); $i++) {
                $subclass = $activeHeaders[$i]
                $value = $values[$i]
                if ($subclass -notin $subclasses -or -not $value -or $value -eq '(none)') { continue }
                $existing = [string]$levelSubclassFeatures[$level][$subclass]
                if (-not $existing) { $levelSubclassFeatures[$level][$subclass] = $value }
                elseif ($existing -ne $value) { $levelSubclassFeatures[$level][$subclass] = "$existing; $value" }
            }
            $activeHeaders = @()
        }
    }

    $records = foreach ($gridRow in $progression | Select-Object -Skip $firstDataRow) {
        $levelText = [string]$gridRow[0]
        if ($levelText -notmatch '([0-9]+)') { continue }
        $level = [int]$Matches[1]
        $record = [ordered]@{}
        for ($column = 0; $column -lt $columnNames.Count; $column++) {
            $value = [string]$gridRow[$column]
            if ($column -eq 0) { $value = [string]$level }
            $record[$columnNames[$column]] = $value
        }
        foreach ($subclass in $subclasses) {
            $record[$subclassColumns[$subclass]] = [string]$levelSubclassFeatures[$level][$subclass]
        }
        $record['source_url'] = $sourceUrl
        [pscustomobject]$record
    }

    if (@($records).Count -ne 12) { throw "$className produced $(@($records).Count) rows instead of 12." }
    $outputPath = Join-Path $classDirectory ((ConvertTo-SnakeCase $className) + '.csv')
    $records | Export-Csv -LiteralPath $outputPath -NoTypeInformation -Encoding utf8
    Write-Host "Wrote 12 rows to $outputPath"
}
