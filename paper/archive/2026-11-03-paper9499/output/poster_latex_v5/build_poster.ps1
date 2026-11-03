$ErrorActionPreference = 'Stop'

$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$texName = 'paper9499_A0_poster_v5.tex'
$texPath = Join-Path $sourceDir $texName
$buildDir = Join-Path $sourceDir 'qa\build'
$deliverDir = Join-Path (Split-Path -Parent $sourceDir) 'pdf'
$deliverPdf = Join-Path $deliverDir 'paper9499_A0_poster_v5.pdf'
$buildPdf = Join-Path $buildDir 'paper9499_A0_poster_v5.pdf'

function Find-Compiler {
    $names = @('tectonic.exe', 'pdflatex.exe', 'xelatex.exe')
    foreach ($name in $names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return $command.Source
        }
    }

    $candidates = @(
        'C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe',
        'C:\Users\Administrator\AppData\Local\Programs\MiKTeX\miktex\bin\x64\pdflatex.exe',
        'C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe',
        'C:\Users\Administrator\AppData\Local\Programs\MiKTeX\miktex\bin\x64\xelatex.exe',
        'C:\Program Files\Tectonic\tectonic.exe',
        'C:\Users\Administrator\AppData\Local\Programs\Tectonic\tectonic.exe'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $texPath)) {
    throw "Missing LaTeX source: $texPath"
}

$compiler = Find-Compiler
if ($null -eq $compiler) {
    Write-Error 'No Tectonic, pdfLaTeX, or XeLaTeX compiler was found.'
    Write-Error 'Install MiKTeX with: winget install --id MiKTeX.MiKTeX --accept-package-agreements --accept-source-agreements'
    exit 2
}

New-Item -ItemType Directory -Force -Path $buildDir, $deliverDir | Out-Null
Get-ChildItem -LiteralPath $buildDir -Force -ErrorAction SilentlyContinue | Remove-Item -Force -Recurse

$engine = [System.IO.Path]::GetFileName($compiler).ToLowerInvariant()
Push-Location $sourceDir
try {
    if ($engine -eq 'tectonic.exe') {
        & $compiler '--keep-logs' '--outdir' $buildDir $texName
    }
    else {
        & $compiler '-interaction=nonstopmode' '-halt-on-error' '-file-line-error' ("-output-directory=" + $buildDir) $texName
    }
    if ($LASTEXITCODE -ne 0) {
        throw "LaTeX compilation failed with exit code $LASTEXITCODE. See $buildDir for the log."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $buildPdf)) {
    throw "Compiler completed without producing $buildPdf"
}

Copy-Item -LiteralPath $buildPdf -Destination $deliverPdf -Force
$hash = (Get-FileHash -LiteralPath $deliverPdf -Algorithm SHA256).Hash
$versionLines = @(& $compiler '--version' 2>&1)
$version = ($versionLines | Where-Object { $_ -match 'This is (pdfTeX|XeTeX)|MiKTeX' } | Select-Object -First 1)
if ([string]::IsNullOrWhiteSpace($version)) {
    $version = ($versionLines | Select-Object -First 1)
}
$infoPath = Join-Path $sourceDir 'qa\build_info.txt'
@(
    "Compiler: $compiler",
    "Version: $version",
    "Source: $texPath",
    "Output: $deliverPdf",
    "SHA256: $hash",
    "Built: $([DateTime]::Now.ToString('s'))"
) | Set-Content -LiteralPath $infoPath -Encoding UTF8

Write-Output "Built $deliverPdf"
Write-Output "SHA256 $hash"



