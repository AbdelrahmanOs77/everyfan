param([string]$Directory = "$PSScriptRoot/../../.venv/handoff/owner-d/delivery")
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$chapters = Get-Content (Join-Path $Directory 'chapters.json') -Raw | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice('Microsoft Zira Desktop')
    $synth.Rate = 2
    $index = 0
    foreach ($chapter in $chapters) {
        $audioPath = [System.IO.Path]::GetFullPath((Join-Path $Directory "voice-$index.wav"))
        $synth.SetOutputToWaveFile($audioPath)
        $synth.Speak([string]$chapter[2])
        $synth.SetOutputToNull()
        $index++
    }
} finally {
    $synth.Dispose()
}
Write-Output 'English narration generated locally; no Azure Speech or model call was used.'
