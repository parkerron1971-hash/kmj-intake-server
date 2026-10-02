param(
    [ValidateSet('both', 'chatgpt', 'claude')]
    [string]$Provider = 'both',
    [string]$StateDirectory = (Join-Path $env:LOCALAPPDATA 'Solutionist/ConnectedAI')
)

# Interactive local setup only. Provider-native sign-in owns all credentials.
$ErrorActionPreference = 'Stop'
$repoDirectory = Split-Path $PSScriptRoot -Parent
$providers = if ($Provider -eq 'both') { @('chatgpt', 'claude') } else { @($Provider) }
Push-Location $repoDirectory
try {
    foreach ($selectedProvider in $providers) {
        $nativePath = if ($selectedProvider -eq 'chatgpt') {
            Join-Path $env:LOCALAPPDATA 'Programs/OpenAI/Codex/bin/codex.exe'
        } else {
            Join-Path $env:APPDATA 'npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe'
        }
        $providerArguments = @('--provider', $selectedProvider, '--state-dir', $StateDirectory)
        if (Test-Path -LiteralPath $nativePath -PathType Leaf) {
            $providerArguments += @('--executable', $nativePath)
        }
        & python -m connected_agents check @providerArguments
        if ($LASTEXITCODE -ne 0) { throw "Install the official $selectedProvider native client first." }
        Write-Host "Complete $selectedProvider sign-in in the provider's own flow."
        & python -m connected_agents login @providerArguments
        if ($LASTEXITCODE -ne 0) { throw "$selectedProvider sign-in did not complete." }
        & python -m connected_agents status @providerArguments
        if ($LASTEXITCODE -ne 0) { throw "$selectedProvider status check failed." }
    }
    Write-Host 'Native sign-in steps finished. Use the draft command to verify each connection with the sample invoice.'
} finally {
    Pop-Location
}
