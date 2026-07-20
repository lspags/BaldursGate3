param([string]$OutputPath = (Join-Path $PSScriptRoot 'class_features.csv'))

$ErrorActionPreference = 'Stop'
$classDir = Join-Path $PSScriptRoot 'classes'
$ignored = '^(?:-|Feat|Choose |Subclass feature|New Spells|Gain |Select |Learn |Replacement Spell|Spells? Known|Improved Warlock Spell Slots|[0-9]+ )'
$titles = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($file in Get-ChildItem -LiteralPath $classDir -Filter '*.csv' | Where-Object { $_.Name -ne 'classes.csv' }) {
    foreach ($row in Import-Csv -LiteralPath $file.FullName) {
        foreach ($property in $row.PSObject.Properties) {
            if ($property.Name -in @('level','proficiency_bonus','source_url') -or $property.Name -match '^(?:spell_slots?|cantrips_known|spells_known|spells_learned|rage_|ki_|sneak_|martial_|unarmoured_|bardic_|sorcery_|invocations_|channel_|lay_on_)') { continue }
            foreach ($part in ([string]$property.Value -split ';')) {
                $title = ($part -replace '\s*\(\s*d\d+\s*\)', '' -replace '\s+', ' ').Trim(' ',':','*')
                if ($title -and $title -notmatch $ignored -and $title.Length -ge 3 -and $title.Length -le 80) { [void]$titles.Add($title) }
            }
        }
    }
}

$records = @()
$titleArray = @($titles | Sort-Object)
for ($offset = 0; $offset -lt $titleArray.Count; $offset += 40) {
    $batch = @($titleArray[$offset..([Math]::Min($offset + 39, $titleArray.Count - 1))])
    Write-Host "Fetching feature summaries: $($offset + 1) / $($titleArray.Count)"
    $joined = $batch -join '|'
    $uri = 'https://bg3.wiki/w/api.php?action=query&format=json&prop=extracts&exintro=1&explaintext=1&redirects=1&titles=' + [uri]::EscapeDataString($joined)
    $response = Invoke-RestMethod -Uri $uri
    foreach ($pageProperty in $response.query.pages.PSObject.Properties) {
        $page = $pageProperty.Value
        if ($page.missing -ne $null -or -not $page.extract) { continue }
        $description = ([string]$page.extract -replace '\s+', ' ').Trim()
        $records += [pscustomobject][ordered]@{
            feature = [string]$page.title
            description = $description
            source_url = 'https://bg3.wiki/wiki/' + ([uri]::EscapeDataString(([string]$page.title -replace ' ', '_')) -replace '%2F','/')
        }
    }
}

$knownBases = @($records | ForEach-Object { ($_.feature -replace '\s*\([^)]*\)$','').ToLowerInvariant() })
$missingTitles = @($titleArray | Where-Object {
    $base = ($_ -replace '\s*\([^)]*\)$','').ToLowerInvariant()
    $base -notin $knownBases -and $_ -notmatch '^(?:\+|\d|\dd\d|Black|Blue|Brass|Bronze|Copper|Gold|Green|Red|Silver|White|Martial weapons|Medium armour|Shields)$'
})
$searchIndex = 0
foreach ($title in $missingTitles) {
    $searchIndex++
    if ($searchIndex % 25 -eq 1) { Write-Host "Searching unmatched features: $searchIndex / $($missingTitles.Count)" }
    $searchUri = 'https://bg3.wiki/w/api.php?action=query&format=json&list=search&srnamespace=0&srlimit=8&srsearch=' + [uri]::EscapeDataString($title)
    $search = Invoke-RestMethod -Uri $searchUri
    $titleBase = ($title -replace '\s*\([^)]*\)$','').ToLowerInvariant()
    $match = @($search.query.search | Where-Object {
        $resultBase = ($_.title -replace '\s*\([^)]*\)$','').ToLowerInvariant()
        $resultBase -eq $titleBase -or $resultBase.StartsWith($titleBase + ':')
    } | Select-Object -First 1)
    if (-not $match) { continue }
    $extractUri = 'https://bg3.wiki/w/api.php?action=query&format=json&prop=extracts&exintro=1&explaintext=1&redirects=1&titles=' + [uri]::EscapeDataString($match[0].title)
    $extractResponse = Invoke-RestMethod -Uri $extractUri
    $page = @($extractResponse.query.pages.PSObject.Properties | ForEach-Object Value | Where-Object { $_.extract } | Select-Object -First 1)
    if (-not $page) { continue }
    $records += [pscustomobject][ordered]@{
        feature = $title
        description = (([string]$page[0].extract -replace '\s+', ' ').Trim())
        source_url = 'https://bg3.wiki/wiki/' + ([uri]::EscapeDataString(([string]$page[0].title -replace ' ', '_')) -replace '%2F','/')
    }
}

$records | Sort-Object feature -Unique | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
Write-Host "Wrote $($records.Count) feature descriptions to $OutputPath"
