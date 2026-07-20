param([string]$CsvPath = (Join-Path (Join-Path $PSScriptRoot 'classes') 'classes.csv'))

$ErrorActionPreference = 'Stop'

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

function Get-Section([string]$Html, [string]$StartId, [string]$EndId) {
    $start = $Html.IndexOf("id=`"$StartId`"")
    if ($start -lt 0) { return '' }
    $end = if ($EndId) { $Html.IndexOf("id=`"$EndId`"", $start + $StartId.Length) } else { -1 }
    if ($end -lt 0) { $end = $Html.Length }
    return $Html.Substring($start, $end - $start)
}

function Get-Definition([string]$Section, [string]$LabelPattern) {
    foreach ($match in [regex]::Matches($Section, '(?is)<dt[^>]*>(.*?)</dt>(.*?)(?=<dt[^>]*>|</dl>)')) {
        $label = ConvertFrom-HtmlText $match.Groups[1].Value
        if ($label -notmatch $LabelPattern) { continue }
        $values = @([regex]::Matches($match.Groups[2].Value, '(?is)<dd[^>]*>(.*?)</dd>') | ForEach-Object {
            ConvertFrom-HtmlText $_.Groups[1].Value
        } | Where-Object { $_ })
        if ($values.Count -eq 0) {
            $fallback = ConvertFrom-HtmlText $match.Groups[2].Value
            if ($fallback) { $values = @($fallback) }
        }
        return $values
    }
    return @()
}

$records = Import-Csv -LiteralPath $CsvPath
$enriched = foreach ($record in $records) {
    $sourceUrl = "https://bg3.wiki/wiki/$($record.class)"
    Write-Host "Fetching $sourceUrl"
    $html = (Invoke-WebRequest -UseBasicParsing -Uri $sourceUrl).Content

    $attributes = Get-Section $html 'Attributes' 'Starting_Proficiencies'
    $starting = Get-Section $html 'Starting_Proficiencies' 'Multiclass_Proficiencies'
    $multiclass = Get-Section $html 'Multiclass_Proficiencies' 'Level_progression'

    $hitPoints = @(Get-Definition $attributes '^Hit points$')
    $keyAbilities = @(Get-Definition $attributes '^Key (?:Ability Scores|abilities)$')
    $spellcasting = @(Get-Definition $attributes '^Spellcasting Ability$')
    $savingThrows = @(Get-Definition $starting '^Saving Throw proficiencies$')
    $equipment = @(Get-Definition $starting '^Equipment proficiencies$')
    $skills = @(Get-Definition $starting '^(?:Skill proficiencies|Skills proficiencies|Skills with proficiency)(?:\s*\(Choose\s*([0-9]+)\))?$')
    $startingEquipment = @(Get-Definition $starting '^(?:Class )?Starting Equipment$')
    $multiclassEquipment = @(Get-Definition $multiclass '^Equipment proficiencies$')

    $skillLabelHtml = [regex]::Match($starting, '(?is)<dt[^>]*>(.*?(?:Skill proficiencies|Skills proficiencies|Skills with proficiency).*?)</dt>').Groups[1].Value
    $skillLabel = [regex]::Match((ConvertFrom-HtmlText $skillLabelHtml), 'Choose\s*([0-9]+)', 'IgnoreCase')
    $skillChoiceCount = if ($skillLabel.Success) { $skillLabel.Groups[1].Value } else { '' }

    [pscustomobject][ordered]@{
        class = $record.class
        description = $record.description
        subclasses = $record.subclasses
        hit_points_level_1 = if ($hitPoints.Count -ge 1) { $hitPoints[0] -replace '^At level 1:\s*', '' } else { '' }
        hit_points_per_level = if ($hitPoints.Count -ge 2) { $hitPoints[1] -replace '^On level up:\s*', '' } else { '' }
        key_abilities = $keyAbilities -join '; '
        spellcasting_ability = $spellcasting -join '; '
        saving_throw_proficiencies = $savingThrows -join '; '
        equipment_proficiencies = $equipment -join '; '
        skill_proficiency_choices = $skillChoiceCount
        skill_proficiencies = $skills -join '; '
        starting_equipment = $startingEquipment -join '; '
        multiclass_proficiencies = if ($multiclassEquipment.Count) { $multiclassEquipment -join '; ' } else { $record.multiclass_proficiencies }
        source_url = $sourceUrl
    }
}

$enriched | Export-Csv -LiteralPath $CsvPath -NoTypeInformation -Encoding utf8
Write-Host "Enriched $(@($enriched).Count) classes in $CsvPath"
